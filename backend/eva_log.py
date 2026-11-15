"""EVA log: the habitat's 'black box' for one Marswalk.

Records events (start, arrivals, alerts, SOS, messages) and a compact trend of suit and route data,
so Mission Control on Earth (and Gemini) can review the EVA from facts, not guesses.
Saved as JSON in logs/ after every event.
"""
import json
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
SAMPLE_EVERY_MIN = 5          # one trend sample per 5 mission minutes


class EvaLog:
    def __init__(self, mission_meta, waypoints, route_m):
        self.meta, self.waypoints, self.route_m = mission_meta, waypoints, route_m
        self.start()

    def start(self):
        self.started_wall = time.time()
        self.id = time.strftime("EVA-%Y%m%d-%H%M%S")
        self.events, self.samples = [], []
        self._last_sample_min = -SAMPLE_EVERY_MIN
        self.complete = False

    def event(self, t_min, kind, text, **data):
        self.events.append({"t_min": round(t_min, 1), "kind": kind, "text": text, **data})
        self.save()

    def sample(self, t_min, st):
        if t_min - self._last_sample_min < SAMPLE_EVERY_MIN:
            return
        self._last_sample_min = t_min
        s = st["suit"]
        self.samples.append({"t_min": round(t_min), "walked_m": st["walked_m"], "o2_min": s["o2_min"],
                             "battery_pct": s["battery_pct"], "suit_temp_c": s.get("temp_c"),
                             "lat": round(st["pos"][1], 5), "lon": round(st["pos"][0], 5),
                             "next_stop": (st["next_wp"] or {}).get("name")})

    def summary(self):
        """Everything Mission Control needs, compact enough to hand to Gemini."""
        return {
            "eva_id": self.id, "mission": self.meta.get("name"), "site": self.meta.get("site"),
            "goal": self.meta.get("science_goal"), "crew": self.meta.get("crew"),
            "planned_route_m": round(self.route_m), "eva_duration_budget_min": self.meta.get("eva_duration_min"),
            "o2_reserve_min": self.meta.get("o2_reserve_min"), "complete": self.complete,
            "planned_stops": [{"name": w["name"], "kind": w["kind"], "task": w.get("task", "")} for w in self.waypoints],
            "events": self.events, "trend": self.samples[-40:],
        }

    def save(self):
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / f"{self.id}.json").write_text(json.dumps(self.summary(), indent=1))
