"""Earth-Mars distance and radio delay for a given date.

Keplerian orbits with J2000 elements (Standish, JPL "Approximate Positions of the Planets"),
good to about 1% over 1800-2050: plenty for "your message takes 12 minutes to reach Earth".
"""
import math
from datetime import datetime, timezone

AU_KM = 149_597_870.7
C_KM_S = 299_792.458

# a [AU], e, i [deg], L [deg], long. perihelion [deg], long. ascending node [deg]; then rates per century
_ELEMENTS = {
    "earth": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
}


def _helio_xyz(planet, t_cent):
    (a, e, i, L, w, O), rates = _ELEMENTS[planet]
    a, e, i, L, w, O = (v + r * t_cent for v, r in zip((a, e, i, L, w, O), rates))
    M = math.radians((L - w + 180) % 360 - 180)
    E = M
    for _ in range(10):                                   # Kepler's equation
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    xp, yp = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    w_arg, O, i = math.radians(w - O), math.radians(O), math.radians(i)
    cw, sw, cO, sO, ci, si = math.cos(w_arg), math.sin(w_arg), math.cos(O), math.sin(O), math.cos(i), math.sin(i)
    return ((cw * cO - sw * sO * ci) * xp + (-sw * cO - cw * sO * ci) * yp,
            (cw * sO + sw * cO * ci) * xp + (-sw * sO + cw * cO * ci) * yp,
            (sw * si) * xp + (cw * si) * yp)


def earth_mars_distance_au(when=None):
    when = when or datetime.now(timezone.utc)
    jd = when.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545.0) / 36525
    e, m = _helio_xyz("earth", t), _helio_xyz("mars", t)
    return math.dist(e, m)


def light_delay_s(when=None):
    """One-way radio delay Earth <-> Mars in seconds."""
    return earth_mars_distance_au(when) * AU_KM / C_KM_S
