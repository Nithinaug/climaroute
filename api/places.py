"""Place search with Amazon Location Service (Places API), limited to the covered area."""

import os
import time
from datetime import datetime
from functools import cache, lru_cache
from zoneinfo import ZoneInfo

from shared import area

# Amazon Location costs $0.50 per 1,000 calls: cap them per city per day so abuse can't run up a
# bill. Past the cap, search and street names pause until midnight; routing is unaffected.
DAILY_LIMIT = int(os.environ.get("LOCATION_DAILY_LIMIT", "2000"))


class SearchUnavailableError(Exception):
    pass


@cache
def _client():
    import boto3  # in the Lambda base image

    return boto3.client("geo-places")


def _count_call() -> None:
    """Count one Amazon Location call for today; raises once the daily cap is reached. The
    counter lives in the reports table under its own key (area "usage"), expiring after 2 days."""
    table = os.environ.get("REPORTS_TABLE")
    if not table:  # local dev and tests: no cap
        return
    import boto3  # in the Lambda base image

    day = datetime.now(ZoneInfo(area.TIMEZONE)).strftime("%Y-%m-%d")
    try:
        boto3.resource("dynamodb").Table(table).update_item(
            Key={"area": "usage", "report_id": f"location-{day}"},
            UpdateExpression="ADD calls :one SET expires_at = :expires",
            ConditionExpression="attribute_not_exists(calls) OR calls < :limit",
            ExpressionAttributeValues={
                ":one": 1,
                ":limit": DAILY_LIMIT,
                ":expires": int(time.time()) + 2 * 86400,
            },
        )
    except boto3.client("dynamodb").exceptions.ConditionalCheckFailedException:
        raise SearchUnavailableError("daily Amazon Location limit reached") from None


@lru_cache(maxsize=512)
def search(text: str, limit: int = 5) -> list[dict]:
    try:
        _count_call()
        items = _client().search_text(
            QueryText=text,
            Filter={"BoundingBox": list(area.BBOX)},
            MaxResults=10,
            Language="en",
        )["ResultItems"]
    except Exception as e:  # noqa: BLE001 - no boto3 locally, AWS errors when deployed
        raise SearchUnavailableError(str(e)) from e
    return [
        {"name": i["Title"], "lat": i["Position"][1], "lon": i["Position"][0]}
        for i in items
        if "Position" in i
    ]


@lru_cache(maxsize=2048)
def name_at(lat: float, lon: float) -> str | None:
    """Short name for a point, e.g. "100 Feet Ring Road, Indira Nagar"."""
    try:
        _count_call()
        items = _client().reverse_geocode(QueryPosition=[lon, lat], MaxResults=1, Language="en")[
            "ResultItems"
        ]
    except Exception as e:  # noqa: BLE001 - same as search
        raise SearchUnavailableError(str(e)) from e
    if not items:
        return None
    address = items[0].get("Address", {})
    parts = [address.get("Street"), address.get("District") or address.get("Locality")]
    return ", ".join(p for p in parts if p) or items[0].get("Title")
