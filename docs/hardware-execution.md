# Mangal Yatra: Hardware Execution Plan

Step-by-step build for the helmet HUD. It follows the timeline in `plan-execution.md` and uses the parts in `hardware-list.md`.

**Rule for the whole build:** every phase ends with a test. Don't start the next phase until the test passes, and keep the laptop fallback demo working at all times.

| Phase | When | Result |
|---|---|---|
| 1. Pi setup | Sat 7:15 to 8:15 PM | Pi boots, SSH works, no power or heat warnings |
| 2. Display + kiosk | Sat 8:15 to 10:00 PM | Pi boots straight into the HUD page |
| 3. IMU head tracking | Sat 10:00 PM to 1:00 AM | Map rotates when you turn your head |
| 4. Voice commands | Sun 7:00 to 10:00 AM | 3+ spoken commands change the HUD |
| 5. AI HAT+ 2 / Gemma (optional) | Sun, only if 1 to 4 are done | Spoken questions get answers |
| 6. Optics + helmet | Sun 10:00 AM to 12:30 PM | Wearable demo |
| 7. Final tests | Sun before filming | Pre-demo checklist all green |

---

## Phase 1: Pi setup (about 1 hour)

### 1.1 Assemble
1. Attach the **Active Cooler** to the Pi 5 (push pins into the mounting holes, plug the fan cable into the FAN connector).
2. If using the **AI HAT+ 2** now: fit the stacking header and spacers, connect the PCIe ribbon cable to the Pi's PCIe connector, then seat the HAT. Check the cooler still has clearance. You can also leave the HAT off until Phase 5.
3. Don't connect sensors yet.

### 1.2 Flash the OS
1. On the laptop, open **Raspberry Pi Imager**.
2. Choose: Device **Raspberry Pi 5**, OS **Raspberry Pi OS (64-bit)** (full desktop version, needed for Chromium), your microSD card.
3. In the settings: set hostname `mangalyatra`, a username and password, Wi-Fi (venue network or your phone hotspot), and **enable SSH**.
4. Write the card, insert it into the Pi, connect the 27W supply.

### 1.3 First boot
```bash
ssh <user>@mangalyatra.local
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config nonint do_i2c 0      # enable I2C for the IMU
sudo apt install -y python3-venv i2c-tools git
python3 -m venv --system-site-packages ~/venv
source ~/venv/bin/activate
sudo reboot
```

### Test 1
```bash
vcgencmd get_throttled     # want: throttled=0x0 (no undervoltage or throttling)
vcgencmd measure_temp      # want: under ~60°C at idle with the cooler
```
If `get_throttled` isn't `0x0`, fix the power supply or cable before anything else.

---

## Phase 2: Display + kiosk (about 1.5 hours)

