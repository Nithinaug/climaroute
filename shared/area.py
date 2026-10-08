"""The covered area, shared by prepare/ (what to download) and api/ (what to accept)."""

import json
import os
from functools import cache

from shared.storage import read_bytes

NAME = os.environ.get("AREA_NAME", "Koramangala, Bengaluru")
_BBOX = os.environ.get("AREA_BBOX", "77.612,12.925,77.636,12.945")
BBOX = tuple(float(v) for v in _BBOX.split(","))  # min_lon, min_lat, max_lon, max_lat
CENTER = {"lat": (BBOX[1] + BBOX[3]) / 2, "lon": (BBOX[0] + BBOX[2]) / 2}
UTM_CRS = "EPSG:32643"
TIMEZONE = "Asia/Kolkata"
SLOT_START, SLOT_MINUTES, SLOT_COUNT = "06:00", 15, 52  # 06:00 .. 18:45


def raw_key(name: str) -> str:
    """Cache key for downloaded source data, per area so a new bbox never reuses old data."""
    return f"raw/{_BBOX}/{name}"


def contains(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = BBOX
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


@cache
def water_points() -> dict:
    try:
        return json.loads(read_bytes("data/water_points.geojson"))
    except FileNotFoundError:
        return {"type": "FeatureCollection", "features": []}
