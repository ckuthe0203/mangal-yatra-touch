"""Mission Control on Earth: Gemini turns the EVA log into a report and answers the team's questions.

Runs on the Earth side. The wrist unit on Mars never calls Gemini: it works offline, and the EVA log
reaches Earth over the (delayed) radio link. Gemini only sees the logged facts, so every number it
quotes comes from the habitat's records.

Settings (environment or backend/secrets.env):
    GEMINI_API_KEY   free key from https://aistudio.google.com  (never commit it)
    GEMINI_MODEL     default gemini-3.5-flash-lite
Without a key, a plain offline summary is produced instead, so the demo still works.
"""
import json
import os

import aiohttp

from earth_link import load_secrets

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

ROLE = ("You are the EVA science and safety officer at Mission Control on Earth for a crewed Mars surface "
        "mission. You receive the habitat's EVA log as JSON. Use ONLY facts and numbers present in the log; "
        "if something is not in the log, say it is not recorded. Never invent measurements. Times are mission "
        "minutes (t_min). Be concise and plain-spoken.")

REPORT_TASK = ("Write the post-EVA report in Markdown with these sections, at most 250 words in total:\n"
               "## Summary (2-3 sentences: where they went, distance, duration, outcome)\n"
               "## Science stops (each stop visited, with its task; note stops not reached)\n"
               "## Safety (alerts, SOS, closest calls; say 'none recorded' if none)\n"
               "## Consumables (oxygen and battery at start and end, and the margin left)\n"
               "## Recommendations for the next EVA (2-3 bullet points, grounded in the log)")


class MissionControl:
    def __init__(self):
        load_secrets()
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
        self.live = bool(self.key)
        print(f"[mission-control] Gemini {'ready: ' + self.model if self.live else 'not configured: offline summaries'}")

    async def _gemini(self, http, prompt, max_tokens=700):
        body = {"systemInstruction": {"parts": [{"text": ROLE}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}}
        async with http.post(API.format(model=self.model), json=body, headers={"x-goog-api-key": self.key},
                             timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.json(content_type=None)
            if r.status >= 300:
                msg = (data.get("error") or {}).get("message", str(data))[:200]
                raise RuntimeError(f"Gemini error {r.status}: {msg}")
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()

    async def report(self, http, log):
        if self.live:
            try:
                text = await self._gemini(http, f"{REPORT_TASK}\n\nEVA log:\n{json.dumps(log)}")
                return text, f"Gemini ({self.model})"
            except Exception as e:
                print(f"[mission-control] {e}; using offline summary")
        return offline_report(log), "offline summary (Gemini not configured)"

    async def ask(self, http, question, log):
        if not self.live:
            return "Gemini is not configured. Add GEMINI_API_KEY to backend/secrets.env to ask questions.", "offline"
        q = question.strip()[:500]
        text = await self._gemini(http, f"Question from the Mission Control team: {q}\n"
                                        f"Answer in at most 4 sentences, from this EVA log only:\n{json.dumps(log)}",
                                  max_tokens=300)
        return text, f"Gemini ({self.model})"


def offline_report(log):
    """Plain summary from the log, used when Gemini is unavailable."""
    ev, tr = log["events"], log["trend"]
    arrived = [e["stop"] for e in ev if e["kind"] == "arrival"]
    alerts = [e for e in ev if e["kind"] in ("alert", "sos")]
    first, last = (tr[0], tr[-1]) if tr else ({}, {})
    lines = [f"## Summary",
             f"{log['mission']} at {log['site']}. Walked {last.get('walked_m', 0)} m of the planned "
             f"{log['planned_route_m']} m in {last.get('t_min', 0)} min. {'EVA complete.' if log['complete'] else 'EVA in progress.'}",
             "## Science stops",
             *([f"- {s}" for s in arrived] or ["- none reached yet"]),
             "## Safety",
             *([f"- t+{e['t_min']} min: {e['text']}" for e in alerts] or ["- none recorded"]),
             "## Consumables",
             f"- Oxygen {first.get('o2_min', '?')} -> {last.get('o2_min', '?')} min; "
             f"battery {first.get('battery_pct', '?')} -> {last.get('battery_pct', '?')} %"]
    return "\n".join(lines)
