"""Talks to the Arduino helmet hub over USB serial (see arduino/helmet_hub/helmet_hub.ino).

Drop-in replacement for sensors.Sensors: same heading(), suit() and recenter() methods,
plus buzz() for alerts and send_cpu_temp() for automatic fan control.
"""
import json
import threading
import time


def read_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) // 1000
    except Exception:
        return None


class ArduinoLink:
    def __init__(self, port, on_button=None, baud=115200):
        import serial  # pip install pyserial
        self.port = port
        self.on_button = on_button
        self.ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)                       # the Arduino resets when the port opens
        self.latest = {}
        self.last_rx = 0.0
        self.heading_offset = 0.0
        self.hello = None
        self._lock = threading.Lock()
        self._stop = False
        threading.Thread(target=self._reader, daemon=True).start()
        print(f"[arduino] listening on {port}")

    # ---------- receive ----------
    def _reader(self):
        while not self._stop:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
            except Exception as e:
                print(f"[arduino] connection lost ({e.__class__.__name__}); reconnecting...")
                self._reconnect()
                continue
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.last_rx = time.time()
            if "hello" in msg:
                self.hello = msg
                print(f"[arduino] hub online: imu={msg.get('imu')} bme={msg.get('bme')}")
            elif "btn" in msg:
                if self.on_button:
                    self.on_button(msg["btn"], bool(msg.get("down")))
            else:
                with self._lock:
                    self.latest = msg

    def _reconnect(self):
        """Keep retrying every 2 s (cable unplugged / Arduino reset). The HUD keeps running meanwhile."""
        import serial
        try:
            self.ser.close()
        except Exception:
            pass
        while not self._stop:
            time.sleep(2)
            try:
                self.ser = serial.Serial(self.port, self.ser.baudrate, timeout=1)
                print(f"[arduino] reconnected on {self.port}")
                return
            except Exception:
                pass

    def connected(self):
        return time.time() - self.last_rx < 2

    # ---------- send ----------
    def send(self, obj):
        try:
            self.ser.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())
        except Exception as e:
            print(f"[arduino] write failed: {e}")

    def buzz(self, times=3):
        self.send({"buzz": times})

    def send_cpu_temp(self):
        t = read_cpu_temp()
        if t is not None:
            self.send({"cpu": t})

    def set_fan(self, pwm):
        self.send({"fan": pwm})             # -1 = automatic

    # ---------- same interface as sensors.Sensors ----------
    def heading(self):
        with self._lock:
            yaw = self.latest.get("yaw")
        if yaw is None or not self.connected():
            return None                     # backend falls back to route direction / arrow keys
        return (yaw + self.heading_offset) % 360

    def recenter(self, true_heading):
        with self._lock:
            yaw = self.latest.get("yaw")
        if yaw is not None:
            self.heading_offset = (true_heading - yaw) % 360

    def suit(self):
        with self._lock:
            d = dict(self.latest)
        if "temp" in d and self.connected():
            return {"temp_c": d["temp"], "pressure_kpa": round(d["pres"] / 10, 1),
                    "humidity_pct": d.get("hum"), "fan_pwm": d.get("fan"), "source": "arduino"}
        return {"temp_c": None, "pressure_kpa": None, "humidity_pct": None,
                "fan_pwm": d.get("fan"), "source": "arduino (no BME280 data)"}
