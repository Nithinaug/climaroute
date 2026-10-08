"""ClimaRoute HTTP API. Runs locally with uvicorn and on Lambda via Mangum."""

import json
import logging
import os
import pickle
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel, Field

from api import reports, weather
from routing import NoRouteError, OutOfAreaError, find_routes, heat_factor, nearest_edge
from shared import area
from shared.storage import read_bytes

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("climaroute.api")
TZ = ZoneInfo(area.TIMEZONE)
FLOOD_SPOTS = json.loads(
    (Path(__file__).parent.parent / "monsoon" / "known_flood_spots.geojson").read_text()
)

app = FastAPI(title="ClimaRoute API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


GRAPH_REFRESH_S = 600  # pick up a new pipeline run (daily or manual) within 10 minutes


def graph(transport: str):
    """Latest graph, cached per container and re-read from storage every 10 minutes."""
    return _load_graph(transport, int(time.time() // GRAPH_REFRESH_S))


@lru_cache(maxsize=4)
def _load_graph(transport: str, _bucket: int):
    return pickle.loads(read_bytes(f"graph/{transport}.pkl"))


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
    rain_scenario: Literal["live", "heavy"] = "live"
    heat_scenario: Literal["live", "heatwave"] = "live"


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
    rain_mm, temperature, cloud, heat = 0.0, None, None, 1.0
    if req.mode == "monsoon" and req.rain_scenario == "heavy":
        rain_mm = weather.HEAVY_RAIN_MM_PER_HOUR
    elif req.mode == "monsoon":
        try:
            rain_mm = weather.effective_rain(weather.current())
        except weather.WeatherUnavailableError:
            raise ApiError(
                503,
                "RAIN_UNAVAILABLE",
                "Live rainfall is unavailable. Try the heavy-rain scenario.",
            ) from None
    elif req.heat_scenario == "heatwave":
        temperature, cloud = weather.HEATWAVE["temperature_c"], weather.HEATWAVE["cloud_cover_pct"]
        heat = heat_factor(temperature, cloud)
    else:
        try:
            temperature, cloud = weather.at(weather.current(), departure)
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
    except OutOfAreaError as e:
        raise ApiError(422, "OUT_OF_AREA", str(e)) from None
    except NoRouteError as e:
        raise ApiError(422, "NO_ROUTE", str(e)) from None
    result["conditions"] = {
        "mode": req.mode,
        "transport": req.transport,
        "rain_mm_per_hour": rain_mm,
        "slot_time": departure.astimezone(TZ).strftime("%H:%M"),
        "temperature_c": temperature,
        "cloud_cover_pct": cloud,
        "heat_factor": heat if req.mode == "summer" else None,
        "shade_date": graph(req.transport).graph.get("shade_date"),
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


_mangum = Mangum(app, lifespan="off")


def handler(event, context):
    if event.get("warmup"):  # EventBridge keep-warm ping; also preloads the graphs
        for transport in ("walk", "two_wheeler"):
            graph(transport)
        return {"warm": True}
    return _mangum(event, context)
