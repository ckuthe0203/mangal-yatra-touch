# Mangal Yatra: Mars EVA navigation display

A handheld/wrist-mounted display (Raspberry Pi 5 + Touch Display 2) that guides an astronaut along a safe route on Mars. It layers NASA terrain, imagery, thermal and environmental data, and it runs fully offline on the device, because the 4–24 minute signal delay to Earth rules out relying on mission control. NASA Space Apps 2026: *Interplanetary Survival Guide: Martian Map*.

```
mangal-yatra/
  backend/    Python server: WebSocket, route simulator, alerts, sensors, voice
  hud/        Web app shown on the Touch Display 2 (MapLibre, works offline)
  data/jezero Sample mission package (illustrative coordinates, works right away)
  pipeline/   Laptop-only scripts that turn NASA rasters into a mission package
```

## 1. Run it on your laptop (5 minutes)

```bash
pip install aiohttp numpy
python backend/server.py                 # add --time-scale 30 to walk faster
```
Open **http://localhost:8080**. The astronaut starts walking the route right away.

| Key | Action | On the Touch Display 2 |
|---|---|---|
| ← → | turn head | BNO085 IMU |
| Enter | type a voice command ("show hazards", "how far to the next waypoint", "status", "what's the dust like") | push-to-talk mic |
| N / P / S | next waypoint / pause / SOS | glove buttons |
| 1–5 | toggle layers: imagery, slope, hazards, route, science | "cycle layer" button |
| + / − | zoom | voice |

Spoken replies use the browser's voice on the laptop and Piper on the Pi.

### While developing: auto-reload

```bash
python dev.py --time-scale 30          # takes the same options as backend/server.py
```
- Save a file in `hud/` and every open browser reloads on its own. The walk keeps its progress.
- Save a file in `backend/` or `data/` and the server restarts, then the browsers reload. The walk starts over.
- If the server crashes (for example, a syntax error), fix the file and save it; it restarts by itself.
- The server sends `Cache-Control: no-store`, so even a plain F5 always loads the latest files.
- Always open the page through the server (`http://localhost:<port>/`), not as a file. Otherwise you get stuck on "Connecting to helmet...".

## 2. How it works

- **`backend/server.py`** sends the full HUD state 5 times a second over `/ws`: position, heading, next waypoint, suit readings, conditions and alerts. It also takes commands from the HUD, the buttons and voice.
- **`backend/sim.py`**: there's no GPS on Mars, so the astronaut's position is simulated along the planned route at 1 m/s, with stops at each waypoint.
- **Alerts:**
  - Warns when you get close to a hazard polygon, and gives a critical alert if you're inside one.
  - **Turn-back rule:** critical alert if O₂ left < time to walk back to the habitat + 30 min reserve.
  - Warnings for high dust opacity, solar particle events and low suit battery.
- **`backend/voice.py`**:
  - Speech to text: Vosk.
  - Understanding: keyword rules first (instant, reliable for the demo). An LLM handles free-form requests the rules miss and turns them into command JSON.
  - Speech out: Piper.
- **`backend/sensors.py`** reads the BNO085 (game rotation vector only: **no magnetometer**, since Mars has no global magnetic field), the BME280 and the GPIO buttons. Every part falls back to mock data on a laptop.

### WebSocket messages
```jsonc
// backend -> HUD
{"type":"state","pos":[lon,lat],"heading":305.2,"next_wp":{"name":"...","dist_m":175,...},
 "suit":{"o2_min":401,"battery_pct":96,"temp_c":22.1,"pressure_kpa":29.6},
 "conditions":{...},"alerts":[{"level":"warn","msg":"Steep slope >25 deg 28 m"}]}
{"type":"say","text":"Next: Delta front outcrop, 585 meters"}
{"type":"command","action":"toggle_layer","layer":"hazards"}
// HUD -> backend
{"type":"command","action":"next_waypoint"}
{"type":"voice_text","text":"show me the slope"}
```

### Quick base map (no GDAL needed)

Without image tiles the map background is just black. To get real imagery in a minute:
```bash
pip install pillow numpy
python pipeline/fetch_ctx_tiles.py data/jezero
```
This downloads the MRO CTX mosaic (about 5 m/px; NASA/JPL/MSSS/Caltech Murray Lab, served by Esri "OnMars") for the area around the route and hazards. It saves the tiles to `data/jezero/tiles/imagery/`, so they work offline on the Pi. CTX is black-and-white, so the script colours it Mars red by default; add `--color dusty` for a softer look or `--color gray` for the original. Restart the server afterwards (`dev.py` restarts by itself). The HiRISE pipeline below replaces these with sharper 25 cm imagery.

## 3. Build the real Jezero map (laptop, needs GDAL)

