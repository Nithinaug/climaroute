"""Terrain flood risk per edge (offline): DEM depressions, flow accumulation, local lows."""

import io
import json
import tempfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import LineString

from shared import area
from shared.storage import read_bytes, write_bytes

DEM_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N12_00_E077_00_DEM/"
    "Copernicus_DSM_COG_10_N12_00_E077_00_DEM.tif"
)
DEM_BUFFER_DEG = 0.02  # ~2 km so drainage from outside the area is counted
LOCAL_WINDOW_PX = 11  # ~330 m neighbourhood for "lower than surroundings"
FULL_DEPTH_M, FULL_LOW_M = 2.0, 3.0
WEIGHTS = {"accumulation": 0.4, "depression": 0.3, "local_low": 0.3}
FLOOD_SPOT_RADIUS_M = 60.0
SAMPLES_PER_EDGE = 5
CONTRAST = 2.0  # >1 pushes middling streets down so only clear low spots score high


def _untiled(profile: dict) -> dict:
    return {k: v for k, v in profile.items() if k not in ("tiled", "blockxsize", "blockysize")}


def _dem_bytes() -> bytes:
    """Copernicus GLO-30 clipped around the area, cached at raw/dem.tif."""
    try:
        return read_bytes("raw/dem.tif")
    except FileNotFoundError:
        min_lon, min_lat, max_lon, max_lat = area.BBOX
        b = DEM_BUFFER_DEG
        with rasterio.open(f"/vsicurl/{DEM_URL}") as src:
            window = from_bounds(min_lon - b, min_lat - b, max_lon + b, max_lat + b, src.transform)
            data = src.read(1, window=window)
            profile = _untiled(src.profile) | {
                "height": data.shape[0],
                "width": data.shape[1],
                "transform": src.window_transform(window),
            }
        with rasterio.MemoryFile() as mem:
            with mem.open(**profile) as dst:
                dst.write(data, 1)
            out = mem.read()
        write_bytes("raw/dem.tif", out)
        return out


def risk_raster() -> tuple[np.ndarray, rasterio.Affine]:
    """0-1 terrain risk on the DEM grid (lon/lat)."""
    # ponytail: pysheds 0.5 still calls np.in1d (removed in NumPy 2.4); drop once it's fixed.
    np.in1d = getattr(np, "in1d", np.isin)
    from pysheds.grid import Grid

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dem.tif"
        path.write_bytes(_dem_bytes())
        grid = Grid.from_raster(str(path))
        dem = grid.read_raster(str(path))
        flooded = grid.fill_depressions(grid.fill_pits(dem))
        acc = grid.accumulation(grid.flowdir(grid.resolve_flats(flooded)))
        with rasterio.open(io.BytesIO(path.read_bytes())) as src:
            transform = src.transform

    dem, flooded, acc = (np.asarray(a, dtype=float) for a in (dem, flooded, acc))
    acc_n = np.log1p(acc) / np.log1p(acc.max())
    depth_n = np.clip((flooded - dem) / FULL_DEPTH_M, 0, 1)
    low_n = np.clip((ndimage.uniform_filter(dem, LOCAL_WINDOW_PX) - dem) / FULL_LOW_M, 0, 1)
    risk = (
        WEIGHTS["accumulation"] * acc_n
        + WEIGHTS["depression"] * depth_n
        + WEIGHTS["local_low"] * low_n
    )
    return np.clip(risk, 0, 1), transform


def _sample(risk: np.ndarray, transform, lonlat: list[list[float]]) -> float:
    line = LineString(lonlat)
    points = [line.interpolate(t, normalized=True) for t in np.linspace(0, 1, SAMPLES_PER_EDGE)]
    inv = ~transform
    values = []
    for p in points:
        col, row = inv * (p.x, p.y)
        r, c = int(row), int(col)
        if 0 <= r < risk.shape[0] and 0 <= c < risk.shape[1]:
            values.append(risk[r, c])
    return float(max(values)) if values else 0.0


def _near_flood_spots(graph: nx.MultiDiGraph) -> set[str]:
    spots = gpd.read_file(
        io.BytesIO((Path(__file__).parent / "known_flood_spots.geojson").read_bytes())
    ).to_crs(area.UTM_CRS)
    zones = spots.geometry.buffer(FLOOD_SPOT_RADIUS_M).union_all()
    return {d["edge_id"] for _, _, d in graph.edges(data=True) if d["geometry"].intersects(zones)}


def terrain_risk(graphs: list[nx.MultiDiGraph]) -> dict[str, float]:
    """{edge_id: 0-1} for every edge in the graphs. Known flood spots are 1.0."""
    risk, transform = risk_raster()
    raw = {}
    for g in graphs:
        for _, _, d in g.edges(data=True):
            raw.setdefault(d["edge_id"], _sample(risk, transform, d["lonlat"]))
    # Scale so the riskiest streets in the area approach 1.0, then sharpen.
    top = float(np.percentile(list(raw.values()), 99)) or 1.0
    out = {k: round(min(v / top, 1.0) ** CONTRAST, 3) for k, v in raw.items()}
    for g in graphs:
        for edge_id in _near_flood_spots(g):
            out[edge_id] = 1.0
    return out


def write(graphs: list[nx.MultiDiGraph]) -> dict[str, float]:
    risk = terrain_risk(graphs)
    write_bytes("terrain/terrain_risk.json", json.dumps(risk).encode())
    return risk
