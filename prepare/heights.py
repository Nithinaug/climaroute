"""Building heights: OSM tags -> Google Open Buildings 2.5D (2023) -> default by type."""

import io
import json
import logging
import urllib.parse
import urllib.request

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from scipy import ndimage

from shared import area
from shared.storage import read_bytes, write_bytes

log = logging.getLogger(__name__)

BUCKET_API = "https://storage.googleapis.com/storage/v1/b/open-buildings-temporal-data/o"
HEIGHT_YEAR = "2023_06_30"
HEIGHT_BAND = 2  # bands: fractional_count, height, presence
RESOLUTION_M = 2.0  # source is 0.5 m pixels with ~4 m effective resolution
LEVEL_HEIGHT_M = 3.0
MIN_HEIGHT_M, MAX_HEIGHT_M = 3.0, 100.0
DEFAULT_HEIGHT_M = 9.0
HEIGHT_BY_TYPE = {
    "apartments": 15.0,
    "commercial": 15.0,
    "office": 15.0,
    "retail": 12.0,
    "hotel": 15.0,
    "hospital": 15.0,
    "college": 12.0,
    "school": 9.0,
    "industrial": 8.0,
    "warehouse": 8.0,
    "garage": 3.0,
    "garages": 3.0,
    "shed": 3.0,
    "roof": 3.0,
    "hut": 3.0,
    "kiosk": 3.0,
    "house": 9.0,
    "residential": 9.0,
    "detached": 9.0,
    "temple": 9.0,
}


def _parse_m(value) -> float | None:
    try:
        return float(str(value).lower().replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def _osm_height(row) -> float | None:
    h = _parse_m(row.get("height"))
    if h:
        return h
    levels = _parse_m(row.get("building:levels"))
    return levels * LEVEL_HEIGHT_M if levels else None


def manifest_urls() -> list[str]:
    """The dataset's manifests for the area's UTM zone; each lists every tile and its extent."""
    epsg = area.UTM_CRS.split(":")[1]
    query = urllib.parse.urlencode(
        {"prefix": "v1/manifests/", "matchGlob": f"**_EPSG_{epsg}_{HEIGHT_YEAR}.json"}
    )
    with urllib.request.urlopen(f"{BUCKET_API}?{query}") as resp:
        names = [item["name"] for item in json.load(resp).get("items", [])]
    return [f"https://storage.googleapis.com/open-buildings-temporal-data/{n}" for n in names]


def tile_urls(bounds: tuple[float, float, float, float], manifests: list[dict]) -> list[str]:
    """Open Buildings tiles overlapping UTM bounds (min_x, min_y, max_x, max_y)."""
    urls = []
    for m in manifests:
        prefix = m["uriPrefix"].replace("gs://", "https://storage.googleapis.com/")
        for source in (s for t in m["tilesets"] for s in t["sources"]):
            t, size = source["affineTransform"], source["dimensions"]
            x0, y1 = t["translateX"], t["translateY"]
            x1, y0 = x0 + size["width"] * t["scaleX"], y1 + size["height"] * t["scaleY"]
            if x0 < bounds[2] and bounds[0] < x1 and y0 < bounds[3] and bounds[1] < y1:
                urls += [prefix + uri for uri in source["uris"]]
    return urls


def _height_raster(bounds: tuple[float, float, float, float]) -> tuple[np.ndarray, object]:
    """Open Buildings height for the UTM bounds, cached per area."""
    key = area.raw_key("building_heights.tif")
    try:
        data = read_bytes(key)
    except FileNotFoundError:
        manifests = [json.load(urllib.request.urlopen(url)) for url in manifest_urls()]
        sources = [rasterio.open(f"/vsicurl/{url}") for url in tile_urls(bounds, manifests)]
        array, transform = merge(sources, bounds=bounds, res=RESOLUTION_M, indexes=[HEIGHT_BAND])
        base = {
            k: v
            for k, v in sources[0].profile.items()
            if k not in ("tiled", "blockxsize", "blockysize")
        }
        profile = base | {
            "driver": "GTiff",
            "count": 1,
            "transform": transform,
            "width": array.shape[2],
            "height": array.shape[1],
        }
        with rasterio.MemoryFile() as mem:
            with mem.open(**profile) as dst:
                dst.write(array)
            data = mem.read()
        write_bytes(key, data)
    with rasterio.open(io.BytesIO(data)) as src:
        return src.read(1), src.transform


def _open_buildings_heights(footprints: gpd.GeoSeries) -> np.ndarray:
    """Median Open Buildings height inside each footprint (NaN where none)."""
    heights, transform = _height_raster(tuple(footprints.total_bounds))
    labels = rasterize(
        ((geom, i + 1) for i, geom in enumerate(footprints)),
        out_shape=heights.shape,
        transform=transform,
        all_touched=True,
        dtype="int32",
    )
    labels[~(heights > 1.0)] = 0  # ignore ground / no-data pixels
    medians = ndimage.median(heights, labels, index=np.arange(1, len(footprints) + 1))
    return np.where(np.isfinite(medians) & (np.asarray(medians) > 0), medians, np.nan)


def assign_heights(buildings_utm: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Adds height_m and height_source columns. Input must be in UTM metres."""
    out = buildings_utm.copy()
    osm = np.array([_osm_height(row) or np.nan for _, row in out.iterrows()], dtype=float)
    try:
        ob = _open_buildings_heights(out.geometry)
    except Exception as e:  # noqa: BLE001 - heights are optional; fall back to defaults
        log.warning("Open Buildings heights unavailable, using defaults: %s", e)
        ob = np.full(len(out), np.nan)
    by_type = out.get("building", gpd.pd.Series(index=out.index, dtype=object))
    default = np.array([HEIGHT_BY_TYPE.get(str(t), DEFAULT_HEIGHT_M) for t in by_type])

    height = np.where(~np.isnan(osm), osm, np.where(~np.isnan(ob), ob, default))
    source = np.where(~np.isnan(osm), "osm", np.where(~np.isnan(ob), "open_buildings", "default"))
    out["height_m"] = np.clip(height, MIN_HEIGHT_M, MAX_HEIGHT_M).round(1)
    out["height_source"] = source
    return out
