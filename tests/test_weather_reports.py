import pytest

from api import reports, weather
from routing import heat_factor
from tests.test_api import SAMPLE


@pytest.mark.parametrize(
    "temp, cloud, expected",
    [(25, 0, 0.0), (30, 0, 0.5), (34, 0, 1.0), (40, 0, 1.5), (34, 100, 0.2)],
)
def test_heat_factor(temp, cloud, expected):
    assert heat_factor(temp, cloud) == pytest.approx(expected)


def test_report_fades_after_first_hour():
    r = {"created_at": 0}
    assert reports.strength(r, 30 * 60) == 1.0
    assert reports.strength(r, 2 * 3600) == pytest.approx(0.5)
    assert reports.strength(r, 3 * 3600) == 0.0


def test_strengths_keep_strongest_report_per_street():
    rs = [{"edge_id": "e1", "created_at": 0}, {"edge_id": "e1", "created_at": 7200}]
    assert reports.strengths(rs, now=7200) == {"e1": 1.0}


def test_trip_uses_worst_rain_near_the_route_and_nearest_heat():
    from dataclasses import replace

    base = weather.parse(SAMPLE)
    dry = replace(base, lat=12.90, lon=77.50, rain_now=0.0, rain=[0.0] * len(base.rain))
    wet = replace(base, lat=13.10, lon=77.70, rain_now=40.0)
    far_wet = replace(base, lat=12.90, lon=77.70, rain_now=99.0)
    ws = [dry, wet, far_wet]
    near_dry = ((12.89, 77.49), (12.91, 77.51))
    rain, w = weather.trip(ws, *near_dry)
    assert rain == weather.effective_rain(dry) and w is dry
    rain, _ = weather.trip(ws, (12.90, 77.50), (13.10, 77.70))  # crosses every cell
    assert rain == 99.0


def test_grid_covers_the_area():
    points, dlat, dlon = weather.grid()
    assert len(points) >= 1 and dlat > 0 and dlon > 0