```bash
conda install -c conda-forge gdal numpy pillow     # Linux/Mac. On Windows + Python 3.13 without conda:
#   pip install gdal-3.13.3-cp313-cp313-win_amd64.whl   (from github.com/cgohlke/geospatial-wheels; PyPI has no Windows build)
python pipeline/fetch_hirise.py pipeline/site_jezero.json   # cuts the site out of the HiRISE DTM + 25 cm mosaic (~3 min)
# THEMIS thermal inertia (1.7 MB): https://zenodo.org/records/4931348 -> raw/Jezero_Thermal_Inertia_v1.tiff
python pipeline/build_site.py pipeline/site_jezero.json     # ~10 min; add --skip-tiles to redo only hazards/route
python backend/server.py                                    # uses data/jezero_real automatically once it exists
```

Result for the Jezero site: 28 steep-slope zones (>25°, HiRISE DTM) and 2 loose-sand zones (THEMIS thermal inertia
below 175; the site has no values under 150, so the floor here is mostly firm), and a 1.95 km A\* route whose steepest
point is 9.2° and which stays at least 126 m from every hazard.

Data used (set in `pipeline/site_jezero.json`):

| Layer | Source | Notes |
|---|---|---|
| Terrain / slope | USGS **Mars 2020 TRN HiRISE DTM mosaic**, 1 m/px (DOI 10.5066/P9REJ9JN) | Streamed with `/vsicurl/`, so only your bounding box is downloaded, not the full 1.8 GB file |
| Imagery | USGS **Mars 2020 TRN HiRISE orthomosaic** (DOI 10.5066/P9QJDP48) | Download it and save as `raw/jezero_hirise_ortho.tif` |
| Soft ground | **THEMIS-derived thermal inertia of Jezero** (Zenodo 4931348, 1.7 MB GeoTIFF) | Save as `raw/Jezero_Thermal_Inertia_v1.tiff`. Low thermal inertia means loose sand or dust |
| Weather / dust | Perseverance **MEDA** | Enter values for your chosen sol in `conditions` |
| Radiation | Curiosity **RAD** surface dose | Gale Crater average, used as a proxy |

The pipeline:
1. Computes slope.
2. Turns ground steeper than 25° and soft ground into hazard polygons.
3. Plans an **A\* route** that stays under 15° slope and avoids soft ground (`pipeline/planner.py`).
4. Builds web map tiles.

Any hazards you trace by hand in QGIS (such as boulder fields seen in HiRISE) can be merged in with `manual_hazards`.

> The sample `data/jezero` package uses illustrative coordinates and hazard outlines near the Perseverance landing site, so the demo works before the pipeline has run. Replace it with real pipeline output before you submit.

## Mission Control on Earth: Gemini EVA reports

