"""The covered area, shared by prepare/ (what to download) and api/ (what to accept)."""

import json
from functools import cache

from shared.storage import read_bytes

NAME = "Koramangala, Bengaluru"
BBOX = (77.612, 12.925, 77.636, 12.945)  # min_lon, min_lat, max_lon, max_lat
CENTER = {"lat": 12.935, "lon": 77.624}
UTM_CRS = "EPSG:32643"
TIMEZONE = "Asia/Kolkata"


def contains(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = BBOX
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


@cache
def water_points() -> dict:
    try:
        return json.loads(read_bytes("data/water_points.geojson"))
    except FileNotFoundError:
        return {"type": "FeatureCollection", "features": []}
