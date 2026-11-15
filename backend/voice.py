"""Voice control: speech -> text -> command JSON -> spoken reply.

Pipeline:  push-to-talk -> Vosk (speech to text) -> keyword rules (instant)
           -> if no rule matched, the LLM (AI HAT+ 2 or Gemma on CPU) -> command JSON
Everything is optional: if a library is missing, the HUD's text box and keyboard still work.
"""
import asyncio
import json
import os
import queue
import re
import shutil
import subprocess
import threading

LAYERS = ["imagery", "slope", "hazards", "route", "science"]
ACTIONS = ["toggle_layer", "restart", "report", "earth_status", "next_waypoint", "zoom_in", "zoom_out", "status", "where_next", "where_am_i",
           "home", "turn_back", "danger", "mission", "conditions", "pause", "resume", "sos", "recenter", "mirror"]

# ---------- 1. Keyword rules (instant, always available) ----------
# Order matters: the first pattern that matches wins.
_RULES = [
    (r"\b(sos|emergency|mayday|help me)\b", {"action": "sos"}),
    (r"\b(restart|reset|start over|start again|from the (beginning|start))\b", {"action": "restart"}),
    (r"\b(mission|eva|walk) report\b|\bdebrief\b|\breport\b", {"action": "report"}),
    (r"\bturn (back|around)\b|\bhow long can (we|i)\b|\bstay out\b|\btime (left|remaining)\b|\bhow much time\b",
     {"action": "turn_back"}),
    (r"\b(base|home|habitat|hab|lander)\b", {"action": "home"}),
    (r"\bmission\b|\bwhy are we\b|\b(goal|purpose|objective)\b", {"action": "mission"}),
    (r"\b(where|how far|which way|what).*(next|going|waypoint)\b|\bnavigate\b", {"action": "where_next"}),
    (r"\bwhere (am i|are we|are you|is (my|our))\b|\b(location|position|coordinates)\b|\bhow far (have|did) (we|i)\b",
     {"action": "where_am_i"}),
    (r"\b(danger|dangerous|safe|safety|unsafe|risk|risky|threat|hazards?|obstacles?)\b", {"action": "danger"}),
    (r"\b(go to |skip to )?next (waypoint|stop|target)\b|\bskip\b", {"action": "next_waypoint"}),
    (r"\bzoom (in|closer)\b|\benhance\b", {"action": "zoom_in"}),
    (r"\bzoom out\b|\bwider\b", {"action": "zoom_out"}),
    (r"\bradiation\b", {"action": "conditions", "what": "radiation"}),
    (r"\btemperature outside\b|\b(how cold|air temp\w*|outside temp\w*)\b", {"action": "conditions", "what": "air"}),
    (r"\b(dust|weather|conditions)\b", {"action": "conditions"}),
    (r"\b(oxygen|o2)\b", {"action": "status", "what": "o2"}),
    (r"\bbattery\b", {"action": "status", "what": "battery"}),
    (r"\b(status|suit)\b", {"action": "status"}),
    (r"\b(pause|stop|hold|wait)\b", {"action": "pause"}),
    (r"\b(resume|continue|go|start)\b", {"action": "resume"}),
    (r"\b(recenter|re-center|reset heading|calibrate)\b", {"action": "recenter"}),
    (r"\bmirror|flip\b", {"action": "mirror"}),
]
_LAYER_WORDS = {
    "imagery": ["imagery", "image", "photo", "satellite", "basemap"],
    "slope": ["slope", "steep", "terrain", "elevation"],
    "hazards": ["hazard", "danger", "rocks", "obstacle"],
    "route": ["route", "path", "trail"],
    "science": ["science", "target", "minerals", "samples"],
}


_EARTH_MSG = re.compile(r"^(?:please\s+)?(?:tell|message|text|radio|send(?:\s+a\s+message)?\s+to)\s+"
                        r"(?:mission control|earth|houston|ground control)[,:]?\s*(?:that\s+)?(.*)$", re.I)
_EARTH_STATUS = re.compile(r"\b(any )?messages?( from earth)?\b|\b(earth|signal|radio) delay\b|\bdelay to earth\b", re.I)