The wrist unit never needs the internet. The habitat keeps an **EVA log** (stops, alerts, SOS, messages, oxygen and
battery trend; `logs/`). The log is sent to Earth with the Mars radio delay, **Gemini** (Google's Gemini API) writes the
mission report at Mission Control, and the report travels back to the wrist display.

- On the wrist: say **"mission report"** (or press **G**). It also starts automatically when the last stop is reached.
- On Earth: open **http://localhost:8090/mission-control** for live EVA status, the event log, the report, and
  questions about the EVA ("How did oxygen use compare to plan?"). Gemini is told to use only numbers from the log.
- Setup: get a free key at **aistudio.google.com** -> *Get API key*, put it in `backend/secrets.env` as
  `GEMINI_API_KEY=...` (git-ignored). Model: `GEMINI_MODEL`, default `gemini-3.5-flash-lite`.
- Without a key, a plain offline summary is produced instead, so the demo always works.

## Earth link: Mission Control by SMS (Twilio)

The helmet works offline; the habitat relays messages to Earth through **Twilio**, held back by the real
Earth-Mars radio delay (computed from the planets' orbits for today's date, 5-22 min; `backend/mars_time.py`).

| Mars -> Earth (SMS to Mission Control's phone) | Earth -> Mars (reply to the Twilio number) |
|---|---|
| SOS with position + O2 (and a phone call if `MISSION_CONTROL_CALL=1`) | Shown as a banner on the HUD and read aloud, "sent 11 min ago" |
| Critical alerts (turn back, inside a hazard), once each | Polled every 10 s; no public webhook or tunnel needed |
| Arrival at each science stop | |
| Dictated: "tell mission control we found layered rocks" | Ask "any messages from Earth?" for what is in transit |

Setup:
1. Create a Twilio account (the free trial works) and get a phone number. On a trial, add Mission Control's phone under **Verified Caller IDs**.
2. Copy `backend/secrets.example.env` to `backend/secrets.env` and fill in your SID, auth token and the two numbers. `secrets.env` is git-ignored.
3. `EARTH_DELAY_S=20` gives a 20-second delay for filming; remove it for the real one.

Without credentials it runs in **simulated** mode: messages are logged and the HUD counts them down, nothing is sent.
Press **E** to simulate a reply from Earth. At most 25 SMS are sent per server run, to protect trial credit.

## 4. Arduino sensor hub

The BNO085, BME280, glove buttons, buzzer and optional extra fan connect to the **Arduino**. The Arduino connects to the Pi with **one USB cable**, which carries both power and data.

```
BNO085 + BME280 (Qwiic) ─┐                                    ┌─> arduino_link.py -> backend -> HUD
Buttons D2-D6 ───────────┼─> Arduino ──USB serial (JSON)──> Pi ┤
Buzzer D8, fan D9 <──────┘                                    └─ sends {"cpu":67}, {"buzz":3}
```

1. In the Arduino IDE, install the libraries **Adafruit BNO08x** and **Adafruit BME280 Library**.
2. Open `arduino/helmet_hub/helmet_hub.ino`, choose your board and upload. Wiring is described at the top of the file. The BNO085 needs a board with more memory than an Uno/Nano, such as a Nano Every, Nano 33 IoT, Uno R4 or ESP32.
3. Check it in the Serial Monitor at 115200 baud. You should see `{"hello":...,"imu":1,"bme":1}` followed by 10 readings per second.
4. Close the Serial Monitor, then start the backend with the Arduino's port:
   ```bash
   python backend/server.py --arduino /dev/ttyACM0     # Pi / Linux (or /dev/ttyUSB0)
   python backend/server.py --arduino COM3             # Windows laptop
   python backend/server.py --arduino /dev/cu.usbmodem1101   # Mac
   ```
   `pip install pyserial` is needed for this.

What happens at runtime:
- Head direction and suit readings come from the Arduino. Buttons act exactly like the keyboard shortcuts.
- Critical alerts beep the buzzer 3 times.
- Every second the Pi sends its CPU temperature, and the Arduino sets the extra fan speed: slow below 50 °C, full at 75 °C. If the Pi goes quiet for 5 seconds, the fan goes to full.
- If the USB cable comes loose, the backend reconnects by itself, and the HUD keeps running in the meantime.
- Press **R** or say "recenter" while facing along the route to align the heading.

## 5. Run it on the Raspberry Pi 5 + Touch Display 2

```bash
sudo apt install -y libportaudio2
pip install --break-system-packages aiohttp numpy pyserial adafruit-circuitpython-bno08x \
    adafruit-circuitpython-bme280 vosk sounddevice piper-tts
# Speech model: download vosk-model-small-en-us-0.15 into models/
# Voice for Piper: e.g. en_US-lessac-medium.onnx into models/
export PIPER_MODEL=models/en_US-lessac-medium.onnx
python backend/server.py --time-scale 1 &
chromium-browser --kiosk --noerrdialogs --disable-infobars --force-device-scale-factor=1.5 "http://localhost:8080/?device=1"
```
- `?device=1` hides the keyboard help. Touch screens are also detected automatically.
- **Touch controls** (bottom bar, sized for gloves): Talk (hold to speak if a mic + Vosk are set up, otherwise tap to type), Next, Zoom +/−, Pause/Resume, Center (re-align heading), SOS. Tap the layer chips to show or hide layers.
- **5" Touch Display 2:** it has the same 720×1280 pixels as the 7" one on a much smaller screen, so `--force-device-scale-factor=1.5` makes text and buttons 1.5× larger (the HUD then lays out at 480×853). Use `1.25` on the 7" display, or leave it out.
- **Orientation:** the layout adapts to the display's native portrait (720×1280) or landscape; portrait leaves more of the map visible on the 5". To rotate, use Raspberry Pi OS's **Screen Configuration** tool.
- **Heading:** the BNO085 should be fixed to the display's case, so the map turns as the astronaut turns while holding the screen.
- On newer Raspberry Pi OS the browser command may be `chromium` instead of `chromium-browser`.
- **With the Arduino**, add `--arduino /dev/ttyACM0` to the server command (see section 4). Without it, buttons can go straight to the Pi's GPIO (BCM, wired to GND): GPIO5 next waypoint, GPIO6 zoom, GPIO13 cycle layer, GPIO19 SOS, GPIO26 push-to-talk.
- **LLM (optional):** set `LLM_URL` / `LLM_MODEL` to an Ollama-compatible server. Ollama on the CPU works, for example with `qwen2.5:1.5b` or Gemma 4 E2B. If the AI HAT+ 2's LLM server has an Ollama-compatible API, point `LLM_URL` at it. Without an LLM, the keyword rules still handle all the demo commands.
