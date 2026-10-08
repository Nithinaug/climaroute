"""Fake prepare/ output (grid street graph over Koramangala) to exercise the pipeline.

Used by tests as a tiny stand-in for prepare/ output.

"""

import json
import math
from collections import defaultdict

import networkx as nx
from shapely.geometry import LineString, box

from routing.net import from_graph
from shared.storage import write_bytes

SW = (12.928, 77.615)  # lat, lon of the grid's south-west corner
N, SPACING_M, TILE_M = 12, 150, 500
SLOT_COUNT = 52


def _lat_lon(i: int, j: int) -> tuple[float, float]:
    lat = SW[0] + j * SPACING_M / 110_574
    return lat, SW[1] + i * SPACING_M / (111_320 * math.cos(math.radians(SW[0])))


def _xy(lat: float, lon: float) -> tuple[float, float]:
    # Rough UTM 43N; fine for fake data.
    return 500_000 + (lon - 75) * 111_320 * math.cos(math.radians(lat)), lat * 110_574


def build_graph(transport: str) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(
        crs="EPSG:32643",
        area_name="Koramangala, Bengaluru (dummy grid)",
        transport=transport,
        shade_date="2026-10-08",
        slot_start="06:00",
        slot_minutes=15,
        slot_count=SLOT_COUNT,
    )
    for i in range(N):
        for j in range(N):
            lat, lon = _lat_lon(i, j)
            x, y = _xy(lat, lon)
            g.add_node(f"n{i}_{j}", x=x, y=y, lat=lat, lon=lon)
    for i in range(N):
        for j in range(N):
            for di, dj in ((1, 0), (0, 1)):
                if i + di >= N or j + dj >= N:
                    continue
                u, v = f"n{i}_{j}", f"n{i + di}_{j + dj}"
                one_way = transport == "two_wheeler" and dj == 0 and j % 3 == 1
                for a, b in ((u, v),) if one_way else ((u, v), (v, u)):
                    geom = LineString(
                        [(g.nodes[a]["x"], g.nodes[a]["y"]), (g.nodes[b]["x"], g.nodes[b]["y"])]
                    )
                    g.add_edge(
                        a,
                        b,
                        edge_id=f"e-{u}-{v}",
                        length=geom.length,
                        geometry=geom,
                        lonlat=[[g.nodes[n]["lon"], g.nodes[n]["lat"]] for n in (a, b)],
                        name=f"Dummy street {j if dj == 0 else i}",
                    )
    return g


def slots() -> list[dict]:
    out = []
    for s in range(SLOT_COUNT):
        t = s / (SLOT_COUNT - 1)  # 06:00 -> 18:45
        out.append(
            {
                "slot": s,
                "elevation_deg": round(80 * math.sin(math.pi * t), 1),
                "azimuth_deg": round(90 + 180 * t, 1),
            }
        )
    return out


def tiles(graphs: list[nx.MultiDiGraph]) -> dict[str, dict]:
    by_tile: dict[str, dict] = defaultdict(lambda: {"edges": {}, "buildings": []})
    for g in graphs:
        for _, _, d in g.edges(data=True):
            mid = d["geometry"].interpolate(0.5, normalized=True)
            tile_id = f"t_{int(mid.x // TILE_M)}_{int(mid.y // TILE_M)}"
            by_tile[tile_id]["edges"][d["edge_id"]] = d["geometry"].wkt
    out = {}
    for tile_id, t in by_tile.items():
        _, tx, ty = tile_id.split("_")
        bbox = [int(tx) * TILE_M, int(ty) * TILE_M, (int(tx) + 1) * TILE_M, (int(ty) + 1) * TILE_M]
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        out[tile_id] = {
            "tile_id": tile_id,
            "bbox": bbox,
            "edges": [{"edge_id": k, "wkt": v} for k, v in sorted(t["edges"].items())],
            "buildings": [{"wkt": box(cx - 10, cy - 10, cx + 10, cy + 10).wkt, "height_m": 12.0}],
        }
    return out


def terrain(graph: nx.MultiDiGraph) -> dict[str, float]:
    # Southern rows are "low-lying": risk 1.0 at the bottom edge, 0 from row 4 up.
    return {
        d["edge_id"]: round(max(0.0, 1 - int(u.split("_")[1]) / 4), 2)
        for u, _, d in graph.edges(data=True)
    }


def main() -> None:
    graphs = [build_graph(t) for t in ("walk", "two_wheeler")]
    tile_inputs = tiles(graphs)
    write_bytes(
        "tiles/index.json",
        json.dumps(
            {"shade_date": "2026-10-08", "slots": slots(), "tiles": sorted(tile_inputs)}
        ).encode(),
    )
    for tile_id, tile_input in tile_inputs.items():
        write_bytes(f"tiles/{tile_id}/input.json", json.dumps(tile_input).encode())
    for g in graphs:
        write_bytes(f"graph/{g.graph['transport']}_base.npz", from_graph(g).to_bytes())
    write_bytes("terrain/terrain_risk.json", json.dumps(terrain(graphs[0])).encode())
    print(f"{len(tile_inputs)} tiles, edges: {[g.number_of_edges() for g in graphs]}")


if __name__ == "__main__":
    main()
