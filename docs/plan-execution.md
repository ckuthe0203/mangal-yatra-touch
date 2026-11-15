# Mangal Yatra: Plan of Execution

**Event:** NASA Space Apps Challenge 2026, NYU local event (Sat Nov 14 to Sun Nov 15)
**Challenge:** Interplanetary Survival Guide: Martian Map
**Project:** Mangal Yatra, a Martian survival map shown in a helmet HUD, with on-device voice control
**Plan written:** Sat Nov 14, ~6:40 PM ET. About 24 to 28 working hours remain, depending on the submission deadline.

---

## 1. What we're shipping

The challenge asks for a layered, integrated view of a site or route on Mars. It should combine data from several NASA missions and help an astronaut plan and carry out a Marswalk. Judging starts Nov 16, after the event. Global judges will mostly see the **project page and demo video**, not the helmet in person.

So we build in this order:

1. **The map is the product.** Use one site (Jezero Crater) with one planned EVA route and 4 to 6 data layers from different missions.
2. **The HUD is the delivery method.** It's a web page, so the same code runs in a laptop browser and on the Pi in Chromium kiosk mode.
3. **The helmet and voice are a bonus.** They make the demo memorable, but if the hardware fails we still have a full submission.

### Must-have (submit even if nothing else works)
- [ ] Web map of Jezero Crater with at least 4 NASA data layers that line up correctly
- [ ] One planned EVA route with waypoints, distance, slope and hazard notes
- [ ] A HUD view: route arrow, distance to next waypoint, hazard warnings, mock suit telemetry
- [ ] Demo video and a finished project page on the Space Apps site

### Should-have
- [ ] HUD running on the Raspberry Pi 5 in kiosk mode
- [ ] IMU head tracking: the map rotates with head direction
- [ ] Voice commands ("next waypoint", "show hazards", "return to base")

### Nice-to-have
- [ ] Beam-splitter optics mounted in a helmet
- [ ] Local LLM (Gemma) answering free-form questions ("How far to the rover?")

---

## 2. Data layers (all prepared on a laptop, never on the Pi)

| Layer | Source mission / dataset | What it gives the astronaut |
|---|---|---|
| Base imagery | MRO CTX mosaic (HiRISE for close-ups along the route) | Visual terrain |
| Elevation / slope | MGS MOLA, or a HiRISE/CTX DTM where available | Slopes to avoid (flag > 15 to 20°) |
| Rock hazards | HiRISE imagery, rock-abundance products | Boulder fields to route around |
| Ground truth | Perseverance traverse and landing site (Mars 2020) | Real path driven, known safe ground |
| Composition / resources | MRO CRISM mineral maps | Hydrated minerals, a proxy for water ice and science targets |
| Environment | Perseverance MEDA weather, or MAVEN / Mars Odyssey radiation context | Dust, temperature and radiation warnings |

**Processing pipeline (laptop):**
1. Download the crops for Jezero only. Don't download global files.
2. Use GDAL to reproject everything to one Mars coordinate system (IAU Mars 2000, areocentric, consistent units).
3. Crop to the area of interest and run `gdal2tiles` to make small map tiles. Compute slope from the DEM with `gdaldem slope`.
4. Export hazards, waypoints and the route as GeoJSON.
5. Check alignment by overlaying the Perseverance track on the imagery. If they don't match, fix the coordinate system first.

**Shortcut if downloads are slow:** use NASA Mars Trek or the USGS Astropedia tile services directly in the map, and process only the route and hazard GeoJSON ourselves.

---

## 3. Architecture

```
Laptop (prep)                       Raspberry Pi 5 8GB + AI HAT+ 2 (helmet)
-------------                       ---------------------------------------
GDAL -> tiles + GeoJSON  ---->      Local web server (tiles, GeoJSON, HUD page)
                                    Chromium kiosk -> HUD page (Leaflet/MapLibre)
                                    Sensor service (Python): IMU -> WebSocket
                                    Voice service: wake word -> STT -> intent -> WebSocket
                                    (optional) Gemma via llama.cpp/Ollama for Q&A
```

- **HUD front end:** a single HTML/JS page using Leaflet or MapLibre GL, a dark high-contrast theme and large text. It listens on a WebSocket for `heading`, `position`, `command` and `telemetry` messages.
- **Simulated position:** there's no GPS on Mars, so position advances along the planned route on a timer or keypress. Explain that real systems use visual odometry, the IMU and orbiter fixes.
- **Heading:** BNO055 or MPU-6050 IMU. Don't use a magnetometer, since Mars has no global magnetic field.
- **Voice:** use a fixed command list first (Vosk or whisper.cpp tiny for speech-to-text, then keyword matching). Add Gemma only once the command path works.
- **AI HAT+ 2:** check whether it can run the Gemma model we want. If not, run a small Gemma on the Pi CPU with llama.cpp, or use a model the HAT supports. Don't let this block anything.
- **Fallback:** every message the Pi sends can also be sent from keyboard shortcuts on the laptop, so the demo always works.

---

