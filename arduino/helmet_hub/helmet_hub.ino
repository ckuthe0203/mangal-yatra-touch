/*
  Mangal Yatra - helmet sensor hub (Arduino)

  Reads head direction (IMU), suit telemetry (BME280) and glove buttons, controls the cooling fan
  and the alert buzzer, and talks to the Raspberry Pi over USB serial as one JSON line per message.

  Arduino -> Pi (10x per second):
    {"yaw":312.4,"temp":22.1,"pres":1012.3,"hum":40,"fan":120}
  Arduino -> Pi (button events):
    {"btn":"next_waypoint","down":1}
  Pi -> Arduino:
    {"buzz":3}     beep 3 times (critical alert)
    {"cpu":67}     Pi CPU temperature in C -> automatic fan speed
    {"fan":200}    force fan speed 0-255 (-1 = back to automatic)
    {"zero":1}     reset yaw to 0 (recenter)

  BOARD
    Default setup is the team's parts: BNO085 + BME280 (Qwiic/STEMMA QT boards).
    The BNO085 library needs more memory than an Uno/Nano (ATmega328) has, so use a board such as
    Arduino Nano Every, Nano 33 IoT, Uno R4, or an ESP32. Only an MPU-6050 fits on an Uno: set USE_BNO085 to 0.

  WIRING
    BNO085 + BME280 on one Qwiic chain. Connect the chain to the Arduino with a Qwiic-to-jumper cable:
      black GND -> GND, red 3.3V -> 3.3V, blue SDA -> SDA, yellow SCL -> SCL
      (SDA/SCL pins: Uno/Uno R4/Nano/Nano Every = A4/A5; ESP32 = GPIO21/22; or the board's Qwiic port if it has one)
    Buttons (other leg to GND, internal pull-ups used):
      D2 next waypoint | D3 zoom in | D4 cycle layer | D5 SOS | D6 push-to-talk
    Fan:    D9 (PWM) -> 1k resistor -> gate/base of a logic-level MOSFET (e.g. IRLZ44N) or NPN transistor.
            Fan + to 5V, fan - to MOSFET drain. Add a flyback diode (1N4007) across the fan.
    Buzzer: D8 -> active/passive piezo buzzer -> GND
    Status LED: built-in LED on D13 blinks while data is flowing.

  LIBRARIES (Arduino IDE > Library Manager): "Adafruit BNO08x" and "Adafruit BME280 Library"
  (accept the dependencies it offers: Adafruit Unified Sensor, Adafruit BusIO).

  The Pi 5's Active Cooler stays on the Pi's own fan connector. D9 is for the optional extra 30 mm helmet fan.
*/

#include <Wire.h>
#include <Adafruit_BME280.h>

#define USE_BNO085 1          // 1 = BNO085 (team build), 0 = MPU-6050 (fallback that fits on an Uno)

#if USE_BNO085
#include <Adafruit_BNO08x.h>
Adafruit_BNO08x bno;
sh2_SensorValue_t bnoValue;
#endif

// ---------------- pins ----------------
const uint8_t BUTTON_PINS[] = {2, 3, 4, 5, 6};   // on an ESP32 use e.g. {13, 14, 25, 26, 27}
const char* BUTTON_NAMES[]  = {"next_waypoint", "zoom_in", "cycle_layer", "sos", "ptt"};
const uint8_t NUM_BUTTONS = 5;
const uint8_t FAN_PIN = 9;
const uint8_t BUZZER_PIN = 8;
const uint8_t LED_PIN = 13;

// ---------------- settings ----------------
const unsigned long SEND_EVERY_MS = 100;     // 10 Hz
const unsigned long DEBOUNCE_MS = 30;
const unsigned long PI_TIMEOUT_MS = 5000;    // no CPU temp from the Pi for 5 s -> fan to full (fail-safe)
const uint8_t FAN_MIN = 80;                  // lowest PWM that still spins your fan; tune this

// ---------------- state ----------------
Adafruit_BME280 bme;
bool bmeOk = false;
bool imuOk = false;
const uint8_t MPU_ADDR = 0x68;
float gyroBiasZ = 0;
float yaw = 0;                               // degrees, 0..360, relative to power-on direction
unsigned long lastImuMicros = 0;

