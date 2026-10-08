"""Sun position without pvlib/pandas (so the daily Lambda stays small).

Low-precision NOAA/Astronomical Almanac formulas: ~0.5 deg, plenty for 15-minute shade slots.
"""

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def sun_position(when: datetime, lat: float, lon: float) -> tuple[float, float]:
    """(elevation_deg, azimuth_deg clockwise from north) for a timezone-aware datetime."""
    n = when.timestamp() / 86400 + 2440587.5 - 2451545.0  # days since J2000
    mean_lon = (280.460 + 0.9856474 * n) % 360
    anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
    ecl_lon = math.radians(mean_lon + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * n)

    ra = math.atan2(math.cos(obliquity) * math.sin(ecl_lon), math.cos(ecl_lon))
    dec = math.asin(math.sin(obliquity) * math.sin(ecl_lon))
    gmst_deg = (280.46061837 + 360.98564736629 * n) % 360
    hour_angle = math.radians(gmst_deg + lon) - ra

    phi = math.radians(lat)
    elevation = math.asin(
        math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.sin(hour_angle),
        math.tan(dec) * math.cos(phi) - math.sin(phi) * math.cos(hour_angle),
    )
    return math.degrees(elevation), math.degrees(azimuth) % 360


def slots(
    day: date, lat: float, lon: float, tz: str, start: str, minutes: int, count: int
) -> list[dict]:
    """Sun position for each shade slot of a day (brief section 3, tiles/index.json)."""
    h, m = map(int, start.split(":"))
    first = datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(tz))
    out = []
    for i in range(count):
        elevation, azimuth = sun_position(first + timedelta(minutes=i * minutes), lat, lon)
        out.append(
            {"slot": i, "elevation_deg": round(elevation, 2), "azimuth_deg": round(azimuth, 2)}
        )
    return out