## 4. Timeline

Times are approximate. Confirm the exact submission deadline with the NYU organizers tonight and shift the Sunday blocks to fit.

### Saturday night
| Time | Task | Done when |
|---|---|---|
| 6:45 to 7:15 PM | Lock scope, split work, set up repo and shared folder, confirm deadline and submission rules | Everyone knows their workstream |
| 7:15 to 10:00 PM | **Data:** download Jezero crops, reproject, make tiles and slope<br>**HUD:** map page with base layer, route line and HUD overlay mock<br>**Hardware:** flash Pi OS, set up cooling and power, boot Chromium kiosk to a test page | Tiles load in the browser; Pi shows a page |
| 10:00 PM to 1:00 AM | **Data:** hazards and resource GeoJSON, waypoint table<br>**HUD:** layer toggles, distance to waypoint, hazard alerts, WebSocket client<br>**Hardware:** IMU wired and streaming heading over WebSocket | Map rotates with IMU on the laptop |
| 1:00 AM | **Checkpoint 1:** must-have map works in the laptop browser | If not, drop the helmet work and all-hands on the map |
| 1:00 to 7:00 AM | Sleep in shifts. At least one person sleeps 4 or more hours. | |

### Sunday
| Time | Task | Done when |
|---|---|---|
| 7:00 to 10:00 AM | Deploy HUD to the Pi; voice command path (STT to intents); polish HUD visuals | HUD on the Pi responds to head movement and 3 voice commands |
| 10:00 AM | **Checkpoint 2:** freeze the feature list. Nothing new after this. | |
| 10:00 AM to 12:30 PM | Optics and helmet mount (beam splitter); optional Gemma Q&A; bug fixes | |
| 12:30 to 2:00 PM | Record the demo video: laptop screen recording plus helmet footage | Final video exported |
| 2:00 to 3:30 PM | Project page: summary, NASA data used, how it works, AI usage disclosure, team, links | Draft complete |
| 3:30 PM onward | Final review and submit **at least 1 hour before the deadline** | Submission confirmed |

---

## 5. Team split

| Workstream | Owner | Key outputs |
|---|---|---|
| A. Data and GIS | _teammate / TBD_ | Tiles, slope map, hazard / route / resource GeoJSON, data source list for the project page |
| B. HUD web app | Tanmay | HUD page, layer toggles, route logic, WebSocket client, keyboard fallback |
| C. Hardware and voice | Tanmay (or teammate 2) | Pi setup, IMU service, voice service, helmet mount, optional Gemma |
| D. Story and submission | Shared, led by whoever finishes first Sunday | Video script, project page, slides if needed |

**Handoff contract between A and B:** agree on the file layout tonight so both sides can work in parallel.
```
/data/tiles/{layer}/{z}/{x}/{y}.png
/data/route.geojson        (LineString + Point waypoints with name, elevation, slope)
/data/hazards.geojson      (Polygons with type: slope | rocks | dust; severity 1-3)
/data/resources.geojson    (Points/Polygons with mineral, confidence)
```
B builds with placeholder GeoJSON until A delivers the real files.

---

## 6. Demo video outline (~1 to 2 minutes; check the submission length limit)

1. **Hook (5 s):** "On Mars there's no GPS, no compass and no second chance. Mangal Yatra puts the map inside the helmet."
2. **Problem (10 s):** astronauts on a Marswalk need terrain, hazards, resources and a route home all at once.
3. **Data (20 s):** fly through the layers on the laptop, naming each mission (CTX, HiRISE, MOLA, CRISM, Perseverance).
4. **HUD in action (30 s):** walk the route. Turn your head and the map turns. Say "show hazards" and a slope warning appears.
5. **How it works (15 s):** architecture diagram showing on-device processing with no Earth link needed.
6. **Mars realities (10 s):** no GPS or magnetic field, plus how we handle it.
7. **Close (5 s):** team name, project name, what's next.

---

## 7. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Data downloads too slow or files too big | Use Mars Trek / USGS tile services; hand-draw hazards from imagery |
| Layers don't line up | Fix the coordinate system first; if stuck, drop the misaligned layer |
| Pi or display fails | Run the HUD on the laptop and present it as a simulated helmet view |
| Pi 5 power warnings on a 3A battery bank | Power from the wall for the demo; mention battery needs in the pitch |
| Gemma too slow or won't run on the HAT | Keyword voice commands only; mention the LLM as future work |
| Optics blurry | Show the HUD on a small screen next to the helmet, or use a phone with Cardboard-style lenses |
| Running out of time | At checkpoint 2, cut everything below must-have and move to video and submission |

---

## 8. Before submitting

- [ ] Project page lists every NASA dataset used, with links
- [ ] AI tool usage disclosed as the Space Apps rules require
- [ ] Demo video meets the length and format rules and is publicly viewable
- [ ] Repo link is public with a README covering setup, data pipeline and hardware list
- [ ] Team name decided and every member added to the team on the Space Apps site
- [ ] Submitted at least 1 hour early, with confirmation screenshot