bool btnState[NUM_BUTTONS];
bool btnLastRead[NUM_BUTTONS];
unsigned long btnChangedAt[NUM_BUTTONS];

int fanForced = -1;                          // -1 = automatic
int cpuTemp = -1;
unsigned long lastCpuMsg = 0;
uint8_t fanPwm = 255;

uint8_t beepsLeft = 0;
unsigned long nextBeepAt = 0;
bool beepOn = false;

unsigned long lastSend = 0;
char rxBuf[64];
uint8_t rxLen = 0;

// ================= MPU-6050 (raw registers, no library = small and fast) =================
void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

int16_t mpuReadGyroZRaw() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x47);                          // GYRO_ZOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, (uint8_t)2);
  if (Wire.available() < 2) return 0;
  return (int16_t)((Wire.read() << 8) | Wire.read());
}

bool mpuBegin() {
  Wire.beginTransmission(MPU_ADDR);
  if (Wire.endTransmission() != 0) return false;
  mpuWrite(0x6B, 0x00);                      // wake up
  mpuWrite(0x1A, 0x03);                      // low-pass filter ~44 Hz
  mpuWrite(0x1B, 0x00);                      // gyro range +-250 deg/s -> 131 LSB per deg/s
  delay(100);
  // Calibrate gyro drift: keep the helmet still for ~2 seconds after power-on.
  long sum = 0;
  for (int i = 0; i < 400; i++) { sum += mpuReadGyroZRaw(); delay(5); }
  gyroBiasZ = sum / 400.0;
  lastImuMicros = micros();
  return true;
}

void mpuUpdate() {
  unsigned long now = micros();
  float dt = (now - lastImuMicros) / 1e6;
  lastImuMicros = now;
  float rate = (mpuReadGyroZRaw() - gyroBiasZ) / 131.0;   // deg/s
  if (fabs(rate) < 0.3) rate = 0;                          // ignore tiny noise to reduce drift
  yaw -= rate * dt;                                        // sign: turning right increases heading
  while (yaw < 0) yaw += 360;
  while (yaw >= 360) yaw -= 360;
}

#if USE_BNO085
float bnoYaw() {
  // Game rotation vector = gyro + accelerometer only (Mars has no global magnetic field).
  if (bno.getSensorEvent(&bnoValue) && bnoValue.sensorId == SH2_GAME_ROTATION_VECTOR) {
    float r = bnoValue.un.gameRotationVector.real, i = bnoValue.un.gameRotationVector.i;
    float j = bnoValue.un.gameRotationVector.j, k = bnoValue.un.gameRotationVector.k;
    float y = atan2(2 * (r * k + i * j), 1 - 2 * (j * j + k * k)) * 180.0 / PI;
    return fmod(y + 360.0, 360.0);
  }
  return -1;
}
#endif

// ================= buttons =================
void readButtons() {
  for (uint8_t b = 0; b < NUM_BUTTONS; b++) {
    bool pressed = digitalRead(BUTTON_PINS[b]) == LOW;    // pull-up: LOW = pressed
    if (pressed != btnLastRead[b]) { btnLastRead[b] = pressed; btnChangedAt[b] = millis(); }
    if (millis() - btnChangedAt[b] > DEBOUNCE_MS && pressed != btnState[b]) {
      btnState[b] = pressed;
      Serial.print(F("{\"btn\":\""));
      Serial.print(BUTTON_NAMES[b]);
      Serial.print(F("\",\"down\":"));
      Serial.print(pressed ? 1 : 0);
      Serial.println(F("}"));
    }
  }
}

// ================= fan =================
void updateFan() {
  if (fanForced >= 0) {
    fanPwm = fanForced;
  } else if (cpuTemp < 0 || millis() - lastCpuMsg > PI_TIMEOUT_MS) {
    fanPwm = 255;                                          // no news from the Pi: play it safe
  } else if (cpuTemp <= 50) {
    fanPwm = FAN_MIN;
  } else if (cpuTemp >= 75) {
    fanPwm = 255;
  } else {
    fanPwm = map(cpuTemp, 50, 75, FAN_MIN, 255);           // linear ramp 50-75 C
  }
  analogWrite(FAN_PIN, fanPwm);
}

