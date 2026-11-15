"""EVA telemetry in TigerData (TimescaleDB on Tiger Cloud), on the Earth side.

The habitat on Mars records a reading every couple of seconds and holds it until it has crossed the
Earth-Mars radio delay ("store and forward", like real missions). Then it is written in batches into a
TigerData hypertable. Mission Control reads it back with time_bucket() for live charts and EVA history.

If the database is unreachable (or not configured) nothing is lost: readings stay in the buffer
(up to MAX_BUFFER) and upload when the link comes back.

Settings (environment or backend/secrets.env, never committed):
    TIGER_DATABASE_URL   postgres://tsdbadmin:...@....tsdb.cloud.timescale.com:3xxxx/tsdb?sslmode=require
"""
import asyncio
import os
import time
from datetime import datetime, timezone

from earth_link import load_secrets

RECORD_EVERY_S = 2.0          # habitat sampling period (real seconds)
FLUSH_EVERY_S = 3.0
MAX_BUFFER = 20000            # ~11 h of readings at 2 s

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS eva_telemetry (
         time        TIMESTAMPTZ NOT NULL,
         eva_id      TEXT        NOT NULL,
         t_min       REAL,                 -- mission minutes since EVA start
         walked_m    REAL,
         o2_min      REAL,
         battery_pct REAL,
         suit_temp_c REAL,
         heading     REAL,
         lat         DOUBLE PRECISION,
         lon         DOUBLE PRECISION,
         next_stop   TEXT,
         alerts      TEXT)""",
    """CREATE TABLE IF NOT EXISTS eva_events (
         time   TIMESTAMPTZ NOT NULL,
         eva_id TEXT        NOT NULL,
         t_min  REAL,
         kind   TEXT,
         text   TEXT)""",
]
HYPERTABLES = ["eva_telemetry", "eva_events"]


class TelemetryStore:
    def __init__(self, delay_s):
        load_secrets()
        self.url = (os.environ.get("TIGER_DATABASE_URL") or os.environ.get("TIMESCALE_SERVICE_URL") or "").strip()
        self.delay_s = delay_s                 # callable: current Mars->Earth delay in seconds
        self.enabled = bool(self.url)
        self.conn = None
        self.status = "not configured" if not self.enabled else "connecting"
        self.rows, self.events = [], []        # waiting on Mars / in transit
        self.uploaded = 0
        self._last_record = 0.0
        print(f"[tigerdata] {'configured' if self.enabled else 'not configured (TIGER_DATABASE_URL missing): readings are not stored'}")

    # ---------- recording on Mars ----------
    def record(self, eva_id, t_min, st):
        now = time.time()
        if not self.enabled or now - self._last_record < RECORD_EVERY_S:
            return
        self._last_record = now
        s, n = st["suit"], st.get("next_wp") or {}
        self.rows.append((now, (datetime.fromtimestamp(now, timezone.utc), eva_id, round(t_min, 2), st["walked_m"],
                                s["o2_min"], s["battery_pct"], s.get("temp_c"), st["heading"], st["pos"][1], st["pos"][0],
                                n.get("name"), "; ".join(a["msg"] for a in st["alerts"])[:500] or None)))
        del self.rows[:-MAX_BUFFER]

    def event(self, eva_id, e):
        if self.enabled:
            now = time.time()
            self.events.append((now, (datetime.fromtimestamp(now, timezone.utc), eva_id, e["t_min"], e["kind"], e["text"])))
            del self.events[:-MAX_BUFFER]

    # ---------- uplink to Earth ----------
    async def run(self):
        if not self.enabled:
            return
        import psycopg
        while True:
            try:
                if self.conn is None or self.conn.closed:
                    self.conn = await psycopg.AsyncConnection.connect(self.url, autocommit=True, connect_timeout=15)
                    await self._ensure_schema()
                    self.status = "connected"
                    print("[tigerdata] connected, hypertables ready")
                await self._flush()
            except Exception as e:
                self.status = f"offline: {e.__class__.__name__}"
                print(f"[tigerdata] {self.status} ({str(e)[:120]}); will retry, {len(self.rows)} readings buffered")
                try:
                    if self.conn:
                        await self.conn.close()
                except Exception:
                    pass
                self.conn = None
                await asyncio.sleep(10)
            await asyncio.sleep(FLUSH_EVERY_S)

    async def _ensure_schema(self):
        async with self.conn.cursor() as cur:
            for sql in SCHEMA:
                await cur.execute(sql)
            for table in HYPERTABLES:
                try:      # TimescaleDB 2.13+ syntax
                    await cur.execute(f"SELECT create_hypertable('{table}', by_range('time'), if_not_exists => TRUE)")
                except Exception:
                    await cur.execute(f"SELECT create_hypertable('{table}', 'time', if_not_exists => TRUE)")
            await cur.execute("CREATE INDEX IF NOT EXISTS eva_telemetry_eva_time ON eva_telemetry (eva_id, time DESC)")

    async def _flush(self):
        """Upload whatever has finished its trip across the Mars-Earth gap."""
        arrived_before = time.time() - self.delay_s()
        rows = [r for t, r in self.rows if t <= arrived_before]
        events = [r for t, r in self.events if t <= arrived_before]
        if not rows and not events:
            return
        async with self.conn.cursor() as cur:
            if rows:
                await cur.executemany(
                    "INSERT INTO eva_telemetry (time, eva_id, t_min, walked_m, o2_min, battery_pct, suit_temp_c, "
                    "heading, lat, lon, next_stop, alerts) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
            if events:
                await cur.executemany("INSERT INTO eva_events (time, eva_id, t_min, kind, text) VALUES (%s,%s,%s,%s,%s)",
                                      events)
        self.rows = [(t, r) for t, r in self.rows if t > arrived_before]
        self.events = [(t, r) for t, r in self.events if t > arrived_before]
        self.uploaded += len(rows)

    # ---------- queries for Mission Control ----------
    async def series(self, eva_id, bucket_s=60):
        """Telemetry bucketed with time_bucket() for the charts."""
        async with self.conn.cursor() as cur:
            await cur.execute(
                """SELECT time_bucket(make_interval(secs => %s), time) AS bucket,
                          max(t_min), max(walked_m), min(o2_min), min(battery_pct), avg(suit_temp_c)
                   FROM eva_telemetry WHERE eva_id = %s
                   GROUP BY bucket ORDER BY bucket""", (bucket_s, eva_id))
            return [{"time": b.isoformat(), "t_min": t, "walked_m": w, "o2_min": o, "battery_pct": bt,
                     "suit_temp_c": round(tc, 1) if tc is not None else None} for b, t, w, o, bt, tc in await cur.fetchall()]

    async def evas(self, limit=10):
        """Recent EVAs stored in TigerData, newest first."""
        async with self.conn.cursor() as cur:
            await cur.execute(
                """SELECT eva_id, min(time), max(time), max(walked_m), min(o2_min), count(*)
                   FROM eva_telemetry GROUP BY eva_id ORDER BY max(time) DESC LIMIT %s""", (limit,))
            return [{"eva_id": e, "start": a.isoformat(), "end": b.isoformat(), "walked_m": w, "min_o2_min": o, "readings": n}
                    for e, a, b, w, o, n in await cur.fetchall()]

    def info(self):
        return {"enabled": self.enabled, "status": self.status, "uploaded": self.uploaded,
                "in_transit": len(self.rows), "connected": self.conn is not None and not self.conn.closed}
