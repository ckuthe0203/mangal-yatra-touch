"""Build a Mangal Yatra mission package from NASA rasters (run on the laptop, not the Pi).

    python pipeline/build_site.py pipeline/site_jezero.json

Inputs (set in the site JSON): an orbital image (HiRISE/CTX GeoTIFF), a terrain model (HiRISE DTM or MOLA),
and optionally a thermal-inertia map (THEMIS). Outputs into data/<site>/:
    tiles/imagery/{z}/{x}/{y}.png   basemap tiles
    tiles/slope/{z}/{x}/{y}.png     slope colour tiles (yellow >15 deg, red >25 deg)
    hazards.geojson                 steep ground + soft ground (+ any hand-traced hazards)
    route.geojson, waypoints.geojson  slope-aware route through your waypoints
    mission.json, conditions.json

Requires GDAL with Python bindings (conda install -c conda-forge gdal) and numpy.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

from planner import cost_grid, plan_through

gdal.UseExceptions()
MARS_R = 3396190.0                                   # IAU Mars 2000 sphere used by most PDS products
MARS_LL = f"+proj=longlat +R={MARS_R} +no_defs"      # Mars lon/lat (planetocentric, east-positive)
M_PER_DEG = 2 * np.pi * MARS_R / 360


def srs(defn):
    s = osr.SpatialReference()
    s.SetFromUserInput(defn)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)   # always lon, lat
    return s


def crop(src, dst, bbox, **kw):
    """Crop to the site box (lon/lat) while keeping the native projection, unless dstSRS is given."""
    gdal.Warp(str(dst), str(src), outputBounds=bbox, outputBoundsSRS=MARS_LL, **kw)
    return dst


def make_tiles(src, out_dir, zooms, work):
    """Reproject to Mars lon/lat, label it as EPSG:4326 (degrees are degrees for web tiles), and tile it.
    The relabel avoids GDAL's 'different celestial body' error; distances are computed with the Mars radius elsewhere."""
    ll = work / (Path(out_dir).name + "_ll.tif")
    gdal.Warp(str(ll), str(src), dstSRS=MARS_LL, resampleAlg="bilinear", dstAlpha=True)
    tagged = work / (Path(out_dir).name + "_4326.tif")
    gdal.Translate(str(tagged), str(ll), outputSRS="EPSG:4326")
    # Run gdal2tiles as a module with this Python: works on Windows too, where "gdal2tiles.py" isn't executable.
    try:
        import osgeo_utils.gdal2tiles  # noqa: F401
        cmd = [sys.executable, "-m", "osgeo_utils.gdal2tiles"]
    except ImportError:
        exe = shutil.which("gdal2tiles.py") or shutil.which("gdal2tiles")
        if not exe:
            sys.exit("gdal2tiles not found; install GDAL's command-line tools")
        cmd = [exe]
    if Path(out_dir).exists():
        shutil.rmtree(out_dir)
    Path(out_dir).parent.mkdir(parents=True, exist_ok=True)   # GDAL 3.13's tiler won't create parent folders
    subprocess.run(cmd + ["--xyz", "-z", zooms, "-w", "none", "-r", "bilinear", "--processes=4",
                          str(tagged), str(out_dir)], check=True)


def colorize_gray(src_path, dst_path, palette_name):
    """Greyscale orbital image -> Mars-coloured RGBA (alpha 0 where there is no data).
    Same palettes as fetch_ctx_tiles.py; the stretch is shared by the whole image so tiles match."""
    from PIL import Image, ImageOps
    from fetch_ctx_tiles import PALETTES
    ds = gdal.Open(str(src_path))
    band = ds.GetRasterBand(1)
    a = band.ReadAsArray()
    nd = band.GetNoDataValue()
    valid = a != (0 if nd is None else nd)
    lo, hi = np.percentile(a[valid], [1, 99])
    g = np.clip((a.astype("float32") - lo) * 255 / max(1.0, hi - lo), 0, 255).astype("uint8")
    palette = PALETTES[palette_name]
    if palette is None:
        rgb = np.repeat(g[..., None], 3, axis=2)
    else:
        ramp = Image.fromarray(np.arange(256, dtype="uint8")[None, :])
        lut = np.asarray(ImageOps.colorize(ramp, black=palette[0], mid=palette[1], white=palette[2]))[0]   # (256, 3)
        rgb = lut[g]
    out = gdal.GetDriverByName("GTiff").Create(str(dst_path), ds.RasterXSize, ds.RasterYSize, 4, gdal.GDT_Byte,
                                               ["COMPRESS=DEFLATE", "TILED=YES", "PHOTOMETRIC=RGB", "ALPHA=YES"])
    out.SetGeoTransform(ds.GetGeoTransform())
    out.SetProjection(ds.GetProjection())
    for i in range(3):
        out.GetRasterBand(i + 1).WriteArray(rgb[..., i])
    out.GetRasterBand(4).WriteArray(np.where(valid, 255, 0).astype("uint8"))
    out.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
    out = None
    return dst_path


