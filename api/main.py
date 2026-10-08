"""ClimaRoute HTTP API. Runs locally with uvicorn and on Lambda via Mangum."""

import json
import logging
import os
import pickle
import time
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import BaseModel, Field

from api import rain
from routing import NoRouteError, OutOfAreaError, find_routes
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


@cache
def graph(transport: str):
    """Loaded once per Lambda container (cold start or warm-up ping)."""
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
    rain_mm = 0.0
    if req.mode == "monsoon":
        try:
            rain_mm = rain.rain_mm_per_hour(req.rain_scenario)
        except rain.RainUnavailableError:
            raise ApiError(
                503,
                "RAIN_UNAVAILABLE",
                "Live rainfall is unavailable. Try the heavy-rain scenario.",
            ) from None

    try:
        result = find_routes(
            graph(req.transport),
            (req.origin.lat, req.origin.lon),
            (req.destination.lat, req.destination.lon),
            req.mode,
            req.transport,
            departure,
            rain_mm,
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


_mangum = Mangum(app, lifespan="off")


def handler(event, context):
    if event.get("warmup"):  # EventBridge keep-warm ping; also preloads the graphs
        for transport in ("walk", "two_wheeler"):
            graph(transport)
        return {"warm": True}
    return _mangum(event, context)
