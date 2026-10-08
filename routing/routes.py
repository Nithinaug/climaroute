"""Safe vs direct route search (brief section 5)."""

import math
from collections.abc import Callable
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from monsoon.rain import rain_factor
from routing import config
from routing.errors import NoRouteError, OutOfAreaError
from shared.area import TIMEZONE

EdgeCost = Callable[[dict], float | None]


@cache
def _node_index(graph: nx.MultiDiGraph) -> tuple[cKDTree, list, float]:
    """KD-tree over nodes in local metres (equirectangular around the area)."""
    nodes = list(graph.nodes)
    lat0 = float(np.mean([graph.nodes[n]["lat"] for n in nodes]))
    kx = 111_320 * math.cos(math.radians(lat0))
    pts = [(graph.nodes[n]["lon"] * kx, graph.nodes[n]["lat"] * 110_574) for n in nodes]
    return cKDTree(pts), nodes, kx


def _nearest(graph: nx.MultiDiGraph, lat: float, lon: float, label: str):
    tree, nodes, kx = _node_index(graph)
    dist, i = tree.query((lon * kx, lat * 110_574))
    if dist > config.SNAP_MAX_M:
        raise OutOfAreaError(f"{label} is outside the covered area ({graph.graph['area_name']}).")
    return nodes[i]


def slot_index(graph: nx.MultiDiGraph, departure: datetime) -> int | None:
    """Shade slot for the departure's local time, or None at night."""
    departure = departure.astimezone(ZoneInfo(TIMEZONE))
    h, m = map(int, graph.graph["slot_start"].split(":"))
    minutes = departure.hour * 60 + departure.minute - (h * 60 + m)
    slot = minutes // graph.graph["slot_minutes"]
    return slot if 0 <= slot < graph.graph["slot_count"] else None


def edge_cost(mode: str, transport: str, slot: int | None, rain_mm: float) -> EdgeCost:
    """Cost of one edge's attributes; None means the edge is blocked."""
    if mode == "summer":
        alpha = config.ALPHA[transport] * config.HEAT_FACTOR

        def summer(d: dict) -> float:
            shade = 1.0 if slot is None else d["shade"][slot]
            return d["length"] * (1 + alpha * (1 - shade))

        return summer

    beta, block, rf = (
        config.BETA[transport],
        config.BLOCK_THRESHOLD[transport],
        rain_factor(rain_mm),
    )

    def monsoon(d: dict) -> float | None:
        risk = d["terrain_risk"] * rf
        return None if risk > block else d["length"] * (1 + beta * risk)

    return monsoon


def _path(graph, source, target, cost: EdgeCost) -> tuple[list, list[dict]]:
    """A* path plus the chosen edge attributes between consecutive nodes."""

    def weight(_u, _v, keyed: dict) -> float | None:
        costs = [c for c in (cost(d) for d in keyed.values()) if c is not None]
        return min(costs) if costs else None

    def heuristic(a, b) -> float:
        na, nb = graph.nodes[a], graph.nodes[b]
        return math.hypot(na["x"] - nb["x"], na["y"] - nb["y"])

    try:
        nodes = nx.astar_path(graph, source, target, heuristic=heuristic, weight=weight)
    except nx.NetworkXNoPath:
        raise NoRouteError("No safe route found between these points right now.") from None
    edges = []
    for u, v in zip(nodes, nodes[1:], strict=False):
        usable = [d for d in graph[u][v].values() if cost(d) is not None]
        edges.append(min(usable, key=cost))
    return nodes, edges


def _feature(edges: list[dict], graph, start) -> dict:
    coords = [[graph.nodes[start]["lon"], graph.nodes[start]["lat"]]]
    for d in edges:
        coords.extend(d["lonlat"][1:])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {},
    }


def _stats(edges: list[dict], mode: str, transport: str, slot, rain_mm: float) -> dict:
    distance = sum(d["length"] for d in edges)
    stats = {
        "distance_m": round(distance),
        "duration_min": round(distance / config.SPEED_M_PER_S[transport] / 60, 1),
        "shaded_pct": None,
        "risk_streets": None,
    }
    if mode == "summer":
        shaded = sum(d["length"] * (1.0 if slot is None else d["shade"][slot]) for d in edges)
        stats["shaded_pct"] = round(100 * shaded / distance) if distance else 0
    else:
        rf = rain_factor(rain_mm)
        risky = {
            d["edge_id"] for d in edges if d["terrain_risk"] * rf >= config.RISK_STREET_THRESHOLD
        }
        stats["risk_streets"] = len(risky)
    return stats


def find_routes(
    graph: nx.MultiDiGraph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str,
    transport: str,
    departure_time: datetime,
    rain_mm_per_hour: float,
) -> dict:
    source = _nearest(graph, *origin, "Start")
    target = _nearest(graph, *destination, "Destination")
    if source == target:
        raise NoRouteError("Start and destination are the same place.")
    slot = slot_index(graph, departure_time)

    safe_cost = edge_cost(mode, transport, slot, rain_mm_per_hour)
    _, safe_edges = _path(graph, source, target, safe_cost)
    _, direct_edges = _path(graph, source, target, lambda d: d["length"])
    return {
        "safe_route": _feature(safe_edges, graph, source),
        "direct_route": _feature(direct_edges, graph, source),
        "stats": {
            "safe": _stats(safe_edges, mode, transport, slot, rain_mm_per_hour),
            "direct": _stats(direct_edges, mode, transport, slot, rain_mm_per_hour),
        },
    }
