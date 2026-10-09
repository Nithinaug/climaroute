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


def test_rain_due_soon_counts_and_warns():
    from dataclasses import replace
    from datetime import timedelta

    base = weather.parse(SAMPLE)
    dry = replace(base, rain_now=0.0, rain=[0.0] * len(base.rain))
    at = lambda minutes, mm: (dry.now + timedelta(minutes=minutes), mm)  # noqa: E731
    storm_in_45 = replace(dry, soon=(at(15, 0.0), at(45, 20.0)))
    assert weather.effective_rain(storm_in_45) == 20.0  # routed for it already
    assert weather.rain_soon(storm_in_45) == at(45, 20.0)
    storm_in_90 = replace(dry, soon=(at(90, 20.0),))
    assert weather.effective_rain(storm_in_90) == 0.0  # too far off to route for
    assert weather.rain_soon(storm_in_90) == at(90, 20.0)  # but worth a warning
    assert weather.rain_soon(replace(dry, soon=(at(30, 1.0),))) is None  # drizzle
    here = (dry.lat, dry.lon)
    assert weather.trip_rain_soon([dry, storm_in_90, storm_in_45], here, here) == at(45, 20.0)
