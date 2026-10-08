"""Turn osmnx street graphs into the brief's graph schema (section 2), minus shade/terrain."""

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

from shared import area

SHADE_DATE = "2026-04-15"  # initial date; the daily pipeline run rewrites it to today
SLOT_START, SLOT_MINUTES, SLOT_COUNT = area.SLOT_START, area.SLOT_MINUTES, area.SLOT_COUNT


def _name(value) -> str | None:
    if isinstance(value, list):
        return " / ".join(str(v) for v in value)
    return None if value is None else str(value)


def edge_id(u: int, v: int, key: int) -> str:
    """Same id for both directions of a street."""
    a, b = sorted((u, v))
    return f"osm-{a}-{b}-{key}"


def to_schema(raw: nx.MultiDiGraph, transport: str) -> nx.MultiDiGraph:
    """raw: unprojected osmnx graph. Returns the largest strongly connected part, in UTM."""
    raw = ox.truncate.largest_component(raw, strongly=True)
    projected = ox.project_graph(raw, to_crs=area.UTM_CRS)

    g = nx.MultiDiGraph(
        crs=area.UTM_CRS,
        area_name=area.NAME,
        transport=transport,
        shade_date=SHADE_DATE,
        slot_start=SLOT_START,
        slot_minutes=SLOT_MINUTES,
        slot_count=SLOT_COUNT,
    )
    for n, d in projected.nodes(data=True):
        g.add_node(n, x=d["x"], y=d["y"], lat=raw.nodes[n]["y"], lon=raw.nodes[n]["x"])

    for u, v, k, d in projected.edges(keys=True, data=True):
        raw_d = raw.edges[u, v, k]
        geom_ll = raw_d.get("geometry") or LineString(
            [(raw.nodes[u]["x"], raw.nodes[u]["y"]), (raw.nodes[v]["x"], raw.nodes[v]["y"])]
        )
        geom = d.get("geometry") or LineString(
            [
                (projected.nodes[u]["x"], projected.nodes[u]["y"]),
                (projected.nodes[v]["x"], projected.nodes[v]["y"]),
            ]
        )
        g.add_edge(
            u,
            v,
            k,
            edge_id=edge_id(u, v, k),
            length=max(float(d["length"]), 0.1),
            geometry=geom,
            lonlat=[[round(x, 6), round(y, 6)] for x, y in geom_ll.coords],
            name=_name(d.get("name")),
        )
    return g
