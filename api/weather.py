"""Live weather from Open-Meteo (cached), on a grid of points across the area.

Rain is local (a cloudburst in one part of the city), so each trip uses the grid points
it passes near. Rain for flood risk lingers: past hours count with a drainage half-life,
so streets stay risky for a while after a storm. Rain forecast for the next hour counts too,
so a trip isn't routed into a downpour that's about to start. Heat uses the forecast for the
departure hour.
"""

import json
import logging
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared import area

DRAIN_HALF_LIFE_H = 1.5  # water on streets halves every 1.5 h after rain stops
CACHE_SECONDS = 10 * 60  # Open-Meteo refreshes every 15 min
GRID_SPACING_KM = 9.0  # rain cells are several km; Open-Meteo's own grid is ~1-2 km
SOON_MINUTES = 60  # forecast rain this close counts as rain now
WARN_SOON_MINUTES = 120  # how far ahead to warn about rain
WARN_MM_PER_HOUR = 2.5  # "moderate" rain and up is worth a warning


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
    "&current=precipitation,temperature_2m,cloud_cover,apparent_temperature"
    "&hourly=precipitation,temperature_2m,cloud_cover,apparent_temperature"
    # ponytail: outside Europe/North America Open-Meteo's 15-min values are interpolated from
    # hourly models, so timing is approximate; a radar nowcast would be the upgrade.
    "&minutely_15=precipitation&forecast_minutely_15=8"
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
    soon: tuple[tuple[datetime, float], ...] = ()  # (15-min slot start, mm/hour), next 2 h
    feels_like_c: tuple[float, ...] = ()  # hourly "apparent" temperature (heat + humidity)
    temp_now: float | None = None  # current reading (the hourly lists are forecasts)
    feels_now: float | None = None


def parse(payload: dict, point: tuple[float, float] | None = None) -> Weather:
    cur, h, m = payload["current"], payload["hourly"], payload.get("minutely_15", {})
    lat, lon = point or (area.CENTER["lat"], area.CENTER["lon"])
    return Weather(
        lat=lat,
        lon=lon,
        now=datetime.fromisoformat(cur["time"]).replace(tzinfo=TZ),
        rain_now=float(cur["precipitation"]) * 3600 / cur.get("interval", 3600),
        temp_now=cur.get("temperature_2m"),
        feels_now=cur.get("apparent_temperature", cur.get("temperature_2m")),
        hours=[datetime.fromisoformat(t).replace(tzinfo=TZ) for t in h["time"]],
        rain=[float(v or 0) for v in h["precipitation"]],
        temperature_c=[float(v) for v in h["temperature_2m"]],
        cloud_cover_pct=[float(v) for v in h["cloud_cover"]],
        feels_like_c=tuple(float(v) for v in h.get("apparent_temperature", h["temperature_2m"])),
        soon=tuple(
            (datetime.fromisoformat(t).replace(tzinfo=TZ), float(v or 0) * 4)  # mm/15 min -> mm/h
            for t, v in zip(m.get("time", []), m.get("precipitation", []), strict=True)
        ),
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


def _upcoming(w: Weather, minutes: int) -> list[tuple[datetime, float]]:
    return [(t, mm) for t, mm in w.soon if w.now < t <= w.now + timedelta(minutes=minutes)]


def effective_rain(w: Weather) -> float:
    """mm/hour that matters for flooding: current rain, past rain decayed, or rain due
    within the hour."""
    lingering = [
        mm * 0.5 ** ((w.now - t).total_seconds() / 3600 / DRAIN_HALF_LIFE_H)
        for t, mm in zip(w.hours, w.rain, strict=True)
        if t <= w.now
    ]
    coming = [mm for _, mm in _upcoming(w, SOON_MINUTES)]
    return round(max([w.rain_now, *lingering, *coming]), 2)


def rain_soon(w: Weather) -> tuple[datetime, float] | None:
    """When rain worth warning about starts in the next 2 h (and how heavy), if it isn't
    raining that hard already."""
    if w.rain_now >= WARN_MM_PER_HOUR:
        return None
    hits = [(t, mm) for t, mm in _upcoming(w, WARN_SOON_MINUTES) if mm >= WARN_MM_PER_HOUR]
    return hits[0] if hits else None


def _hour(w: Weather, when: datetime) -> int:
    return min(range(len(w.hours)), key=lambda k: abs((w.hours[k] - when).total_seconds()))


def at(w: Weather, when: datetime) -> tuple[float, float]:
    """(temperature_c, cloud_cover_pct) for the forecast hour nearest to `when`."""
    i = _hour(w, when)
    return w.temperature_c[i], w.cloud_cover_pct[i]


def feels_like(w: Weather, when: datetime) -> float:
    """How hot it feels (temperature with humidity) in the forecast hour nearest to `when`."""
    i = _hour(w, when)
    return (w.feels_like_c or w.temperature_c)[i]


def nearest(ws: list[Weather], lat: float, lon: float) -> Weather:
    return min(ws, key=lambda w: (w.lat - lat) ** 2 + (w.lon - lon) ** 2)


def _near(ws: list[Weather], a: tuple[float, float], b: tuple[float, float]) -> list[Weather]:
    """Grid cells the trip's box touches (at least the one nearest its middle)."""
    lo_lat, hi_lat = sorted((a[0], b[0]))
    lo_lon, hi_lon = sorted((a[1], b[1]))
    near = [
        w
        for w in ws
        if lo_lat - CELL_LAT / 2 <= w.lat <= hi_lat + CELL_LAT / 2
        and lo_lon - CELL_LON / 2 <= w.lon <= hi_lon + CELL_LON / 2
    ]
    return near or [nearest(ws, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)]


def trip(
    ws: list[Weather], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, Weather]:
    """(rain mm/h for flood risk: the worst grid cell the trip's box touches,
    weather nearest the trip's middle for heat). a, b are (lat, lon)."""
    middle = nearest(ws, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return max(effective_rain(w) for w in _near(ws, a, b)), middle


def trip_rain_soon(
    ws: list[Weather], a: tuple[float, float], b: tuple[float, float]
) -> tuple[datetime, float] | None:
    """Earliest warning-worthy rain due along the trip (heaviest if two start together)."""
    hits = [r for w in _near(ws, a, b) if (r := rain_soon(w))]
    return min(hits, key=lambda r: (r[0], -r[1])) if hits else None
