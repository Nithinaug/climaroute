"""ClimaRoute HTTP API. Runs locally with uvicorn and on Lambda via Mangum."""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel, Field

from api import places, reports, weather
from routing import (
    NoRouteError,
    NotNearStreetError,
    OutOfAreaError,
    find_routes,
    heat_factor,
    near_street,
    nearest_edge,
)
from routing.net import Net
from shared import area
from shared.storage import read_bytes
from shared.storage import version as storage_version

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("climaroute.api")
TZ = ZoneInfo(area.TIMEZONE)
_ALL_SPOTS = json.loads(
    (Path(__file__).parent.parent / "monsoon" / "known_flood_spots.geojson").read_text()
)
FLOOD_SPOTS = {  # this city's spots only
    "type": "FeatureCollection",
    "features": [
        f for f in _ALL_SPOTS["features"] if area.contains(*reversed(f["geometry"]["coordinates"]))
    ],
}
SPOT_POINTS = [tuple(reversed(f["geometry"]["coordinates"])) for f in FLOOD_SPOTS["features"]]
FLOOD_SPOT_RADIUS_M = 60.0
BEST_TIME_STEP_MIN, BEST_TIME_STEPS = 30, 7  # now .. +3 h

app = FastAPI(title="ClimaRoute API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


GRAPH_CHECK_S = 60  # a new pipeline run is picked up within a minute


def graph(transport: str):
    """Latest graph. Its stored version is checked every GRAPH_CHECK_S; the (slow) download
    happens only when a pipeline run has actually written a new one."""
    key = f"graph/{transport}.npz"
    return _load_graph(transport, _graph_version(key, int(time.time() // GRAPH_CHECK_S)))


@lru_cache(maxsize=8)
def _graph_version(key: str, _bucket: int) -> str:
    return storage_version(key)


@lru_cache(maxsize=4)
def _load_graph(transport: str, _version: str):
    net = Net.from_bytes(read_bytes(f"graph/{transport}.npz"))
    # Applied at load, so adding spots only needs a redeploy, not a rebuild of the city.
    net.mark_flood_spots(SPOT_POINTS, FLOOD_SPOT_RADIUS_M)
    return net


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return _error(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, e: RequestValidationError):
    first = e.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p != "body")
    return _error(422, "INVALID_REQUEST", f"Invalid {field or 'request'}: {first['msg']}.")


@app.exception_handler(Exception)
async def _internal(_: Request, e: Exception):
    log.exception("unhandled error")
    return _error(500, "INTERNAL", "Something went wrong. Please try again.")


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: Point
    destination: Point
    mode: Literal["summer", "monsoon"]
    transport: Literal["walk", "two_wheeler"] = "walk"
    departure_time: datetime | None = None
    # Monsoon demo on a dry day: use this rainfall instead of the live value.
    simulate_rain_mm_per_hour: float | None = Field(default=None, ge=0, le=200)


class ReportRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/area")
def get_area():
    return {
        "name": area.NAME,
        "bbox": list(area.BBOX),
        "center": area.CENTER,
        "water_points": area.water_points(),
        "flood_spots": FLOOD_SPOTS,
    }


@app.get("/now")
def now(at: datetime | None = None):
    """Weather at the city centre for the panel's temperature chip: the current reading, or
    with `at` (a departure time) the forecast for that hour."""
    try:
        w = weather.nearest(weather.current(), area.CENTER["lat"], area.CENTER["lon"])
    except weather.WeatherUnavailableError:
        raise ApiError(
            503, "WEATHER_UNAVAILABLE", "Live weather is unavailable right now."
        ) from None
    if at is not None:
        at = at.replace(tzinfo=TZ) if at.tzinfo is None else at
        return {
            "temperature_c": weather.at(w, at)[0],
            "feels_like_c": weather.feels_like(w, at),
            "rain_mm_per_hour": None,
        }
    return {
        "temperature_c": w.temp_now,
        "feels_like_c": w.feels_now,
        "rain_mm_per_hour": round(w.rain_now, 1),
    }


@app.get("/search")
def search(q: str = Query(min_length=2, max_length=100)):
    try:
        return {"results": places.search(q.strip())}
    except places.SearchUnavailableError:
        raise ApiError(
            503, "SEARCH_UNAVAILABLE", "Place search isn't available right now."
        ) from None


@app.get("/place")
def place(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    transport: Literal["walk", "two_wheeler"] = "walk",
):
    """Street name for a tapped point, and whether a route can start or end there."""
    near = area.contains(lat, lon) and near_street(graph(transport), lat, lon)
    try:
        name = places.name_at(round(lat, 4), round(lon, 4))
    except places.SearchUnavailableError:
        name = None  # the street check still matters without a name
    return {"name": name, "near_street": near}


@app.post("/route")
def route(req: RouteRequest):
    started = time.perf_counter()
    for label, p in (("Start", req.origin), ("Destination", req.destination)):
        if not area.contains(p.lat, p.lon):
            raise ApiError(
                422, "OUT_OF_AREA", f"{label} is outside the covered area ({area.NAME})."
            )

    departure = req.departure_time or datetime.now(TZ)
    departure = departure.replace(tzinfo=TZ) if departure.tzinfo is None else departure
    rain_mm, temperature, cloud, heat, soon, feels, uv = 0.0, None, None, 1.0, None, None, None
    trip_a, trip_b = (req.origin.lat, req.origin.lon), (req.destination.lat, req.destination.lon)
    if req.mode == "monsoon" and req.simulate_rain_mm_per_hour is not None:
        rain_mm = req.simulate_rain_mm_per_hour
    elif req.mode == "monsoon":
        try:
            # A set departure time uses the rain forecast for then; "now" also warns of rain
            # due in the next 2 h.
            when = req.departure_time and departure
            rain_mm, _ = weather.trip(weather.current(), trip_a, trip_b, when)
            if when is None:
                soon = weather.trip_rain_soon(weather.current(), trip_a, trip_b)
        except weather.WeatherUnavailableError:
            raise ApiError(
                503, "RAIN_UNAVAILABLE", "Live rainfall is unavailable. Please try again shortly."
            ) from None
    else:
        try:
            middle = weather.trip(weather.current(), trip_a, trip_b)[1]
            temperature, cloud = weather.at(middle, departure)
            feels = round(weather.feels_like(middle, departure), 1)
            uv = weather.uv_at(middle, departure)
            heat = heat_factor(temperature, cloud)
        except weather.WeatherUnavailableError:
            log.warning("weather unavailable; using default heat factor")

    active_reports = reports.active()
    try:
        result = find_routes(
            graph(req.transport),
            (req.origin.lat, req.origin.lon),
            (req.destination.lat, req.destination.lon),
            req.mode,
            req.transport,
            departure,
            rain_mm,
            heat_factor=heat,
            reports=reports.strengths(active_reports),
        )
    except NotNearStreetError as e:
        raise ApiError(422, f"{e.end.upper()}_NOT_NEAR_STREET", str(e)) from None
    except OutOfAreaError as e:
        raise ApiError(422, "OUT_OF_AREA", str(e)) from None
    except NoRouteError as e:
        raise ApiError(422, "NO_ROUTE", str(e)) from None
    result["conditions"] = {
        "mode": req.mode,
        "transport": req.transport,
        "rain_mm_per_hour": rain_mm,
        "rain_simulated": req.mode == "monsoon" and req.simulate_rain_mm_per_hour is not None,
        # Heavier rain due in the next 2 h along the trip (already counted if within the hour).
        "rain_soon": {
            "at": soon[0].strftime("%H:%M"),
            "mm_per_hour": round(soon[1], 1),
            "counted": soon[0] <= datetime.now(TZ) + timedelta(minutes=weather.SOON_MINUTES),
        }
        if soon
        else None,
        "slot_time": departure.astimezone(TZ).strftime("%H:%M"),
        "temperature_c": temperature,
        "feels_like_c": feels,  # temperature with humidity, for heat warnings
        "uv_index": uv,
        "cloud_cover_pct": cloud,
        "heat_factor": heat if req.mode == "summer" else None,
        "shade_date": graph(req.transport).meta.get("shade_date"),
        "active_reports": len(active_reports),
    }
    log.info(
        json.dumps(
            {
                "event": "route",
                "mode": req.mode,
                "transport": req.transport,
                "ms": round((time.perf_counter() - started) * 1000),
            }
        )
    )
    return result


@app.post("/best-time")
def best_time(req: RouteRequest):
    """The safe route if you leave now or in the next 3 hours. Summer: least sun exposure.
    Monsoon: fewest flood-risk streets, then least rain (ties go to the earliest time)."""
    start = req.departure_time or datetime.now(TZ)
    start = start.replace(tzinfo=TZ) if start.tzinfo is None else start
    options = []
    for i in range(BEST_TIME_STEPS):
        when = start + timedelta(minutes=i * BEST_TIME_STEP_MIN)
        try:
            body = route(req.model_copy(update={"departure_time": when}))
        except ApiError as e:
            if e.code != "NO_ROUTE":  # flooded shut at that time: just not an option
                raise
            continue
        safe, c = body["stats"]["safe"], body["conditions"]
        option = {"time": c["slot_time"]}
        if req.mode == "summer":
            option |= {
                "shaded_pct": safe["shaded_pct"],
                "temperature_c": c["temperature_c"],
                "heat_factor": c["heat_factor"],
                # Sun exposure that actually matters: unshaded share x how hot it is.
                "exposure": round((100 - safe["shaded_pct"]) / 100 * (c["heat_factor"] or 0), 3),
            }
        else:
            option |= {
                "risk_streets": safe["risk_streets"],
                "rain_mm_per_hour": c["rain_mm_per_hour"],
                "exposure": (safe["risk_streets"], c["rain_mm_per_hour"]),
            }
        options.append(option)
    if not options:
        raise ApiError(422, "NO_ROUTE", "No safe route found in the next 3 hours.")
    return {"options": options, "best": min(options, key=lambda o: o["exposure"])}


def _report_feature(r: dict, now: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        "properties": {
            "age_min": round((now - r["created_at"]) / 60),
            "strength": round(reports.strength(r, now), 2),
        },
    }


@app.get("/reports")
def list_reports():
    now = time.time()
    return {
        "type": "FeatureCollection",
        "features": [_report_feature(r, now) for r in reports.active(now)],
    }


@app.post("/reports", status_code=201)
def add_report(req: ReportRequest):
    if not area.contains(req.lat, req.lon):
        raise ApiError(422, "OUT_OF_AREA", f"That spot is outside the covered area ({area.NAME}).")
    try:
        edge_id = nearest_edge(graph("walk"), req.lat, req.lon)
    except OutOfAreaError as e:
        raise ApiError(422, "NOT_ON_STREET", str(e)) from None
    report = reports.add(edge_id, req.lat, req.lon)
    log.info(json.dumps({"event": "flood_report", "edge_id": edge_id}))
    return _report_feature(report, time.time())


WARMUP_HOLD_S = 0.5
_mangum = Mangum(app, lifespan="off")


def handler(event, context):
    if event.get("warmup"):  # EventBridge keep-warm ping; also preloads the graphs
        started = time.perf_counter()
        for transport in ("walk", "two_wheeler"):
            graph(transport)
        # Already warm: stay busy briefly so the rule's other ping (sent at the same moment)
        # lands on a second instance and keeps that one warm too.
        time.sleep(max(0.0, WARMUP_HOLD_S - (time.perf_counter() - started)))
        return {"warm": True}
    return _mangum(event, context)
