"""Mars geometry helpers. Coordinates are [lon, lat] in degrees (planetocentric, east-positive)."""
import math

MARS_RADIUS_M = 3_389_500.0


def distance_m(a, b):
    """Great-circle distance in metres between two [lon, lat] points on Mars."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * MARS_RADIUS_M * math.asin(math.sqrt(h))


def bearing_deg(a, b):
    """Initial bearing from a to b, degrees clockwise from north."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def interpolate(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def to_local_m(origin, p):
    """Project p to metres east/north of origin (fine for a few km)."""
    k = math.pi / 180 * MARS_RADIUS_M
    return ((p[0] - origin[0]) * k * math.cos(math.radians(origin[1])), (p[1] - origin[1]) * k)


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _point_in_ring(p, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def distance_to_polygon_m(point, polygon_coords):
    """Distance in metres from point to a GeoJSON Polygon (0 if inside)."""
    outer = [to_local_m(point, c) for c in polygon_coords[0]]
    if _point_in_ring((0, 0), outer):
        return 0.0
    return min(_seg_dist((0, 0), outer[i], outer[i + 1]) for i in range(len(outer) - 1))


def compass_label(deg):
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return names[int((deg + 22.5) // 45) % 8]