### 2.1 Connect the display
- **HDMI screen:** micro-HDMI port **HDMI0** (the one next to the USB-C power port) to the display.
- **DSI screen:** ribbon cable to one of the two MIPI ports, contacts facing the right way (check the display's guide).
- Boot and confirm the desktop appears. Set resolution under *Preferences > Screen Configuration* if needed.

### 2.2 Serve the HUD locally
Copy the HUD web app and data from the laptop, then serve it on the Pi:
```bash
# from the laptop
scp -r ./hud <user>@mangalyatra.local:~/hud

# on the Pi (test manually first)
cd ~/hud && python3 -m http.server 8000
```
Make it start on boot with a systemd service, `/etc/systemd/system/hud-web.service`:
```ini
[Unit]
Description=Mangal Yatra HUD web server
After=network.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/hud
ExecStart=/usr/bin/python3 -m http.server 8000
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now hud-web
```

### 2.3 Chromium kiosk on boot
Current Raspberry Pi OS uses the labwc desktop. Add to `~/.config/labwc/autostart` (create it if missing):
```bash
chromium --kiosk --noerrdialogs --disable-infobars --incognito http://localhost:8000/index.html &
```
If `chromium` isn't found, the binary is called `chromium-browser` on your OS version (`which chromium chromium-browser` to check).

To hide the mouse cursor, also turn off screen blanking: `sudo raspi-config` > *Display Options* > *Screen Blanking* > No.

### Test 2
Reboot. The Pi should go straight to the full-screen HUD with no desktop, no error bars, and the map tiles loading. Pan and zoom should feel smooth.

---

## Phase 3: IMU head tracking (about 3 hours)

### 3.1 Wiring (BNO055 or MPU-6050, I2C)
Power off the Pi before wiring.

| Sensor pin | Pi 5 physical pin |
|---|---|
| VIN / VCC | Pin 1 (3.3V) |
| GND | Pin 6 (GND) |
| SDA | Pin 3 (GPIO 2, SDA) |
| SCL | Pin 5 (GPIO 3, SCL) |

The BME280 (optional suit telemetry) shares the same four pins.

### 3.2 Detect the sensor
```bash
i2cdetect -y 1
```
Expected addresses: **BNO055** `0x28` (or `0x29`), **MPU-6050** `0x68`, **BME280** `0x76` or `0x77`. If nothing appears, recheck wiring and that I2C is enabled.

### 3.3 Install libraries
```bash
source ~/venv/bin/activate
pip install adafruit-blinka adafruit-circuitpython-bno055 websockets
```
(For an MPU-6050, install `adafruit-circuitpython-mpu6050` instead. It has no onboard fusion, so you'd need to integrate the gyro yourself. Prefer the BNO055.)

### 3.4 Sensor service: IMU heading to WebSocket
`~/services/imu_ws.py`:
```python
import asyncio, json, time
import board, adafruit_bno055
import websockets

i2c = board.I2C()
sensor = adafruit_bno055.BNO055_I2C(i2c)
clients = set()

async def handler(ws):
    clients.add(ws)
    try:
        await ws.wait_closed()
    finally:
        clients.discard(ws)

async def broadcast():
    while True:
        euler = sensor.euler  # (heading, roll, pitch) in degrees, may contain None
        if euler and euler[0] is not None:
            msg = json.dumps({"type": "heading", "value": euler[0], "t": time.time()})
            websockets.broadcast(clients, msg)
        await asyncio.sleep(0.05)  # 20 Hz

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await broadcast()

asyncio.run(main())
```
Run it manually first: `python ~/services/imu_ws.py`. Then add a systemd service like `hud-web`, with `ExecStart=/home/<user>/venv/bin/python /home/<user>/services/imu_ws.py`.

**If the BNO055 gives I2C errors or freezes:** this sensor is known to have I2C timing problems on Raspberry Pis. Try lowering the I2C speed (add `dtparam=i2c_arm_baudrate=10000` to `/boot/firmware/config.txt` and reboot) or wire it in UART mode instead.

### 3.5 HUD side
In the HUD page:
```js
const ws = new WebSocket(`ws://${location.hostname}:8765`);
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "heading") {
    map.setBearing(msg.value);   // MapLibre GL; for Leaflet, rotate the map container with CSS
  }
};
```
Add light smoothing (average the last few readings) if the map jitters.

**Keyboard fallback (keep this working):** arrow keys change the bearing, so the laptop demo works without the IMU.

### Test 3
Hold the sensor flat, then turn it. The map rotates the same way and stays put when the sensor is still. If it rotates the wrong way, negate the value (`-msg.value`). If the heading drifts, recalibrate by moving the BNO055 in a figure-eight for a few seconds.

**Checkpoint at 1 AM:** if this isn't working, stop hardware work and help finish the map (see `plan-execution.md`).

---

## Phase 4: Voice commands (about 3 hours)

### 4.1 Microphone
Plug in the USB mic and check it's detected and recording:
```bash
arecord -l                                       # find card number
arecord -D plughw:<card>,0 -f S16_LE -r 16000 -d 5 test.wav
aplay test.wav                                   # needs a USB/Bluetooth speaker (no 3.5mm jack on Pi 5)
```

### 4.2 Offline speech-to-text (Vosk, fixed commands)
```bash
source ~/venv/bin/activate
sudo apt install -y libportaudio2
pip install vosk sounddevice
# download and unzip a small English model, e.g. vosk-model-small-en-us-0.15, into ~/models/
```
`~/services/voice_ws.py` (core idea; merge into the same WebSocket server as the IMU or run it on port 8766):
```python
import json, queue, sounddevice as sd
from vosk import Model, KaldiRecognizer

COMMANDS = {
    "next waypoint": "next_waypoint",
    "show hazards": "toggle_hazards",
    "show resources": "toggle_resources",
    "return to base": "route_home",
    "zoom in": "zoom_in",
    "zoom out": "zoom_out",
}
grammar = json.dumps(list(COMMANDS) + ["[unk]"])  # restrict vocabulary = much better accuracy

model = Model("/home/<user>/models/vosk-model-small-en-us-0.15")
rec = KaldiRecognizer(model, 16000, grammar)
q = queue.Queue()

def callback(indata, frames, time, status):
    q.put(bytes(indata))

with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                       channels=1, callback=callback):
    while True:
        if rec.AcceptWaveform(q.get()):
            text = json.loads(rec.Result()).get("text", "")
            if text in COMMANDS:
                print("command:", COMMANDS[text])
                # send {"type": "command", "value": COMMANDS[text]} over the WebSocket
