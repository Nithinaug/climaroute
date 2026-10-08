import pytest
from fastapi.testclient import TestClient

from api import main, rain
from api.main import app, handler
from shade import merge_graph
from tests import dummy_area

client = TestClient(app)
INSIDE_A = {"lat": 12.9352, "lon": 77.6245}
INSIDE_B = {"lat": 12.9279, "lon": 77.6271}


@pytest.fixture(autouse=True)
def fake_graphs(monkeypatch):
    def load(transport):
        g = dummy_area.build_graph(transport)
        shade = {d["edge_id"]: [0.5] * 52 for *_, d in g.edges(data=True)}
        return merge_graph(g, shade, dummy_area.terrain(dummy_area.build_graph("walk")))

    monkeypatch.setattr(main, "graph", load)


def _route(**overrides):
    body = {"origin": INSIDE_A, "destination": INSIDE_B, "mode": "summer", **overrides}
    return client.post("/route", json=body)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_area_shape(local_data):
    body = client.get("/area").json()
    assert len(body["bbox"]) == 4
    assert body["water_points"]["type"] == "FeatureCollection"
    assert body["flood_spots"]["type"] == "FeatureCollection"


def test_summer_route_matches_contract():
    r = _route(departure_time="2026-10-08T14:30:00+05:30")
    assert r.status_code == 200
    body = r.json()
    assert body["safe_route"]["geometry"]["type"] == "LineString"
    assert body["stats"]["safe"]["shaded_pct"] is not None
    assert body["stats"]["safe"]["risk_streets"] is None
    assert body["conditions"] == {
        "mode": "summer",
        "transport": "walk",
        "rain_mm_per_hour": 0.0,
        "slot_time": "14:30",
    }


def test_monsoon_heavy_two_wheeler():
    body = _route(mode="monsoon", transport="two_wheeler", rain_scenario="heavy").json()
    assert body["conditions"]["rain_mm_per_hour"] == rain.HEAVY_RAIN_MM_PER_HOUR
    assert body["stats"]["direct"]["risk_streets"] is not None


def test_out_of_area():
    r = _route(destination={"lat": 13.1, "lon": 77.6})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OUT_OF_AREA"


def test_invalid_request_uses_error_shape():
    r = _route(mode="winter")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_live_rain_unavailable(monkeypatch):
    monkeypatch.setattr(rain, "_cache", {"value": None, "at": 0.0})
    monkeypatch.setattr(rain, "_fetch_live", lambda: (_ for _ in ()).throw(OSError("down")))
    r = _route(mode="monsoon", rain_scenario="live")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "RAIN_UNAVAILABLE"


def test_warmup_event_preloads_graphs():
    assert handler({"warmup": True}, None) == {"warm": True}


def test_live_rain_uses_stale_cache_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(rain, "_cache", {"value": 3.2, "at": 0.0})
    monkeypatch.setattr(rain, "_fetch_live", lambda: (_ for _ in ()).throw(OSError("down")))
    assert rain.rain_mm_per_hour("live") == 3.2