def mask_to_polygons(mask, ref_ds, min_pixels, props, simplify_m):
    """Turn a boolean raster mask into GeoJSON polygon features in Mars lon/lat."""
    drv = gdal.GetDriverByName("MEM")
    m = drv.Create("", ref_ds.RasterXSize, ref_ds.RasterYSize, 1, gdal.GDT_Byte)
    m.SetGeoTransform(ref_ds.GetGeoTransform())
    m.SetProjection(ref_ds.GetProjection())
    band = m.GetRasterBand(1)
    band.WriteArray(mask.astype("uint8"))
    gdal.SieveFilter(band, None, band, min_pixels, 8)          # drop tiny specks
    native = srs(ref_ds.GetProjection())
    vec = (ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")).CreateDataSource("")
    lyr = vec.CreateLayer("p", srs=native, geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    to_ll = osr.CoordinateTransformation(native, srs(MARS_LL))
    tol = simplify_m / M_PER_DEG if native.IsGeographic() else simplify_m
    feats = []
    for i, f in enumerate(lyr):
        g = f.GetGeometryRef().SimplifyPreserveTopology(tol)
        g.Transform(to_ll)
        gj = json.loads(g.ExportToJson())
        if gj["type"] != "Polygon":
            continue
        feats.append({"type": "Feature", "geometry": gj, "properties": {**props, "id": f"{props['id']}{i + 1}"}})
    return feats


def main(cfg_path, skip_tiles=False):
    cfg = json.loads(Path(cfg_path).read_text())
    root = Path(cfg_path).resolve().parent.parent
    out = root / cfg["output_dir"]
    work = out / "_work"
    work.mkdir(parents=True, exist_ok=True)
    bbox = cfg["bbox"]                                           # [lon_min, lat_min, lon_max, lat_max]
    # Local paths are relative to the project root. "/vsicurl/https://..." streams only the part of a
    # remote GeoTIFF inside your bbox, so you don't need to download the full 1.8 GB mosaic.
    inp = {k: (None if not v else v if v.startswith("/vsi") else root / v) for k, v in cfg["inputs"].items()}
    zooms = cfg.get("tile_zooms", "13-18")

    # 1. Terrain: crop the DTM and compute slope in degrees.
    print("1/6 slope from terrain model")
    dtm = crop(inp["dtm"], work / "dtm.tif", bbox, resampleAlg="bilinear")
    dtm_ds = gdal.Open(str(dtm))
    scale = M_PER_DEG if srs(dtm_ds.GetProjection()).IsGeographic() else 1.0
    slope_path = work / "slope.tif"
    gdal.DEMProcessing(str(slope_path), str(dtm), "slope", scale=scale, computeEdges=True)

    # 2. Slope colour tiles.
    print("2/6 slope tiles")
    ramp = work / "slope_colors.txt"
    ramp.write_text("nv 0 0 0 0\n0 0 0 0 0\n10 0 0 0 0\n15 255 201 60 170\n25 255 77 77 230\n90 255 0 0 255\n")
    slope_rgba = work / "slope_rgba.tif"
    gdal.DEMProcessing(str(slope_rgba), str(slope_path), "color-relief", colorFilename=str(ramp), addAlpha=True)
    if skip_tiles:
        print("    skipped (--skip-tiles)")
    else:
        make_tiles(slope_rgba, out / "tiles" / "slope", zooms, work)

    # 3. Imagery tiles (8-bit, contrast-stretched).
    if inp.get("imagery") and not skip_tiles:
        print("3/6 imagery tiles")
        img = crop(inp["imagery"], work / "img.tif", bbox, resampleAlg="bilinear")
        img_rgba = colorize_gray(img, work / "img_rgba.tif", cfg.get("imagery_color", "mars"))
        make_tiles(img_rgba, out / "tiles" / "imagery", zooms, work)

    # 4. Hazards: steep ground + soft ground (+ hand-traced).
    print("4/6 hazards")
    slope_ds = gdal.Open(str(slope_path))
    slope = slope_ds.GetRasterBand(1).ReadAsArray().astype("float32")
    nd = slope_ds.GetRasterBand(1).GetNoDataValue()
    if nd is not None:
        slope[slope == nd] = np.nan
    px_m = abs(slope_ds.GetGeoTransform()[1]) * scale
    min_px = max(4, int(cfg.get("min_hazard_area_m2", 400) / (px_m * px_m)))
    hz_deg = cfg.get("hazard_slope_deg", 25)
    hazards = mask_to_polygons(slope > hz_deg, slope_ds, min_px,
                               {"id": "SL", "name": "Steep slope", "kind": "slope", "min_slope_deg": hz_deg,
                                "source": "DTM slope", "warn_m": 60}, simplify_m=px_m * 2)
    soft = np.zeros_like(slope, dtype=bool)
    if inp.get("thermal_inertia"):
        # Resample thermal inertia onto exactly the same grid as the slope raster.
        g = slope_ds.GetGeoTransform()
        nx, ny = slope_ds.RasterXSize, slope_ds.RasterYSize
        extent = [g[0], g[3] + ny * g[5], g[0] + nx * g[1], g[3]]
        ti = work / "ti.tif"
        gdal.Warp(str(ti), str(inp["thermal_inertia"]), dstSRS=slope_ds.GetProjection(),
                  outputBounds=extent, width=nx, height=ny, resampleAlg="bilinear")
        ti_ds = gdal.Open(str(ti))          # keep a reference: newer GDAL frees a dataset used only in a chain
        ti_arr = ti_ds.GetRasterBand(1).ReadAsArray().astype("float32")
        soft = (ti_arr > 0) & (ti_arr < cfg.get("soft_ground_ti_max", 150))   # low thermal inertia = loose dust/sand
        hazards += mask_to_polygons(soft, slope_ds, min_px,
                                    {"id": "SG", "name": "Loose sand", "kind": "soft_ground",
                                     "source": "THEMIS thermal inertia", "warn_m": 60}, simplify_m=px_m * 3)
    if cfg.get("manual_hazards"):
        hazards += json.loads((root / cfg["manual_hazards"]).read_text())["features"]
    (out / "hazards.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": hazards}))
    print(f"    {len(hazards)} hazard polygons")

    # 5. Route: A* over a downsampled slope grid, avoiding steep and soft ground.
    print("5/6 route planning")
    max_px = cfg.get("planner_max_pixels", 800)
    f = max(1, int(np.ceil(max(slope.shape) / max_px)))
    small = slope[::f, ::f]
    blocked = soft[::f, ::f]
    cost = cost_grid(small, max_slope=cfg.get("max_route_slope_deg", 15), blocked=blocked)
    gt = slope_ds.GetGeoTransform()
    native = srs(slope_ds.GetProjection())
    ll2nat = osr.CoordinateTransformation(srs(MARS_LL), native)
    nat2ll = osr.CoordinateTransformation(native, srs(MARS_LL))

    def to_rc(lon, lat):
        x, y, _ = ll2nat.TransformPoint(lon, lat)
        c = int((x - gt[0]) / gt[1]) // f
        r = int((y - gt[3]) / gt[5]) // f
        return (min(max(r, 0), small.shape[0] - 1), min(max(c, 0), small.shape[1] - 1))

    def to_ll(r, c):
        x = gt[0] + (c * f + f / 2) * gt[1]
        y = gt[3] + (r * f + f / 2) * gt[5]
        lon, lat, _ = nat2ll.TransformPoint(x, y)
        return [round(lon, 6), round(lat, 6)]

    wps = cfg["waypoints"]
    path = plan_through(cost, [to_rc(*w["coord"]) for w in wps])
    line = ogr.Geometry(ogr.wkbLineString)
    for r, c in path:
        line.AddPoint_2D(*to_ll(r, c))
    line = line.Simplify(cfg.get("route_simplify_m", 5) / M_PER_DEG)
    coords = [list(p[:2]) for p in line.GetPoints()]
    coords[0], coords[-1] = wps[0]["coord"], wps[-1]["coord"]
    max_on_route = float(np.nanmax([small[r, c] for r, c in path]))
    (out / "route.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": cfg["name"] + " route", "max_slope_deg": round(max_on_route, 1)},
         "geometry": {"type": "LineString", "coordinates": coords}}]}))
    (out / "waypoints.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {k: v for k, v in w.items() if k != "coord"},
         "geometry": {"type": "Point", "coordinates": w["coord"]}} for w in wps]}))
    print(f"    route: {len(coords)} points, max slope on route {max_on_route:.1f} deg")

    # 6. Mission metadata + conditions.
    print("6/6 mission files")
    mission = {"name": cfg["name"], "site": cfg["site"], "center": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
               "zoom": cfg.get("zoom", 15.5), "tile_maxzoom": int(zooms.split("-")[-1]),
               "science_goal": cfg.get("science_goal", ""), "goal_short": cfg.get("goal_short", ""),
               "imagery_credit": "HiRISE 25 cm orthomosaic and 1 m DTM: NASA/JPL/UArizona, USGS Mars 2020 TRN mosaics; "
                                 "thermal inertia: THEMIS (Zenodo 4931348)",
               "data_note": "Built by pipeline/build_site.py from HiRISE DTM slope and THEMIS thermal inertia.",
               "eva_duration_min": cfg.get("eva_duration_min", 420),
               "o2_reserve_min": cfg.get("o2_reserve_min", 30), "crew": cfg.get("crew", ["EV1", "EV2"])}
    (out / "mission.json").write_text(json.dumps(mission, indent=1))
    (out / "conditions.json").write_text(json.dumps(cfg["conditions"], indent=1))
    if not cfg.get("keep_work"):
        dtm_ds = slope_ds = None            # close GDAL files first; Windows can't delete open files
        shutil.rmtree(work, ignore_errors=True)
    print(f"Done -> {out}\nRun: python backend/server.py --mission {out}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    # --skip-tiles: reuse the tiles from an earlier run and redo only slope/hazards/route/mission files.
    main(args[0] if args else "pipeline/site_jezero.json", skip_tiles="--skip-tiles" in sys.argv)
