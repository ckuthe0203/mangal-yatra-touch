"""Helmet sensors and glove buttons. Falls back to mock values when hardware libraries are missing
(e.g. on your laptop), so the same code runs everywhere."""
import math
import random
import time

# GPIO pins (BCM numbering) for the glove-friendly buttons. Wire each button between the pin and GND.
BUTTON_PINS = {
    5: "next_waypoint",
    6: "zoom_in",
    13: "cycle_layer",
    19: "sos",
    26: "ptt",          # push-to-talk (held)
}


def _yaw_from_quat(i, j, k, real):
    # yaw (rotation about the vertical axis) in degrees, 0..360
    siny = 2 * (real * k + i * j)
    cosy = 1 - 2 * (j * j + k * k)
    return (math.degrees(math.atan2(siny, cosy)) + 360) % 360


class Sensors:
    def __init__(self):
        self.imu = None
        self.bme = None
        self.heading_offset = 0.0
        self.mock = True
        try:
            import board
            i2c = board.I2C()
            try:
                from adafruit_bno08x.i2c import BNO08X_I2C
                from adafruit_bno08x import BNO_REPORT_GAME_ROTATION_VECTOR
                self.imu = BNO08X_I2C(i2c)
                # Game rotation vector = gyro + accel only. Mars has no global magnetic field,
                # so we deliberately do NOT use the magnetometer.
                self.imu.enable_feature(BNO_REPORT_GAME_ROTATION_VECTOR)
            except Exception as e:
                print(f"[sensors] BNO085 not available: {e}")
            try:
                from adafruit_bme280 import basic as bme280
                self.bme = bme280.Adafruit_BME280_I2C(i2c)
            except Exception as e:
                print(f"[sensors] BME280 not available: {e}")
            self.mock = self.imu is None and self.bme is None
        except Exception as e:
            print(f"[sensors] No I2C bus ({e}); using mock sensors")
        self._t0 = time.time()

    def raw_heading(self):
        if self.imu is None:
            return None
        try:
            return _yaw_from_quat(*self.imu.game_quaternion)
        except Exception:
            return None

    def recenter(self, true_heading):
        """Align the IMU's relative yaw to a known heading (e.g. the route direction at start)."""
        raw = self.raw_heading()
        if raw is not None:
            self.heading_offset = (true_heading - raw) % 360

    def heading(self):
        raw = self.raw_heading()
        return None if raw is None else (raw + self.heading_offset) % 360

    def suit(self):
        if self.bme is not None:
            try:
                return {
                    "temp_c": round(self.bme.temperature, 1),
                    "pressure_kpa": round(self.bme.pressure / 10, 1),   # hPa -> kPa
                    "humidity_pct": round(self.bme.humidity, 0),
                    "source": "BME280",
                }
            except Exception:
                pass
        t = time.time() - self._t0
        return {
            "temp_c": round(21.5 + 0.6 * math.sin(t / 40) + random.uniform(-0.1, 0.1), 1),
            "pressure_kpa": round(29.6 + random.uniform(-0.05, 0.05), 1),  # ~4.3 psi suit pressure
            "humidity_pct": round(38 + 2 * math.sin(t / 60)),
            "source": "mock",
        }


def start_buttons(on_command):
    """Attach GPIO buttons. on_command(name, pressed: bool) is called from a background thread."""
    try:
        from gpiozero import Button
    except Exception:
        print("[sensors] gpiozero not available; use keyboard shortcuts in the HUD instead")
        return []
    buttons = []
    for pin, name in BUTTON_PINS.items():
        try:
            b = Button(pin, bounce_time=0.05)
            b.when_pressed = lambda n=name: on_command(n, True)
            b.when_released = lambda n=name: on_command(n, False)
            buttons.append(b)
        except Exception as e:
            print(f"[sensors] button on GPIO{pin} failed: {e}")
    return buttons