def parse_rules(text):
    t = text.lower().strip()
    if not t:
        return None
    m = _EARTH_MSG.match(text.strip())            # keep the original wording of the message itself
    if m:
        return {"action": "earth_msg", "text": m.group(1).strip().rstrip(".") + ("." if m.group(1).strip() else "")}
    if _EARTH_STATUS.search(t):
        return {"action": "earth_status"}
    if re.search(r"\b(show|hide|toggle|turn on|turn off|display)\b", t):
        for layer, words in _LAYER_WORDS.items():
            if any(w in t for w in words):
                return {"action": "toggle_layer", "layer": layer}
    for pattern, cmd in _RULES:
        if re.search(pattern, t):
            return dict(cmd)
    return None


# ---------- 2. LLM fallback (AI HAT+ 2 via an Ollama-compatible server, or Ollama on the CPU) ----------
LLM_URL = os.environ.get("LLM_URL", "http://localhost:11434/api/chat")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")   # e.g. "gemma4:e2b" for Gemma on the CPU
_SYSTEM = (
    "You convert an astronaut's spoken request into ONE JSON command for a Mars helmet HUD. "
    f"Valid actions: {ACTIONS}. For toggle_layer also give \"layer\" from {LAYERS}. "
    'Reply with JSON only, e.g. {"action":"toggle_layer","layer":"hazards"}. '
    'If nothing fits, reply {"action":"none"}.'
)


async def parse_llm(text, session, timeout=8):
    payload = {
        "model": LLM_MODEL, "stream": False, "format": "json",
        "options": {"num_predict": 40, "num_ctx": 1024},
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text}],
    }
    try:
        async with session.post(LLM_URL, json=payload, timeout=timeout) as r:
            data = await r.json()
        content = data.get("message", {}).get("content") or data.get("response", "")
        cmd = json.loads(re.search(r"\{.*\}", content, re.S).group(0))
        if cmd.get("action") in ACTIONS:
            if cmd["action"] == "toggle_layer" and cmd.get("layer") not in LAYERS:
                return None
            return cmd
    except Exception as e:
        print(f"[voice] LLM unavailable or bad reply ({e.__class__.__name__})")
    return None


async def understand(text, session):
    """Rules first (instant, reliable for the demo), LLM only for free-form requests."""
    cmd = parse_rules(text)
    if cmd:
        return cmd, "rules"
    cmd = await parse_llm(text, session)
    if cmd and cmd["action"] != "none":
        return cmd, "llm"
    return None, None


# ---------- 3. Speech to text with Vosk (on the Pi; optional) ----------
class PushToTalk:
    """Records while the PTT button is held, then returns the transcript."""

    def __init__(self, model_path=os.environ.get("VOSK_MODEL", "models/vosk-model-small-en-us-0.15")):
        self.ok = False
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer
            self.sd, self.KaldiRecognizer = sd, KaldiRecognizer
            self.model = Model(model_path)
            self.rate = 16000
            self.ok = True
        except Exception as e:
            print(f"[voice] Vosk speech-to-text disabled ({e}); type commands in the HUD instead")
        self._q = queue.Queue()
        self._stream = None

    def start(self):
        if not self.ok or self._stream:
            return
        self._q = queue.Queue()
        self._stream = self.sd.RawInputStream(samplerate=self.rate, blocksize=4000, dtype="int16",
                                              channels=1, callback=lambda d, f, t, s: self._q.put(bytes(d)))
        self._stream.start()

    def stop_and_transcribe(self):
        if not self._stream:
            return ""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        rec = self.KaldiRecognizer(self.model, self.rate)
        while not self._q.empty():
            rec.AcceptWaveform(self._q.get())
        return json.loads(rec.FinalResult()).get("text", "")


# ---------- 4. Text to speech with Piper (optional; otherwise the HUD speaks in the browser) ----------
PIPER_MODEL = os.environ.get("PIPER_MODEL")  # e.g. models/en_US-lessac-medium.onnx


def piper_available():
    return bool(PIPER_MODEL) and shutil.which("piper") and shutil.which("aplay")


def speak_piper(text):
    def run():
        try:
            p1 = subprocess.Popen(["piper", "--model", PIPER_MODEL, "--output_raw"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p2 = subprocess.Popen(["aplay", "-q", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"],
                                  stdin=p1.stdout, stderr=subprocess.DEVNULL)
            p1.stdin.write(text.encode())
            p1.stdin.close()
            p2.wait()
        except Exception as e:
            print(f"[voice] piper failed: {e}")
    threading.Thread(target=run, daemon=True).start()