```
The HUD handles each `command` message (toggle a layer, advance the waypoint, and so on). Map the same commands to number keys for the fallback.

### Test 4
With the helmet on (or the mic where it will sit), say each command 5 times. Aim for at least 4 out of 5 recognized. If accuracy is poor: move the mic closer to the mouth, cut background noise, or shorten the phrases.

---

## Phase 5: AI HAT+ 2 / Gemma (optional, only after Phases 1 to 4 pass)

Timebox this to **90 minutes**. If it isn't working by then, drop it and mention on-device LLM as future work.

1. **Check the HAT is detected:**
   ```bash
   lspci          # should list a Hailo device
   ```
2. Install the AI HAT+ 2 drivers and software following Raspberry Pi's official AI HAT+ 2 documentation.
3. Check whether the Gemma model you want is supported on the HAT. If it isn't, choose one:
   - **CPU fallback:** install Ollama (`curl -fsSL https://ollama.com/install.sh | sh`), then pull the smallest Gemma model available in the Ollama library and test response speed.
   - **Use a model the HAT supports** for the Q&A feature instead of Gemma.
4. Wire it in: voice text that doesn't match a fixed command goes to the LLM with a short system prompt that includes the current waypoint, distance, hazards and suit telemetry. The answer is shown as text on the HUD (and spoken, if you have a speaker).

**Test 5:** "How far to the next waypoint?" gets a correct answer in under ~5 seconds. If it takes longer, show "thinking…" on the HUD or drop the feature.

---

## Phase 6: Optics + helmet (about 2.5 hours)

### 6.1 Beam-splitter layout
```
          eye
           |
   --------/-------   <- beam splitter at ~45°, in front of the eyes
          /
   [ display, screen facing up ]   <- below eye level, near the chin
```
1. Mount the display **face-up** below eye level.
2. Mount the teleprompter glass or acrylic at about **45°** above it so the screen reflects toward the eyes.
3. **Flip the HUD** so text reads correctly in the reflection: add `body { transform: scaleX(-1); }` (or `scaleY(-1)`, depending on the mounting). Put this behind a URL flag like `?mirror=1` so the laptop demo stays normal.
4. Turn display brightness to maximum.
5. **Design tip:** on a beam splitter, black is transparent and bright colors show. A black background with bright green or cyan lines, text and icons looks like a real HUD. Full satellite imagery will look faint, so show it in a smaller minimap panel and keep the main view as bright vector overlays.

### 6.2 Mounting
- Pi, battery bank and cooler go at the **back** of the helmet or in a pouch, to balance the weight of the front display.
- Keep the cooler's air path open. Don't seal the Pi in foam.
- Route the display cable and mic along the inside edge; secure with Velcro and zip ties so nothing tugs on the connectors.
- Leave the face area ventilated; the visor fogs up quickly.

### Test 6
Wear it for 5 minutes. Check: HUD is readable, text isn't mirrored, the map turns with your head, voice works with the helmet on, no cables pull loose, and the Pi stays cool:
```bash
vcgencmd measure_temp      # want: under ~80°C under load (throttling starts around 80 to 85°C)
vcgencmd get_throttled     # want: throttled=0x0
```

---

## Phase 7: Final tests before filming

- [ ] Cold boot: power on and the HUD appears with no keyboard or mouse needed
- [ ] `vcgencmd get_throttled` is `0x0` on the power source you'll use for the demo
- [ ] Heading rotation is the right direction and smooth
- [ ] All voice commands work with the helmet on
- [ ] Mirror flag correct for the beam splitter; off for the laptop
- [ ] 15-minute run without overheating or crashes
- [ ] Laptop fallback demo works with keyboard shortcuts (arrows = heading, numbers = commands)
- [ ] Backup copy of the microSD card image (or at least the `~/hud` and `~/services` folders on the laptop)

## Filming tips
- Record the HUD screen directly (laptop or a screen capture) for clear footage, and a phone shot of someone wearing the helmet for the "real hardware" moment.
- A phone camera held behind the beam splitter can film the reflection, which shows what the astronaut sees.

## If something breaks

| Problem | Quick fix |
|---|---|
| Lightning icon / `get_throttled` not `0x0` | Use the 27W wall supply and a 5A-rated cable |
| Pi overheating | Check the cooler fan spins; open up airflow in the mount |
| Black screen on boot | Try the other micro-HDMI port; check the labwc autostart line |
| IMU not found | Recheck wiring (SDA/SCL swapped is common); run `i2cdetect -y 1` |
| IMU freezes | Lower the I2C speed or switch to UART mode |
| Voice commands missed | Move mic closer; restrict grammar; shorter phrases |
| HAT not in `lspci` | Reseat the PCIe ribbon cable; skip Phase 5 if it still fails |
| Optics unreadable | Brightness up, black background; fall back to a direct screen or phone viewer |
