"""Compact street network: numpy arrays instead of networkx, so a whole city fits in Lambda.

Directed edges (one per travel direction) point at "streets" (one per edge_id, shared by both
directions), which hold geometry, shade per slot (uint8, /255) and terrain risk.
"""

import io
import json
import math
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

M_PER_DEG_LAT = 110_574


@dataclass
class Net:
    meta: dict  # area_name, transport, crs, shade_date, slot_start, slot_minutes, slot_count
    node_lat: np.ndarray  # float64 [N]
    node_lon: np.ndarray  # float64 [N]
    src: np.ndarray  # int32 [E]
    dst: np.ndarray  # int32 [E]
    length: np.ndarray  # float32 [E], metres
    street: np.ndarray  # int32 [E] -> street index
    reverse: np.ndarray  # bool [E]: edge runs against the street's coordinate order
    street_id: np.ndarray  # str [S] (edge_id)
    street_name: np.ndarray  # str [S] ("" if unnamed)
    coords: np.ndarray  # float64 [C, 2] lon, lat
    coord_start: np.ndarray  # int64 [S + 1]: street s uses coords[coord_start[s]:coord_start[s+1]]
    shade: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), np.uint8))  # [S, slots]
    terrain: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))  # [S]

    @cached_property
    def _order(self) -> np.ndarray:
        return np.lexsort((self.dst, self.src))  # CSR order: by source node, then target

    @cached_property
    def indptr(self) -> np.ndarray:
        counts = np.bincount(self.src, minlength=len(self.node_lat))
        return np.concatenate([[0], np.cumsum(counts)])

    @cached_property
    def indices(self) -> np.ndarray:
        return self.dst[self._order]

    def matrix(self, weights: np.ndarray) -> csr_matrix:
        n = len(self.node_lat)
        return csr_matrix((weights[self._order], self.indices, self.indptr), shape=(n, n))

    def edge_between(self, u: int, v: int) -> int:
        row = slice(self.indptr[u], self.indptr[u + 1])
        pos = self.indptr[u] + int(np.flatnonzero(self.indices[row] == v)[0])
        return int(self._order[pos])

    @cached_property
    def kx(self) -> float:
        return 111_320 * math.cos(math.radians(float(self.node_lat.mean())))

    @cached_property
    def kdtree(self) -> cKDTree:
        return cKDTree(np.column_stack([self.node_lon * self.kx, self.node_lat * M_PER_DEG_LAT]))

    @cached_property
    def street_index(self) -> dict[str, int]:
        return {s: i for i, s in enumerate(self.street_id.tolist())}

    def mark_flood_spots(self, points: list[tuple[float, float]], radius_m: float) -> None:
        """Streets passing within radius_m of a known flood spot (lat, lon) get terrain risk 1.0."""
        if not points or not len(self.terrain):
            return
        # Checks street vertices only, so a long straight segment passing a spot can slip by.
        lon, lat = self.coords[:, 0], self.coords[:, 1]
        near = np.zeros(len(lat), dtype=bool)
        for plat, plon in points:  # plain distance test: no index to build, ~ms per spot
            near |= ((lat - plat) * M_PER_DEG_LAT) ** 2 + (
                (lon - plon) * self.kx
            ) ** 2 <= radius_m**2
        idx = np.flatnonzero(near)
        self.terrain[np.searchsorted(self.coord_start, idx, side="right") - 1] = 1.0

    def street_coords(self, s: int) -> np.ndarray:
        return self.coords[self.coord_start[s] : self.coord_start[s + 1]]

    def edge_coords(self, e: int) -> np.ndarray:
        c = self.street_coords(int(self.street[e]))
        return c[::-1] if self.reverse[e] else c

    ARRAYS = (
        "node_lat",
        "node_lon",
        "src",
        "dst",
        "length",
        "street",
        "reverse",
        "street_id",
        "street_name",
        "coords",
        "coord_start",
        "shade",
        "terrain",
    )

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez_compressed(
            buf, meta=np.array(json.dumps(self.meta)), **{k: getattr(self, k) for k in self.ARRAYS}
        )
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "Net":
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            return cls(meta=json.loads(str(z["meta"])), **{k: z[k] for k in cls.ARRAYS})


def from_graph(g) -> "Net":
    """osmnx-style MultiDiGraph -> Net. Parallel edges between the same
    two nodes keep only the shortest (rare after osmnx simplification)."""
    nodes = list(g.nodes)
    node_ix = {n: i for i, n in enumerate(nodes)}
    best: dict[tuple[int, int], dict] = {}
    for u, v, d in g.edges(data=True):
        key = (node_ix[u], node_ix[v])
        if key not in best or d["length"] < best[key]["length"]:
            best[key] = d

    street_ix: dict[str, int] = {}
    street_first: list[dict] = []
    src, dst, length, street, reverse = [], [], [], [], []
    for (u, v), d in best.items():
        sid = d["edge_id"]
        if sid not in street_ix:
            street_ix[sid] = len(street_first)
            street_first.append(d)
        first = street_first[street_ix[sid]]
        src.append(u)
        dst.append(v)
        length.append(d["length"])
        street.append(street_ix[sid])
        reverse.append(first is not d and first["lonlat"][0] != d["lonlat"][0])

    coord_start = np.concatenate([[0], np.cumsum([len(d["lonlat"]) for d in street_first])])
    has_shade = "shade" in street_first[0]
    meta = {
        k: g.graph.get(k)
        for k in (
            "area_name",
            "transport",
            "crs",
            "shade_date",
            "slot_start",
            "slot_minutes",
            "slot_count",
        )
    }
    return Net(
        meta=meta,
        node_lat=np.array([g.nodes[n]["lat"] for n in nodes], np.float64),
        node_lon=np.array([g.nodes[n]["lon"] for n in nodes], np.float64),
        src=np.array(src, np.int32),
        dst=np.array(dst, np.int32),
        length=np.array(length, np.float32),
        street=np.array(street, np.int32),
        reverse=np.array(reverse, bool),
        street_id=np.array([d["edge_id"] for d in street_first]),
        street_name=np.array([d.get("name") or "" for d in street_first]),
        coords=np.array([pt for d in street_first for pt in d["lonlat"]], np.float64),
        coord_start=coord_start.astype(np.int64),
        shade=(
            np.array([[round(x * 255) for x in d["shade"]] for d in street_first], np.uint8)
            if has_shade
            else np.zeros((len(street_first), 0), np.uint8)
        ),
        terrain=np.array([d.get("terrain_risk", 0.0) for d in street_first], np.float32),
    )
