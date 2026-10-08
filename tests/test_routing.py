from datetime import datetime
from zoneinfo import ZoneInfo

import networkx as nx
import pytest
from shapely.geometry import LineString

from routing import NoRouteError, OutOfAreaError, find_routes
from routing.routes import slot_index

TZ = ZoneInfo("Asia/Kolkata")
AFTERNOON = datetime(2026, 4, 15, 15, 0, tzinfo=TZ)  # slot 36
NODES = {  # name: (x, y) in metres; lat/lon derived around Koramangala
    "A": (0, 0),
    "B": (200, 0),
    "C": (100, 60),
}


def _graph(sunny_direct: bool = True, flooded_direct: float = 0.0) -> nx.MultiDiGraph:
    """A--B direct (200 m), or A--C--B detour (~233 m). Direct is sunny/flooded."""
    g = nx.MultiDiGraph(area_name="Test", slot_start="06:00", slot_minutes=15, slot_count=52)
    for n, (x, y) in NODES.items():
        g.add_node(n, x=x, y=y, lat=12.93 + y / 110_574, lon=77.62 + x / 108_500)
    edges = [
        ("A", "B", 0.0 if sunny_direct else 1.0, flooded_direct),
        ("A", "C", 1.0, 0.0),
        ("C", "B", 1.0, 0.0),
    ]
    for u, v, shade, risk in edges:
        for a, b in ((u, v), (v, u)):
            geom = LineString([NODES[a], NODES[b]])
            g.add_edge(
                a,
                b,
                edge_id=f"{u}{v}",
                length=geom.length,
                geometry=geom,
                lonlat=[
                    [g.nodes[a]["lon"], g.nodes[a]["lat"]],
                    [g.nodes[b]["lon"], g.nodes[b]["lat"]],
                ],
                name=None,
                shade=[shade] * 52,
                terrain_risk=risk,
            )
    return g


def _route(g, mode="summer", transport="walk", when=AFTERNOON, rain=0.0):
    a, b = g.nodes["A"], g.nodes["B"]
    return find_routes(g, (a["lat"], a["lon"]), (b["lat"], b["lon"]), mode, transport, when, rain)


def test_summer_prefers_shaded_detour():
    r = _route(_graph())
    assert r["stats"]["safe"]["shaded_pct"] == 100
    assert r["stats"]["direct"]["shaded_pct"] == 0
    assert r["stats"]["safe"]["distance_m"] > r["stats"]["direct"]["distance_m"]
    assert r["safe_route"]["geometry"]["type"] == "LineString"


def test_night_has_no_heat_penalty():
    night = datetime(2026, 4, 15, 22, 0, tzinfo=TZ)
    r = _route(_graph(), when=night)
    assert r["stats"]["safe"]["distance_m"] == r["stats"]["direct"]["distance_m"]


def test_monsoon_blocks_flooded_street_in_heavy_rain():
    r = _route(_graph(flooded_direct=1.0), mode="monsoon", rain=50.0)
    assert r["stats"]["direct"]["risk_streets"] == 1
    assert r["stats"]["safe"]["risk_streets"] == 0
    assert r["stats"]["safe"]["shaded_pct"] is None


def test_no_rain_means_direct_route():
    r = _route(_graph(flooded_direct=1.0), mode="monsoon", rain=0.0)
    assert r["stats"]["safe"]["distance_m"] == r["stats"]["direct"]["distance_m"]


def test_two_wheeler_blocks_at_lower_risk_than_walking():
    g = _graph(flooded_direct=0.85)  # flood_risk ~0.78 at 50 mm/h: blocked for 2W, not walk
    walk = _route(g, mode="monsoon", rain=50.0, transport="walk")
    two = _route(g, mode="monsoon", rain=50.0, transport="two_wheeler")
    assert two["stats"]["safe"]["distance_m"] > walk["stats"]["direct"]["distance_m"]


def test_no_route_when_everything_floods():
    g = _graph(flooded_direct=1.0)
    for _, _, d in g.edges(data=True):
        d["terrain_risk"] = 1.0
    with pytest.raises(NoRouteError):
        _route(g, mode="monsoon", rain=50.0)


def test_out_of_area():
    with pytest.raises(OutOfAreaError):
        find_routes(_graph(), (13.1, 77.6), (12.93, 77.62), "summer", "walk", AFTERNOON, 0.0)


def test_slot_index_uses_local_time():
    g = _graph()
    utc = datetime(2026, 4, 15, 9, 30, tzinfo=ZoneInfo("UTC"))  # 15:00 IST
    assert slot_index(g, utc) == 36
    assert slot_index(g, datetime(2026, 4, 15, 5, 59, tzinfo=TZ)) is None
