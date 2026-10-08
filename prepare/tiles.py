"""Sun positions and the tile inputs for the shade pipeline."""

import math
from collections import defaultdict
from datetime import date

import geopandas as gpd
import networkx as nx
from shapely import STRtree, box

from prepare.graphs import SHADE_DATE, SLOT_COUNT, SLOT_MINUTES, SLOT_START
from shade import sun
from shared import area

TILE_SIZE_M = 500
LOW_SUN_DEG = 10.0  # below this every edge counts as shaded; caps shadow length


def slots() -> list[dict]:
    return sun.slots(
        date.fromisoformat(SHADE_DATE),
        area.CENTER["lat"],
        area.CENTER["lon"],
        area.TIMEZONE,
        SLOT_START,
        SLOT_MINUTES,
        SLOT_COUNT,
    )


def tile_inputs(graphs: list[nx.MultiDiGraph], shade_casters: gpd.GeoDataFrame) -> dict[str, dict]:
    """shade_casters: UTM polygons with height_m (buildings and tree canopies)."""
    edges: dict[str, dict[str, str]] = defaultdict(dict)
    for g in graphs:
        for _, _, d in g.edges(data=True):
            mid = d["geometry"].interpolate(0.5, normalized=True)
            tile_id = f"t_{int(mid.x // TILE_SIZE_M)}_{int(mid.y // TILE_SIZE_M)}"
            edges[tile_id][d["edge_id"]] = d["geometry"].wkt

    buffer_m = shade_casters["height_m"].max() / math.tan(math.radians(LOW_SUN_DEG))
    tree = STRtree(shade_casters.geometry.values)
    out = {}
    for tile_id, tile_edges in edges.items():
        _, tx, ty = tile_id.split("_")
        bbox = [
            int(tx) * TILE_SIZE_M,
            int(ty) * TILE_SIZE_M,
            (int(tx) + 1) * TILE_SIZE_M,
            (int(ty) + 1) * TILE_SIZE_M,
        ]
        nearby = shade_casters.iloc[tree.query(box(*bbox).buffer(buffer_m))]
        out[tile_id] = {
            "tile_id": tile_id,
            "bbox": [float(b) for b in bbox],
            "edges": [{"edge_id": k, "wkt": v} for k, v in sorted(tile_edges.items())],
            "buildings": [
                {"wkt": g.wkt, "height_m": float(h)}
                for g, h in zip(nearby.geometry, nearby["height_m"], strict=True)
            ],
        }
    return out
