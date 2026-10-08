import pytest
from fastapi.testclient import TestClient

from api import main, reports, weather
from api.main import app, handler
from routing.net import from_graph
from shade import merge_graph
from tests import dummy_area

client = TestClient(app)
INSIDE_A = {"lat": 12.9352, "lon": 77.6245}
INSIDE_B = {"lat": 12.9300, "lon": 77.6271}
SAMPLE = {
    "current": {
        "time": "2026-10-08T15:00",
        "interval": 900,
        "precipitation": 0.0,
        "temperature_2m": 33.0,
        "cloud_cover": 10,
    },
    "hourly": {
        "time": ["2026-10-08T13:00", "2026-10-08T14:00", "2026-10-08T15:00", "2026-10-08T16:00"],
        "precipitation": [0.0, 30.0, 0.0, 0.0],
        "temperature_2m": [32.0, 33.0, 33.0, 31.0],
        "cloud_cover": [5, 10, 10, 20],
    },
}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    def load(transport):
        g = dummy_area.build_graph(transport)
        shade = {d["edge_id"]: [0.5] * 52 for *_, d in g.edges(data=True)}
        return merge_graph(from_graph(g), shade, dummy_area.terrain(dummy_area.build_graph("walk")))

    monkeypatch.setattr(main, "graph", load)
    monkeypatch.setattr(weather, "_cache", {"value": weather.parse(SAMPLE), "at": 1e18})
    monkeypatch.delenv("REPORTS_TABLE", raising=False)
    monkeypatch.setattr(reports, "_local", [])


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


def test_summer_route_uses_forecast_heat():
    r = _route(departure_time="2026-10-08T16:00:00+05:30")
    assert r.status_code == 200
    body = r.json()
    assert body["safe_route"]["geometry"]["type"] == "LineString"
    assert body["stats"]["safe"]["risk_streets"] is None
    c = body["conditions"]
    assert c["slot_time"] == "16:00" and c["temperature_c"] == 31.0  # 16:00 forecast
    assert c["heat_factor"] == pytest.approx(0.525, abs=0.01)  # 31 C, 20% cloud


def test_monsoon_live_uses_lingering_rain():
    body = _route(mode="monsoon").json()
    # 30 mm at 14:00, one hour before "now" (15:00), half-life 1.5 h -> ~18.9 mm/h
    assert body["conditions"]["rain_mm_per_hour"] == pytest.approx(18.9, abs=0.1)


def test_monsoon_two_wheeler():
    body = _route(mode="monsoon", transport="two_wheeler").json()
    assert body["conditions"]["transport"] == "two_wheeler"
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
    monkeypatch.setattr(weather, "_cache", {"value": None, "at": 0.0})
    monkeypatch.setattr(weather, "_fetch", lambda: (_ for _ in ()).throw(OSError("down")))
    r = _route(mode="monsoon")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "RAIN_UNAVAILABLE"


def test_summer_survives_weather_outage(monkeypatch):
    monkeypatch.setattr(weather, "_cache", {"value": None, "at": 0.0})
    monkeypatch.setattr(weather, "_fetch", lambda: (_ for _ in ()).throw(OSError("down")))
    r = _route()
    assert r.status_code == 200 and r.json()["conditions"]["heat_factor"] == 1.0


def test_flood_report_is_listed_and_avoided():
    before = _route(mode="monsoon").json()
    lon, lat = before["direct_route"]["geometry"]["coordinates"][1]
    r = client.post("/reports", json={"lat": lat, "lon": lon})
    assert r.status_code == 201 and r.json()["properties"]["strength"] == 1.0
    assert len(client.get("/reports").json()["features"]) == 1

    after = _route(mode="monsoon").json()
    assert after["conditions"]["active_reports"] == 1
    assert after["stats"]["safe"]["reported_streets"] == 0


def test_flood_report_must_be_on_a_street():
    r = client.post("/reports", json={"lat": 12.9443, "lon": 77.6355})  # inside bbox, off grid
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_ON_STREET"


def test_warmup_event_preloads_graphs():
    assert handler({"warmup": True}, None) == {"warm": True}
