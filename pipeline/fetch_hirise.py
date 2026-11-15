"""Cut the site box out of the USGS Mars 2020 TRN HiRISE mosaics without downloading the whole files.

    python pipeline/fetch_hirise.py pipeline/site_jezero.json        (laptop, needs GDAL + internet)

The DTM (1 m, 1.8 GB) and orthomosaic (25 cm, 7.4 GB) are stored uncompressed, so GDAL can read just
the byte ranges inside the site's bbox. Results are saved (compressed) to raw/, where site_jezero.json
expects them, so build_site.py never touches the network:
    raw/jezero_hirise_dtm.tif    DOI 10.5066/P9REJ9JN
    raw/jezero_hirise_ortho.tif  DOI 10.5066/P9QJDP48
"""
import json
import math
import sys
import time
from pathlib import Path

from osgeo import gdal

gdal.UseExceptions()
for k, v in {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GTIFF_DIRECT_IO": "YES", "GDAL_HTTP_MULTIRANGE": "YES",
             "GDAL_HTTP_MAX_RETRY": "5", "GDAL_HTTP_RETRY_DELAY": "2"}.items():
    gdal.SetConfigOption(k, v)

BASE = "/vsicurl/https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/"
SOURCES = {
    "raw/jezero_hirise_dtm.tif": BASE + "JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif",
    "raw/jezero_hirise_ortho.tif": BASE + "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first.tif",
}
R = 3396190.0   # the mosaics use simple cylindrical (eqc) on the Mars sphere


def main(cfg_path):
    cfg = json.loads(Path(cfg_path).read_text())
    root = Path(cfg_path).resolve().parent.parent
    lon0, lat0, lon1, lat1 = cfg["bbox"]
    m = lambda deg: math.radians(deg) * R
    for out, src in SOURCES.items():
        dst = root / out
        dst.parent.mkdir(exist_ok=True)
        print(f"{out}: cutting lon {lon0}..{lon1}, lat {lat0}..{lat1}")
        t = time.time()
        gdal.Translate(str(dst), src, projWin=[m(lon0), m(lat1), m(lon1), m(lat0)],
                       creationOptions=["COMPRESS=DEFLATE", "TILED=YES"], callback=gdal.TermProgress_nocb)
        ds = gdal.Open(str(dst))
        print(f"    {ds.RasterXSize} x {ds.RasterYSize} px in {time.time() - t:.0f} s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pipeline/site_jezero.json")
