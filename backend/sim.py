"""Simulated astronaut position walking the planned route (there is no GPS on Mars)."""
from geo import distance_m, bearing_deg, interpolate


class RouteSimulator:
    def __init__(self, route_coords, waypoints, speed_mps=1.0, time_scale=10.0, dwell_s=4.0):
        self.route = route_coords
        self.speed = speed_mps          # real walking speed in a suit, ~1 m/s
        self.time_scale = time_scale    # demo speed-up
        self.dwell_s = dwell_s          # pause at each waypoint (sim seconds / time_scale)
        self.cum = [0.0]
        for a, b in zip(route_coords, route_coords[1:]):
            self.cum.append(self.cum[-1] + distance_m(a, b))
        self.total = self.cum[-1]
        self.waypoints = []
        for wp in waypoints:
            self.waypoints.append({**wp, "along": self._along_of(wp["coord"])})
        self.waypoints.sort(key=lambda w: w["along"])
        self.s = 0.0
        self.paused = False
        self._dwell_left = 0.0
        self._reached = set()

    def _along_of(self, coord):
        best_i = min(range(len(self.route)), key=lambda i: distance_m(self.route[i], coord))
        return self.cum[best_i]

    def position(self):
        return self.point_at(self.s)

    def point_at(self, s):
        """Point and bearing at distance s (m) along the route."""
        s = max(0.0, min(s, self.total))
        for i in range(len(self.cum) - 1):
            if self.cum[i] <= s <= self.cum[i + 1]:
                seg = self.cum[i + 1] - self.cum[i]
                t = 0 if seg == 0 else (s - self.cum[i]) / seg
                return interpolate(self.route[i], self.route[i + 1], t), bearing_deg(self.route[i], self.route[i + 1])
        return self.route[-1], bearing_deg(self.route[-2], self.route[-1])

    def next_waypoint(self):
        for wp in self.waypoints:
            if wp["along"] > self.s + 0.5:
                return wp
        return None

    def reset(self):
        """Back to the start of the route (the habitat)."""
        self.s = 0.0
        self.paused = False
        self._dwell_left = 0.0
        self._reached = set()

    def skip_to_next(self):
        wp = self.next_waypoint()
        if wp:
            self.s = wp["along"]
            self._reached.add(wp["id"])
            self._dwell_left = 0
        return wp

    def step(self, dt):
        """Advance by dt real seconds. Returns a waypoint dict if one was just reached."""
        if self.paused or self.s >= self.total:
            return None
        if self._dwell_left > 0:
            self._dwell_left -= dt
            return None
        target = self.next_waypoint()
        self.s = min(self.total, self.s + self.speed * self.time_scale * dt)
        if target and self.s >= target["along"] and target["id"] not in self._reached:
            self.s = target["along"]
            self._reached.add(target["id"])
            self._dwell_left = self.dwell_s
            return target
        return None

    def remaining_m(self):
        return max(0.0, self.total - self.s)
