from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from shade.sun import slots, sun_position

TZ = ZoneInfo("Asia/Kolkata")
LAT, LON = 12.935, 77.624


# Reference values from pvlib.solarposition (SPA) for Koramangala.
@pytest.mark.parametrize(
    "when, elevation, azimuth",
    [
        ("2026-04-15 09:00", 41.04, 88.26),
        ("2026-04-15 12:15", 86.66, 160.29),
        ("2026-04-15 16:00", 35.97, 272.87),
        ("2026-10-08 07:00", 11.46, 98.80),
        ("2026-10-08 16:30", 22.02, 257.98),
        ("2026-12-21 12:00", 53.38, 173.28),
    ],
)
def test_matches_pvlib(when, elevation, azimuth):
    t = datetime.fromisoformat(when).replace(tzinfo=TZ)
    e, a = sun_position(t, LAT, LON)
    assert e == pytest.approx(elevation, abs=0.5)
    # Azimuth is ill-conditioned with the sun near overhead; looser there.
    assert a == pytest.approx(azimuth, abs=3.0 if elevation > 80 else 0.7)


def test_slots_cover_the_day():
    s = slots(date(2026, 10, 8), LAT, LON, "Asia/Kolkata", "06:00", 15, 52)
    assert len(s) == 52 and s[0]["slot"] == 0
    assert s[0]["elevation_deg"] < 10 < max(x["elevation_deg"] for x in s)
