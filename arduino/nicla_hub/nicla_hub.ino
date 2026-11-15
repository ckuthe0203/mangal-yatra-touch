/*
  Mangal Yatra - helmet sensor hub on the Arduino Nicla Sense ME.
  Same USB-serial JSON protocol as arduino/helmet_hub, so run:
    python backend/server.py --arduino /dev/ttyACM0
  Heading = game rotation vector (gyro + accel, no magnetometer: Mars has no magnetic field).
  Press R in the HUD (or say "recenter") while facing along the route.
  Connect to the Pi with a micro-USB data cable only (Nicla pins are 1.8 V).
*/
#include "Arduino_BHY2.h"

SensorQuaternion gameRV(SENSOR_ID_GAMERV);
Sensor temperature(SENSOR_ID_TEMP);
Sensor humidity(SENSOR_ID_HUM);
Sensor pressure(SENSOR_ID_BARO);
SensorBSEC bsec(SENSOR_ID_BSEC);

float yawOffset = 0;
unsigned long lastPrint = 0;
String rx;

// If the map turns the wrong way when you turn your head, change this to +1.0.
const float YAW_SIGN = -1.0;

float rawYawDeg() {
  float x = gameRV.x(), y = gameRV.y(), z = gameRV.z(), w = gameRV.w();
  float yaw = atan2(2.0f * (w * z + x * y), 1.0f - 2.0f * (y * y + z * z));
  return yaw * 180.0f / PI;
}

float heading() {
  float h = YAW_SIGN * rawYawDeg() - yawOffset;
  while (h < 0) h += 360;
  while (h >= 360) h -= 360;
  return h;
}

void handleLine(const String &line) {
  if (line.indexOf("\"zero\"") >= 0) yawOffset += heading();
}

void setup() {
  Serial.begin(115200);
  BHY2.begin();
  gameRV.begin();
  temperature.begin();
  humidity.begin();
  pressure.begin();
  bsec.begin();
  delay(500);
  Serial.println(F("{\"hello\":\"mangal-yatra-nicla\",\"imu\":1,\"bme\":1}"));
}

void loop() {
  BHY2.update();
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleLine(rx); rx = ""; }
    else if (rx.length() < 120) rx += c;
  }
  if (millis() - lastPrint >= 100) {
    lastPrint = millis();
    Serial.print(F("{\"yaw\":"));   Serial.print(heading(), 1);
    Serial.print(F(",\"temp\":"));  Serial.print(temperature.value(), 1);
    Serial.print(F(",\"pres\":"));  Serial.print(pressure.value(), 1);
    Serial.print(F(",\"hum\":"));   Serial.print(humidity.value(), 1);
    Serial.print(F(",\"iaq\":"));   Serial.print(bsec.iaq());
    Serial.print(F(",\"co2\":"));   Serial.print(bsec.co2_eq());
    Serial.println(F("}"));
  }
}
