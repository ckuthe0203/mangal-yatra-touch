"""Download real MRO CTX imagery for a mission area and save it as offline map tiles.

    python pipeline/fetch_ctx_tiles.py data/jezero            (laptop, needs internet + Pillow)

Source: Esri "OnMars" CTX global mosaic (NASA/JPL/MSSS, Caltech Murray Lab, about 5 m/px).
That service tiles Mars in plain lat/lon, but MapLibre needs Web Mercator tiles, so this
script fetches the lat/lon tiles covering the mission and re-cuts them into
<mission>/tiles/imagery/{z}/{x}/{y}.png. The HUD picks them up automatically, and once
they are on disk the Pi needs no internet. A quick stand-in until build_site.py has been
run with the HiRISE orthomosaic.
"""
import argparse
import io
import json
import math
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# CTX is greyscale. These map dark -> mid -> bright greys onto Mars-like colours.
PALETTES = {
    "mars": ((38, 18, 10), (176, 92, 52), (242, 196, 150)),     # rust brown -> red-orange -> butterscotch
    "dusty": ((52, 34, 24), (160, 112, 78), (226, 196, 164)),   # softer, more muted
    "gray": None,                                               # original greyscale
}

SERVICE = "https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX/MapServer"
# Level 12 is ~5 m/px = native CTX. Deeper levels don't exist and some coarser ones are
# corrupt on the server, so every zoom is built from level 12 (a mission area needs only a few).
SRC_LEVEL = 12
OUT_TILE = 256
CREDIT = "MRO CTX mosaic: NASA/JPL/MSSS/Caltech Murray Lab, via Esri OnMars"
M_PER_DEG = 2 * math.pi * 3396190 / 360   # Mars


def mission_bbox(folder: Path, pad_m: float):
    pts = []
    for name in ("route.geojson", "waypoints.geojson", "hazards.geojson"):
        p = folder / name
        if not p.exists():
            continue
        for f in json.loads(p.read_text())["features"]:
            def walk(c):
                if isinstance(c[0], (int, float)):
                    pts.append(c[:2])
                else:
                    for cc in c:
                        walk(cc)
            walk(f["geometry"]["coordinates"])
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    dlat = pad_m / M_PER_DEG
    dlon = dlat / math.cos(math.radians(sum(lats) / len(lats)))
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def lon2x(lon, z): return (lon + 180) / 360 * 2 ** z
def lat2y(lat, z): return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z
def y2lat(y, z): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


class Source:
    """Fetches and caches Esri lat/lon tiles; samples them at arbitrary lon/lat grids."""

    def __init__(self):
        self.cache = {}
        with urllib.request.urlopen(f"{SERVICE}?f=json", timeout=30) as r:
            info = json.load(r)["tileInfo"]
        self.size = info["cols"]
        self.origin = info["origin"]["x"], info["origin"]["y"]
        self.res = {l["level"]: l["resolution"] for l in info["lods"]}   # degrees per pixel

    def tile(self, level, row, col):
        key = (level, row, col)
        if key not in self.cache:
            url = f"{SERVICE}/tile/{level}/{row}/{col}"
            req = urllib.request.Request(url, headers={"User-Agent": "mangal-yatra-tiles"})
            arr = None
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        arr = np.asarray(Image.open(io.BytesIO(r.read())).convert("L"))
                    break
                except Exception as e:
                    print(f"    retry {attempt + 1} for tile {level}/{row}/{col}: {e}")
                    time.sleep(1 + attempt)
            if arr is None:
                print(f"    giving up on {level}/{row}/{col}; leaving it black")
                arr = np.zeros((self.size, self.size), dtype=np.uint8)
            self.cache[key] = arr
        return self.cache[key]

    def sample(self, level, lons, lats):
        res, size = self.res[level], self.size
        px = (lons - self.origin[0]) / res          # global pixel column
        py = (self.origin[1] - lats) / res          # global pixel row
        out = np.zeros(lons.shape, dtype=np.uint8)
        cols, rows = (px // size).astype(int), (py // size).astype(int)
        for row in np.unique(rows):
            for col in np.unique(cols):
                m = (rows == row) & (cols == col)
                if not m.any():
                    continue
                t = self.tile(level, int(row), int(col))
                out[m] = t[(py[m] % size).astype(int), (px[m] % size).astype(int)]
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mission", help="mission folder, e.g. data/jezero")
    ap.add_argument("--min-zoom", type=int, default=12)
    ap.add_argument("--max-zoom", type=int, default=17)
    ap.add_argument("--pad-m", type=float, default=800, help="margin around the route and hazards")
    ap.add_argument("--color", choices=PALETTES, default="mars", help="colour the greyscale CTX imagery")
    args = ap.parse_args()
    palette = PALETTES[args.color]

    stretch = None     # (low, high) grey levels for the whole area, so tiles match each other

    def colorize(gray):
        if palette is None:
            return Image.fromarray(gray)
        lo, hi = stretch
        g = np.clip((gray.astype(np.float32) - lo) * 255 / max(1, hi - lo), 0, 255).astype(np.uint8)
        black, mid, white = palette
        return ImageOps.colorize(Image.fromarray(g), black=black, white=white, mid=mid)

    folder = Path(args.mission)
    west, south, east, north = mission_bbox(folder, args.pad_m)
    print(f"area: lon {west:.4f}..{east:.4f}, lat {south:.4f}..{north:.4f}")
    src, out_root, n = Source(), folder / "tiles" / "imagery", 0
    # Sample the whole area once to pick a contrast stretch shared by every tile.
    lons, lats = np.meshgrid(np.linspace(west, east, 400), np.linspace(south, north, 400))
    lo, hi = np.percentile(src.sample(SRC_LEVEL, lons, lats), [1, 99])
    stretch = (float(lo), float(hi))
    print(f"contrast stretch: grey {lo:.0f}..{hi:.0f}, colour: {args.color}")

    for z in range(args.min_zoom, args.max_zoom + 1):
        level = SRC_LEVEL
        x0, x1 = int(lon2x(west, z)), int(lon2x(east, z))
        y0, y1 = int(lat2y(north, z)), int(lat2y(south, z))
        for x in range(x0, x1 + 1):
            lons_1d = 360 * (x + (np.arange(OUT_TILE) + 0.5) / OUT_TILE) / 2 ** z - 180
            for y in range(y0, y1 + 1):
                lats_1d = np.array([y2lat(y + (j + 0.5) / OUT_TILE, z) for j in range(OUT_TILE)])
                lons, lats = np.meshgrid(lons_1d, lats_1d)
                img = src.sample(level, lons, lats)
                path = out_root / str(z) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                colorize(img).save(path, optimize=True)
                n += 1
        print(f"  zoom {z}: {(x1 - x0 + 1) * (y1 - y0 + 1)} tiles (source level {level})")

    (out_root / "SOURCE.txt").write_text(CREDIT + "\n")
    meta_path = folder / "mission.json"
    meta = json.loads(meta_path.read_text())
    meta["tile_maxzoom"] = args.max_zoom      # the HUD over-zooms past this instead of showing black
    meta["imagery_credit"] = CREDIT
    meta_path.write_text(json.dumps(meta, indent=1) + "\n")
    print(f"wrote {n} tiles to {out_root} ({len(src.cache)} source tiles downloaded)")


if __name__ == "__main__":
    main()