// ================= buzzer (non-blocking) =================
void updateBuzzer() {
  if (beepsLeft == 0 || millis() < nextBeepAt) return;
  beepOn = !beepOn;
  digitalWrite(BUZZER_PIN, beepOn ? HIGH : LOW);
  if (!beepOn) beepsLeft--;
  nextBeepAt = millis() + (beepOn ? 150 : 120);
}

// ================= commands from the Pi =================
int jsonInt(const char* line, const char* key, bool* found) {
  const char* p = strstr(line, key);
  *found = (p != NULL);
  if (!p) return 0;
  p = strchr(p, ':');
  return p ? atoi(p + 1) : 0;
}

void handleLine(const char* line) {
  bool f;
  int v = jsonInt(line, "\"buzz\"", &f);
  if (f) { beepsLeft = constrain(v, 0, 10); nextBeepAt = millis(); beepOn = false; }
  v = jsonInt(line, "\"cpu\"", &f);
  if (f) { cpuTemp = v; lastCpuMsg = millis(); }
  v = jsonInt(line, "\"fan\"", &f);
  if (f) { fanForced = (v < 0) ? -1 : constrain(v, 0, 255); }
  jsonInt(line, "\"zero\"", &f);
  if (f) { yaw = 0; }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (rxLen > 0) { rxBuf[rxLen] = 0; handleLine(rxBuf); rxLen = 0; }
    } else if (rxLen < sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = c;
    } else {
      rxLen = 0;                                           // line too long: drop it
    }
  }
}

// ================= main =================
void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(FAN_PIN, OUTPUT);
  analogWrite(FAN_PIN, 255);                               // fan full until the Pi reports in
  for (uint8_t b = 0; b < NUM_BUTTONS; b++) {
    pinMode(BUTTON_PINS[b], INPUT_PULLUP);
    btnState[b] = btnLastRead[b] = false;
    btnChangedAt[b] = 0;
  }

  bmeOk = bme.begin(0x76) || bme.begin(0x77);
#if USE_BNO085
  imuOk = (bno.begin_I2C(0x4A) || bno.begin_I2C(0x4B)) && bno.enableReport(SH2_GAME_ROTATION_VECTOR, 10000);   // 0x4A Adafruit, 0x4B SparkFun
#else
  digitalWrite(LED_PIN, HIGH);                             // LED on = calibrating, keep still
  imuOk = mpuBegin();
  digitalWrite(LED_PIN, LOW);
#endif

  Serial.print(F("{\"hello\":\"mangal-yatra-hub\",\"imu\":"));
  Serial.print(imuOk ? 1 : 0);
  Serial.print(F(",\"bme\":"));
  Serial.print(bmeOk ? 1 : 0);
  Serial.println(F("}"));
}

void loop() {
#if USE_BNO085
  if (imuOk) {
    if (bno.wasReset()) bno.enableReport(SH2_GAME_ROTATION_VECTOR, 10000);   // sensor rebooted: re-enable
    float y = bnoYaw(); if (y >= 0) yaw = y;
  }
#else
  if (imuOk) mpuUpdate();
#endif
  readButtons();
  readSerial();
  updateBuzzer();

  if (millis() - lastSend >= SEND_EVERY_MS) {
    lastSend = millis();
    updateFan();
    Serial.print(F("{\"yaw\":"));
    if (imuOk) Serial.print(yaw, 1); else Serial.print(F("null"));
    if (bmeOk) {
      Serial.print(F(",\"temp\":")); Serial.print(bme.readTemperature(), 1);
      Serial.print(F(",\"pres\":")); Serial.print(bme.readPressure() / 100.0, 1);   // hPa
      Serial.print(F(",\"hum\":"));  Serial.print(bme.readHumidity(), 0);
    }
    Serial.print(F(",\"fan\":")); Serial.print(fanPwm);
    Serial.println(F("}"));
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));            // heartbeat blink
  }
}
