"""Safe vs direct route search on a compact Net.

Costs for every edge are computed at once with numpy for each request, then scipy's
Dijkstra (C) finds the path. Penalties are non-negative multipliers of length.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from scipy.sparse.csgraph import dijkstra

from monsoon.rain import rain_factor
from routing import config
from routing.errors import NoRouteError, OutOfAreaError
from routing.net import M_PER_DEG_LAT, Net
from shared.area import TIMEZONE

BLOCKED = 1e9  # cost of an unusable edge; a path costing this much counts as no route


def _nearest_node(net: Net, lat: float, lon: float, label: str) -> int:
    dist, i = net.kdtree.query((lon * net.kx, lat * M_PER_DEG_LAT))
    if dist > config.SNAP_MAX_M:
        # Inside the city but nowhere near a street (a lake, park or field).
        raise OutOfAreaError(f"{label} isn't near a street. Pick a point on or next to a road.")
    return int(i)


def nearest_edge(net: Net, lat: float, lon: float) -> str:
    """edge_id of the street closest to a point (for flood reports)."""
    here = np.array([lon * net.kx, lat * M_PER_DEG_LAT])
    _, near = net.kdtree.query(here, k=min(8, len(net.node_lat)))
    best, best_d = None, float("inf")
    for u in np.atleast_1d(near):
        for pos in range(net.indptr[u], net.indptr[u + 1]):
            s = int(net.street[net._order[pos]])
            pts = net.street_coords(s) * [net.kx, M_PER_DEG_LAT]
            a, b = pts[:-1], pts[1:]
            ab = b - a
            t = np.clip(((here - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
            d = float(np.min(np.linalg.norm(a + t[:, None] * ab - here, axis=1)))
            if d < best_d:
                best, best_d = s, d
    if best is None or best_d > config.SNAP_EDGE_MAX_M:
        raise OutOfAreaError("Tap on a street to report flooding.")
    return str(net.street_id[best])


def slot_index(meta: dict, departure: datetime) -> float | None:
    """Fractional shade slot for the departure's local time (16:07 -> between the 16:00
    and 16:15 slots), or None at night."""
    departure = departure.astimezone(ZoneInfo(TIMEZONE))
    h, m = map(int, meta["slot_start"].split(":"))
    minutes = departure.hour * 60 + departure.minute + departure.second / 60 - (h * 60 + m)
    slot = minutes / meta["slot_minutes"]
    return slot if 0 <= slot < meta["slot_count"] else None


def street_shade(net: Net, slot: float | None) -> np.ndarray:
    """Shade 0-1 per street, blended between the two nearest slots; night counts as shaded."""
    if slot is None:
        return np.ones(len(net.street_id), np.float32)
    i = int(slot)
    j = min(i + 1, net.shade.shape[1] - 1)
    frac = slot - i
    return (net.shade[:, i] * (1 - frac) + net.shade[:, j] * frac) / 255.0


def edge_weights(
    net: Net,
    mode: str,
    transport: str,
    slot: float | None,
    rain_mm: float,
    heat: float,
    reports: dict[str, float],
) -> np.ndarray:
    """Safe-route cost per directed edge; BLOCKED where unusable."""
    if mode == "summer":
        sun = 1 - street_shade(net, slot)[net.street]
        w = net.length * (1 + config.ALPHA[transport] * heat * sun)
    else:
        risk = net.terrain[net.street] * rain_factor(rain_mm)
        w = net.length * (1 + config.BETA[transport] * risk)
        w = np.where(risk > config.BLOCK_THRESHOLD[transport], BLOCKED, w)
    if reports:
        strength = np.zeros(len(net.street_id), np.float32)
        for edge_id, s in reports.items():
            if (k := net.street_index.get(edge_id)) is not None:
                strength[k] = s
        es = strength[net.street]
        w = np.where(es >= 1.0, BLOCKED, w * (1 + config.REPORT_PENALTY * es))
    return w.astype(np.float64)


def _path(net: Net, source: int, target: int, weights: np.ndarray) -> list[int]:
    """Edge indices of the cheapest path."""
    dist, pred = dijkstra(net.matrix(weights), indices=source, return_predecessors=True)
    if not np.isfinite(dist[target]) or dist[target] >= BLOCKED:
        raise NoRouteError("No safe route found between these points right now.")
    nodes = [target]
    while nodes[-1] != source:
        nodes.append(int(pred[nodes[-1]]))
    nodes.reverse()
    return [net.edge_between(u, v) for u, v in zip(nodes, nodes[1:], strict=False)]


def _feature(net: Net, edges: list[int]) -> dict:
    coords: list[list[float]] = []
    for e in edges:
        pts = net.edge_coords(e).round(6).tolist()
        coords.extend(pts if not coords else pts[1:])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {},
    }


def _stats(
    net: Net, edges: list[int], mode: str, transport: str, slot, rain_mm: float, reports: dict
) -> dict:
    e = np.array(edges, dtype=np.int64)
    streets = net.street[e]
    lengths = net.length[e].astype(np.float64)
    distance = float(lengths.sum())
    stats = {
        "distance_m": round(distance),
        "duration_min": round(distance / config.SPEED_M_PER_S[transport] / 60, 1),
        "shaded_pct": None,
        "risk_streets": None,
        "reported_streets": len({str(net.street_id[s]) for s in streets} & set(reports)),
    }
    if mode == "summer":
        shaded = float((lengths * street_shade(net, slot)[streets]).sum())
        stats["shaded_pct"] = round(100 * shaded / distance) if distance else 0
    else:
        risky = net.terrain[streets] * rain_factor(rain_mm) >= config.RISK_STREET_THRESHOLD
        stats["risk_streets"] = len(set(streets[risky].tolist()))
    return stats


def find_routes(
    net: Net,
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
    transport: str,
    departure_time: datetime,
    rain_mm_per_hour: float,
    heat_factor: float = 1.0,
    reports: dict[str, float] | None = None,
) -> dict:
    """reports: {edge_id: strength 0-1} from active flood reports."""
    reports = reports or {}
    source = _nearest_node(net, *origin, "Start")
    target = _nearest_node(net, *destination, "Destination")
    if source == target:
        raise NoRouteError("Start and destination are the same place.")
    slot = slot_index(net.meta, departure_time)

    safe = _path(
        net,
        source,
        target,
        edge_weights(net, mode, transport, slot, rain_mm_per_hour, heat_factor, reports),
    )
    direct = _path(net, source, target, net.length.astype(np.float64))
    return {
        "safe_route": _feature(net, safe),
        "direct_route": _feature(net, direct),
        "stats": {
            "safe": _stats(net, safe, mode, transport, slot, rain_mm_per_hour, reports),
            "direct": _stats(net, direct, mode, transport, slot, rain_mm_per_hour, reports),
        },
    }
