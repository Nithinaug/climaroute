"""Crowd flood reports. DynamoDB (REPORTS_TABLE) when deployed, in memory for local dev.

A report fully blocks its street for FULL_BLOCK_H, then fades to nothing at EXPIRE_H.
DynamoDB TTL deletes old items (with some lag), so reads also filter by expiry.
"""

import os
import time
import uuid
from functools import cache

from shared import area

FULL_BLOCK_H, EXPIRE_H = 1.0, 3.0
AREA_KEY = area.NAME
_local: list[dict] = []


def strength(report: dict, now: float) -> float:
    """1.0 while fresh, then linear fade to 0 at expiry."""
    age_h = (now - report["created_at"]) / 3600
    if age_h <= FULL_BLOCK_H:
        return 1.0
    return max(0.0, 1 - (age_h - FULL_BLOCK_H) / (EXPIRE_H - FULL_BLOCK_H))


@cache
def _table():
    import boto3  # in the Lambda base image

    return boto3.resource("dynamodb").Table(os.environ["REPORTS_TABLE"])


def add(edge_id: str, lat: float, lon: float, now: float | None = None) -> dict:
    now = now or time.time()
    report = {
        "report_id": f"{int(now)}-{uuid.uuid4().hex[:8]}",
        "edge_id": edge_id,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "created_at": int(now),
        "expires_at": int(now + EXPIRE_H * 3600),
    }
    if os.environ.get("REPORTS_TABLE"):
        item = {**report, "area": AREA_KEY, "lat": str(report["lat"]), "lon": str(report["lon"])}
        _table().put_item(Item=item)
    else:
        _local.append(report)
    return report


def active(now: float | None = None) -> list[dict]:
    now = now or time.time()
    if os.environ.get("REPORTS_TABLE"):
        from boto3.dynamodb.conditions import Key

        items = _table().query(KeyConditionExpression=Key("area").eq(AREA_KEY))["Items"]
        rows = [
            {
                **i,
                "lat": float(i["lat"]),
                "lon": float(i["lon"]),
                "created_at": int(i["created_at"]),
                "expires_at": int(i["expires_at"]),
            }
            for i in items
        ]
    else:
        rows = list(_local)
    return [r for r in rows if r["expires_at"] > now]


def strengths(reports: list[dict], now: float | None = None) -> dict[str, float]:
    """{edge_id: strongest active report} for routing."""
    now = now or time.time()
    out: dict[str, float] = {}
    for r in reports:
        out[r["edge_id"]] = max(out.get(r["edge_id"], 0.0), strength(r, now))
    return out
