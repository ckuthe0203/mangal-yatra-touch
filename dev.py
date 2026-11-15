"""Dev runner: start the backend with live reload.

    python dev.py --time-scale 30 --port 8090      (same options as backend/server.py)

- Change anything in hud/            -> open browsers reload instantly (server keeps running).
- Change backend/*.py or data/ files -> the server restarts, then open browsers reload.
Ctrl+C stops everything.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WATCH = [(ROOT / "backend", "*.py"), (ROOT / "data", "*.json"), (ROOT / "data", "*.geojson")]


def snapshot():
    return {p: p.stat().st_mtime for folder, pattern in WATCH for p in folder.rglob(pattern)}


def start():
    cmd = [sys.executable, "-u", str(ROOT / "backend" / "server.py"), "--dev", *sys.argv[1:]]
    print(f"[dev] starting: {' '.join(cmd[1:])}", flush=True)
    return subprocess.Popen(cmd, cwd=ROOT)


def main():
    proc, before = start(), snapshot()
    try:
        while True:
            time.sleep(0.5)
            now = snapshot()
            if now != before:
                changed = sorted(str(p.relative_to(ROOT)) for p in now.keys() | before.keys() if now.get(p) != before.get(p))
                print(f"[dev] changed: {', '.join(changed)} -> restarting server", flush=True)
                before = now
                proc.terminate()
                proc.wait()
                proc = start()
            elif proc.poll() is not None:
                # Server crashed (e.g. a syntax error). Wait for the next save, then try again.
                print("[dev] server stopped; fix the error and save to restart", flush=True)
                while snapshot() == before:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
