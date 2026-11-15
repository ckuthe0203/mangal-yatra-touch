# Mangal Yatra: Hardware List

Hardware for the helmet HUD prototype. Items are grouped by priority so you know what to get first if time or stores are limited.

**Tiers**
- **Core:** needed for the HUD to run on the Pi
- **Recommended:** needed for head tracking, voice and the helmet demo
- **Optional:** nice to have, or backups

---

## 1. Compute

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 1 | Raspberry Pi 5, **8GB** | 1 | Core | Runs the browser HUD, sensors, speech-to-text and (optionally) Gemma at the same time. 4GB will swap with Gemma. |
| 2 | Raspberry Pi AI HAT+ 2 | 1 | Recommended | Accelerator for on-device AI. Check early whether it supports the Gemma model you want; fall back to CPU (llama.cpp / Ollama) if not. |
| 3 | Raspberry Pi Active Cooler (official) | 1 | Core | The Pi 5 runs hot, especially inside a closed helmet. Check it fits under the AI HAT+ 2 with the supplied stacking header and spacers. |
| 4 | microSD card, 64GB, A2 / U3 | 1 | Core | Raspberry Pi OS 64-bit. Room for map tiles and model files. Flash a spare if you can. |
| 5 | microSD card reader | 1 | Core | For flashing from the laptop. |

## 2. Power

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 6 | Official Raspberry Pi 27W USB-C power supply (5V / 5A) | 1 | Core | Use for development and the demo if possible. |
| 7 | USB-C PD power bank that can supply **5V / 5A** | 1 | Recommended | For the wearable demo. Most banks only give 3A, which triggers low-power warnings and limits the USB ports. |
| 8 | Short USB-C to USB-C cable rated 5A | 1 | Recommended | A weak cable causes the same undervoltage warnings. |

## 3. Display and optics

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 9 | Small display, 3.5" to 5" | 1 | Core | Either a small HDMI display or the Raspberry Pi Touch Display 2 (DSI). Avoid tiny 0.96" OLEDs; they're too low-resolution for maps. |
| 10 | Micro-HDMI to HDMI cable (or adapter) | 1 | Core | The Pi 5 has micro-HDMI ports only. Skip if using a DSI display. |
| 11 | Pi 5 DSI display cable (22-pin to 15-pin) | 1 | Optional | Only for a DSI screen made for older Pis. The Touch Display 2 includes it. |
| 12 | Beam splitter: teleprompter glass (e.g. 70/30) or clear acrylic sheet | 1 | Recommended | Mounted at about 45° in front of the eyes, reflecting the screen. The image comes out mirrored, so flip the HUD in CSS (`transform: scaleX(-1)`). |
| 13 | Backup: phone + Cardboard-style VR viewer | 1 | Optional | Easiest way to get a sharp image if the optics don't work. |

## 4. Sensors

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 14 | IMU: **BNO055** (preferred) or MPU-6050 | 1 | Recommended | Head direction for rotating the map. BNO055 does sensor fusion onboard, so it's easier. Use orientation only; a compass is useless on Mars. |
| 15 | BME280 temperature / humidity / pressure sensor | 1 | Optional | Mock *suit* telemetry inside the helmet, not Mars weather. |
| 16 | Female-to-female jumper wires | 1 pack | Recommended | IMU and BME280 connect to the Pi's I2C pins (3.3V, GND, SDA, SCL). |
| 17 | Arduino Uno / Nano | 1 | Optional | Only if you want a separate sensor hub over USB serial. The Pi can read the sensors directly. |

## 5. Audio (voice control)

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 18 | USB microphone (mini plug-in or lapel) | 1 | Recommended | For voice commands. A lapel mic placed near the mouth works better inside a helmet. |
| 19 | USB speaker, USB audio adapter + earbud, or Bluetooth earbud | 1 | Optional | For spoken replies. **The Pi 5 has no 3.5mm audio jack.** |

## 6. Helmet and mounting

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 20 | Helmet shell (costume astronaut helmet, motorcycle or bike helmet) | 1 | Recommended | Needs room in front of the face for the beam splitter. |
| 21 | Mounting: Velcro strips, zip ties, hot glue, foam board / cardboard | 1 set | Recommended | Fast and adjustable. 3D-printed brackets if you have time. |
| 22 | Pi 5 case or mounting plate with standoffs | 1 | Optional | Protects the board; keep airflow for the cooler. |
| 23 | Counterweight or rear battery pouch | 1 | Optional | Balance the front-heavy display by putting the battery at the back. |

## 7. Setup and tools

| # | Item | Qty | Tier | Notes |
|---|---|---|---|---|
| 24 | USB keyboard and mouse | 1 | Core | First boot and debugging (or set up SSH and skip). |
| 25 | Laptop | 1 | Core | Data processing (GDAL), development, and the fallback demo. |
| 26 | Hot glue gun, scissors, utility knife, tape | 1 set | Recommended | Building the helmet mount. |
| 27 | USB hub (powered) | 1 | Optional | If the mic, keyboard and other devices run out of ports or power. |

---

## Minimum working setup

If you can only get a few things tonight: **Pi 5 8GB, Active Cooler, 27W power supply, microSD card, small HDMI display with cable, and the BNO055 IMU.** That's enough for a HUD on the Pi that rotates with head movement. Everything else can be added later or shown on the laptop.

## Pre-demo checklist

- [ ] Pi boots straight into Chromium kiosk mode with the HUD
- [ ] No undervoltage warning (lightning icon) on the power source you'll demo with
- [ ] IMU heading updates smoothly; map rotation direction is correct
- [ ] Microphone picks up commands with the helmet on
- [ ] HUD image is flipped correctly for the beam splitter
- [ ] Pi temperature stays below throttling (check with `vcgencmd measure_temp`)
- [ ] Laptop fallback demo ready with keyboard shortcuts
