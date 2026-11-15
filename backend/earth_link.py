"""Earth link: the habitat relays messages between the astronaut and Mission Control via Twilio.

Mars -> Earth: SOS (SMS + optional phone call), critical alerts, arrivals, dictated messages.
Earth -> Mars: SMS replies to the Twilio number are picked up by polling (no public webhook needed)
               and shown on the HUD after the radio delay.

Every message is held back by the Earth-Mars light delay: the real one (5-22 min), or a short
demo delay for filming (EARTH_DELAY_S=20). Without Twilio credentials the link runs in
"simulated" mode: messages are logged and shown on the HUD, nothing is sent.

Credentials come from environment variables or backend/secrets.env (never commit that file):
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   from the Twilio console
    TWILIO_FROM                             your Twilio number, e.g. +15551234567
    MISSION_CONTROL_PHONE                   the phone that plays Mission Control (verified in Twilio on a trial)
    MISSION_CONTROL_CALL=1                  also phone Mission Control on SOS (optional)
    EARTH_DELAY_S=20                        demo delay in seconds; leave unset for the real light delay
"""
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import aiohttp

from mars_time import light_delay_s

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/{what}.json"
MAX_SMS_PER_RUN = 25          # trial credit guard: never send more than this per server run
POLL_S = 10


def load_secrets(path=Path(__file__).with_name("secrets.env")):
    """KEY=value lines into os.environ (existing environment variables win)."""
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class EarthLink:
    def __init__(self, on_delivered, on_status=None):
        load_secrets()
        self.sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_ = os.environ.get("TWILIO_FROM", "")
        self.mc = os.environ.get("MISSION_CONTROL_PHONE", "")
        self.call_on_sos = os.environ.get("MISSION_CONTROL_CALL", "") == "1"
        demo = os.environ.get("EARTH_DELAY_S")
        self.demo_delay = float(demo) if demo else None
        self.live = all((self.sid, self.token, self.from_, self.mc))
        self.on_delivered = on_delivered        # async fn(text, sent_at, delay_s): Earth message reaches the HUD
        self.on_status = on_status              # async fn(dict): outbox/inbox changes, for the HUD
        self.http = None
        self.sent = 0
        self.outbox = []                        # [{"text", "arrives"}] messages still travelling to Earth
        self.inbox = []                         # [{"text", "arrives", "sent_at"}] messages travelling to Mars
        self.seen = set()
        self.started = datetime.now(timezone.utc)
        print(f"[earth] Twilio {'LIVE: SMS to ' + self._mask(self.mc) if self.live else 'not configured: simulated mode'}"
              f", delay {'demo ' + str(self.demo_delay) + ' s' if self.demo_delay is not None else 'real light delay'}")

    @staticmethod
    def _mask(num):
        return num[:3] + "..." + num[-2:] if len(num) > 6 else "***"

    def delay_s(self):
        return self.demo_delay if self.demo_delay is not None else light_delay_s()

    def status(self):
        now = time.time()
        return {"live": self.live, "delay_s": round(self.delay_s()), "real_delay_s": round(light_delay_s()),
                "outbox": [{"text": m["text"], "eta_s": max(0, round(m["arrives"] - now))} for m in self.outbox],
                "inbox_eta_s": [max(0, round(m["arrives"] - now)) for m in self.inbox]}

    # ---------- Mars -> Earth ----------
    async def send(self, text, call=False):
        """Queue a message; it 'arrives' at Earth (the SMS is sent) after the radio delay."""
        msg = {"text": text, "arrives": time.time() + self.delay_s(), "call": call}
        self.outbox.append(msg)
        print(f"[earth] -> queued for Earth in {round(self.delay_s())} s: {text}")
        await self._status()

    async def _deliver_to_earth(self, msg):
        if not self.live:
            print(f"[earth] (simulated) SMS to Mission Control: {msg['text']}")
            return
        if self.sent >= MAX_SMS_PER_RUN:
            print("[earth] SMS limit for this run reached; not sent")
            return
        auth = aiohttp.BasicAuth(self.sid, self.token)
        try:
            async with self.http.post(API.format(sid=self.sid, what="Messages"), auth=auth,
                                      data={"From": self.from_, "To": self.mc, "Body": msg["text"][:1500]}) as r:
                ok = r.status < 300
                print(f"[earth] SMS {'sent' if ok else 'FAILED ' + str(r.status) + ' ' + (await r.text())[:200]}")
            self.sent += 1
            if msg.get("call"):
                twiml = f'<Response><Say voice="alice">{escape(msg["text"])}</Say><Pause length="1"/>' \
                        f'<Say voice="alice">{escape(msg["text"])}</Say></Response>'
                async with self.http.post(API.format(sid=self.sid, what="Calls"), auth=auth,
                                          data={"From": self.from_, "To": self.mc, "Twiml": twiml}) as r:
                    print(f"[earth] call {'placed' if r.status < 300 else 'FAILED ' + str(r.status)}")
        except Exception as e:
            print(f"[earth] Twilio error: {e.__class__.__name__}: {e}")

    # ---------- Earth -> Mars ----------
    async def _poll_inbound(self):
        """New SMS from Mission Control to our Twilio number since the server started."""
        if not self.live:
            return
        params = {"To": self.from_, "From": self.mc, "PageSize": "20",
                  "DateSent>": self.started.strftime("%Y-%m-%d")}
        try:
            async with self.http.get(API.format(sid=self.sid, what="Messages"), params=params,
                                     auth=aiohttp.BasicAuth(self.sid, self.token)) as r:
                if r.status >= 300:
                    print(f"[earth] inbound poll failed {r.status}")
                    return
                data = await r.json()
        except Exception as e:
            print(f"[earth] inbound poll error: {e.__class__.__name__}")
            return
        for m in reversed(data.get("messages", [])):
            if m["sid"] in self.seen or not m["direction"].startswith("inbound"):
                continue
            self.seen.add(m["sid"])
            sent_at = datetime.strptime(m["date_created"], "%a, %d %b %Y %H:%M:%S %z")
            if sent_at < self.started:
                continue                                      # older than this run
            await self.receive(m["body"], sent_at.timestamp())

    async def receive(self, text, sent_at=None):
        """A message from Earth starts its trip to Mars (also used to simulate one without Twilio)."""
        sent_at = sent_at or time.time()
        self.inbox.append({"text": text, "sent_at": sent_at, "arrives": sent_at + self.delay_s()})
        print(f"[earth] <- message from Earth, arrives in {round(self.inbox[-1]['arrives'] - time.time())} s: {text}")
        await self._status()

    # ---------- loop ----------
    async def run(self, http):
        self.http = http
        last_poll = 0.0                   # (messages older than this run are skipped in _poll_inbound)
        while True:
            await asyncio.sleep(1)
            now = time.time()
            for msg in [m for m in self.outbox if m["arrives"] <= now]:
                self.outbox.remove(msg)
                await self._deliver_to_earth(msg)
                await self._status()
            for msg in [m for m in self.inbox if m["arrives"] <= now]:
                self.inbox.remove(msg)
                await self.on_delivered(msg["text"], msg["sent_at"], now - msg["sent_at"])
                await self._status()
            if now - last_poll > POLL_S:
                last_poll = now
                await self._poll_inbound()

    async def _status(self):
        if self.on_status:
            await self.on_status(self.status())
