"""Rainfall in mm/hour: live from Open-Meteo (cached), or the heavy-rain demo scenario."""

import json
import logging
import time
import urllib.request

from shared import area

HEAVY_RAIN_MM_PER_HOUR = 50.0
CACHE_SECONDS = 30 * 60
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={area.CENTER['lat']}&longitude={area.CENTER['lon']}&current=precipitation"
)

log = logging.getLogger(__name__)
_cache: dict = {"value": None, "at": 0.0}


class RainUnavailableError(Exception):
    pass


def _fetch_live() -> float:
    with urllib.request.urlopen(OPEN_METEO_URL, timeout=5) as resp:
        return float(json.load(resp)["current"]["precipitation"])


def rain_mm_per_hour(scenario: str) -> float:
    if scenario == "heavy":
        return HEAVY_RAIN_MM_PER_HOUR
    fresh = time.monotonic() - _cache["at"] < CACHE_SECONDS
    if _cache["value"] is not None and fresh:
        return _cache["value"]
    try:
        _cache["value"], _cache["at"] = _fetch_live(), time.monotonic()
    except Exception as e:
        log.warning("open-meteo fetch failed: %s", e)
        if _cache["value"] is None:  # stale value beats no value
            raise RainUnavailableError from e
    return _cache["value"]
