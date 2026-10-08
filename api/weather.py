"""Live weather from Open-Meteo (cached), on a grid of points across the area.

Rain is local (a cloudburst in one part of the city), so each trip uses the grid points
it passes near. Rain for flood risk lingers: past hours count with a drainage half-life,
so streets stay risky for a while after a storm. Heat uses the forecast for the departure hour.
"""

import json
import logging
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from shared import area

DRAIN_HALF_LIFE_H = 1.5  # water on streets halves every 1.5 h after rain stops
CACHE_SECONDS = 10 * 60  # Open-Meteo refreshes every 15 min
GRID_SPACING_KM = 9.0  # rain cells are several km; Open-Meteo's own grid is ~1-2 km


def grid() -> tuple[list[tuple[float, float]], float, float]:
    """Cell centres (lat, lon) covering the area, and the cell size in degrees."""
    w, s, e, n = area.BBOX
    km_lon = 111.32 * math.cos(math.radians((s + n) / 2))
    nx = max(1, round((e - w) * km_lon / GRID_SPACING_KM))
    ny = max(1, round((n - s) * 110.57 / GRID_SPACING_KM))
    dlat, dlon = (n - s) / ny, (e - w) / nx
    points = [
        (round(s + (j + 0.5) * dlat, 4), round(w + (i + 0.5) * dlon, 4))
        for j in range(ny)
        for i in range(nx)
    ]
    return points, dlat, dlon


POINTS, CELL_LAT, CELL_LON = grid()
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={','.join(str(p[0]) for p in POINTS)}"
    f"&longitude={','.join(str(p[1]) for p in POINTS)}"
    "&current=precipitation,temperature_2m,cloud_cover"
    "&hourly=precipitation,temperature_2m,cloud_cover"
    "&past_hours=6&forecast_hours=24&timezone=Asia%2FKolkata"
)

log = logging.getLogger(__name__)
TZ = ZoneInfo(area.TIMEZONE)
_cache: dict = {"value": None, "at": 0.0}


class WeatherUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class Weather:
    lat: float
    lon: float
    now: datetime
    rain_now: float  # mm in the current 15-minute interval, as mm/hour
    hours: list[datetime]
    rain: list[float]  # mm per hour
    temperature_c: list[float]
    cloud_cover_pct: list[float]


def parse(payload: dict, point: tuple[float, float] | None = None) -> Weather:
    cur, h = payload["current"], payload["hourly"]
    lat, lon = point or (area.CENTER["lat"], area.CENTER["lon"])
    return Weather(
        lat=lat,
        lon=lon,
        now=datetime.fromisoformat(cur["time"]).replace(tzinfo=TZ),
        rain_now=float(cur["precipitation"]) * 3600 / cur.get("interval", 3600),
        hours=[datetime.fromisoformat(t).replace(tzinfo=TZ) for t in h["time"]],
        rain=[float(v or 0) for v in h["precipitation"]],
        temperature_c=[float(v) for v in h["temperature_2m"]],
        cloud_cover_pct=[float(v) for v in h["cloud_cover"]],
    )


def _fetch() -> list[Weather]:
    with urllib.request.urlopen(OPEN_METEO_URL, timeout=5) as resp:
        payload = json.load(resp)
    payloads = payload if isinstance(payload, list) else [payload]  # one location -> object
    return [parse(p, point) for p, point in zip(payloads, POINTS, strict=True)]


def current() -> list[Weather]:
    """One Weather per grid point. Cached; a stale value beats no value."""
    if _cache["value"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    try:
        _cache["value"], _cache["at"] = _fetch(), time.monotonic()
    except Exception as e:
        log.warning("open-meteo fetch failed: %s", e)
        if _cache["value"] is None:
            raise WeatherUnavailableError from e
    return _cache["value"]


def effective_rain(w: Weather) -> float:
    """mm/hour that still matters for flooding: current rain, or past rain decayed."""
    lingering = [
        mm * 0.5 ** ((w.now - t).total_seconds() / 3600 / DRAIN_HALF_LIFE_H)
        for t, mm in zip(w.hours, w.rain, strict=True)
        if t <= w.now
    ]
    return round(max([w.rain_now, *lingering]), 2)


def at(w: Weather, when: datetime) -> tuple[float, float]:
    """(temperature_c, cloud_cover_pct) for the forecast hour nearest to `when`."""
    i = min(range(len(w.hours)), key=lambda k: abs((w.hours[k] - when).total_seconds()))
    return w.temperature_c[i], w.cloud_cover_pct[i]


def nearest(ws: list[Weather], lat: float, lon: float) -> Weather:
    return min(ws, key=lambda w: (w.lat - lat) ** 2 + (w.lon - lon) ** 2)


def trip(
    ws: list[Weather], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, Weather]:
    """(rain mm/h for flood risk: the worst grid cell the trip's box touches,
    weather nearest the trip's middle for heat). a, b are (lat, lon)."""
    lo_lat, hi_lat = sorted((a[0], b[0]))
    lo_lon, hi_lon = sorted((a[1], b[1]))
    near = [
        w
        for w in ws
        if lo_lat - CELL_LAT / 2 <= w.lat <= hi_lat + CELL_LAT / 2
        and lo_lon - CELL_LON / 2 <= w.lon <= hi_lon + CELL_LON / 2
    ]
    middle = nearest(ws, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return max(effective_rain(w) for w in near or [middle]), middle
