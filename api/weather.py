"""Live weather from Open-Meteo (cached).

Rain for flood risk lingers: past hours count with a drainage half-life, so streets stay
risky for a while after a storm. Heat uses the forecast for the departure hour.
"""

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from shared import area

DRAIN_HALF_LIFE_H = 1.5  # water on streets halves every 1.5 h after rain stops
CACHE_SECONDS = 10 * 60  # Open-Meteo refreshes every 15 min
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={area.CENTER['lat']}&longitude={area.CENTER['lon']}"
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
    now: datetime
    rain_now: float  # mm in the current 15-minute interval, as mm/hour
    hours: list[datetime]
    rain: list[float]  # mm per hour
    temperature_c: list[float]
    cloud_cover_pct: list[float]


def parse(payload: dict) -> Weather:
    cur, h = payload["current"], payload["hourly"]
    return Weather(
        now=datetime.fromisoformat(cur["time"]).replace(tzinfo=TZ),
        rain_now=float(cur["precipitation"]) * 3600 / cur.get("interval", 3600),
        hours=[datetime.fromisoformat(t).replace(tzinfo=TZ) for t in h["time"]],
        rain=[float(v or 0) for v in h["precipitation"]],
        temperature_c=[float(v) for v in h["temperature_2m"]],
        cloud_cover_pct=[float(v) for v in h["cloud_cover"]],
    )


def _fetch() -> Weather:
    with urllib.request.urlopen(OPEN_METEO_URL, timeout=5) as resp:
        return parse(json.load(resp))


def current() -> Weather:
    """Cached for 30 min; a stale value beats no value."""
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
