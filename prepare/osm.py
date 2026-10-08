"""OSM data: from a regional .osm.pbf when OSM_REGION_PBF is set (city scale, on Fargate),
otherwise from Overpass, cached under raw/ (slow and sometimes down; fine for a neighbourhood)."""

import io
import logging
import os
import pickle
import tempfile
from functools import cache
from pathlib import Path

import geopandas as gpd
import osmnx as ox

from prepare import pbf
from shared import area
from shared.storage import read_bytes, write_bytes

log = logging.getLogger(__name__)
OVERPASS_URLS = ["https://overpass-api.de/api", "https://overpass.private.coffee/api"]
BUILDING_BUFFER_DEG = 0.004  # ~400 m: buildings outside the area still cast shadows into it
ox.settings.requests_timeout = 180
REGION_PBF = os.environ.get("OSM_REGION_PBF")


@cache
def _area_pbf() -> str:
    min_lon, min_lat, max_lon, max_lat = area.BBOX
    b = BUILDING_BUFFER_DEG
    out = str(Path(tempfile.gettempdir()) / "area.osm.pbf")
    return pbf.clip(REGION_PBF, (min_lon - b, min_lat - b, max_lon + b, max_lat + b), out)


def _with_mirrors(fetch):
    for url in OVERPASS_URLS:
        ox.settings.overpass_url = url
        try:
            return fetch()
        except Exception as e:  # noqa: BLE001 - any Overpass failure: try the next mirror
            log.warning("overpass %s failed: %s", url, e)
    raise RuntimeError("all Overpass mirrors failed")


def _cached(key: str, fetch, dump, load):
    try:
        return load(read_bytes(key))
    except FileNotFoundError:
        value = _with_mirrors(fetch)
        write_bytes(key, dump(value))
        return value


def street_graph(network_type: str):
    """Unprojected osmnx graph (lat/lon)."""
    if REGION_PBF:
        return pbf.street_graph(_area_pbf(), network_type)
    return _cached(
        area.raw_key(f"osm_{network_type}.pkl"),
        lambda: ox.graph_from_bbox(area.BBOX, network_type=network_type, simplify=True),
        pickle.dumps,
        pickle.loads,
    )


def features(name: str, tags: dict, buffer_deg: float = 0.0) -> gpd.GeoDataFrame:
    """OSM features as WGS84 GeoDataFrame."""
    if REGION_PBF:
        return pbf.features(_area_pbf(), tags)
    min_lon, min_lat, max_lon, max_lat = area.BBOX
    bbox = (min_lon - buffer_deg, min_lat - buffer_deg, max_lon + buffer_deg, max_lat + buffer_deg)

    def fetch():
        try:
            gdf = ox.features_from_bbox(bbox, tags=tags)
        except ox._errors.InsufficientResponseError:
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        return gdf.reset_index()[
            [
                c
                for c in ("geometry", "height", "building:levels", "building", "name")
                if c in gdf.columns
            ]
        ]

    return _cached(
        area.raw_key(f"{name}.geojson"),
        fetch,
        lambda gdf: gdf.to_json(drop_id=True).encode(),
        lambda b: gpd.read_file(io.BytesIO(b)),
    )


def buildings() -> gpd.GeoDataFrame:
    gdf = features("buildings", {"building": True}, BUILDING_BUFFER_DEG)
    return gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index(drop=True)


def trees() -> gpd.GeoDataFrame:
    return features("trees", {"natural": ["tree", "tree_row"]}, BUILDING_BUFFER_DEG)


def water_points() -> gpd.GeoDataFrame:
    gdf = features("water_points", {"amenity": "drinking_water"})
    return gdf[gdf.geometry.geom_type == "Point"].reset_index(drop=True)
