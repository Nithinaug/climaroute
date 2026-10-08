"""Place search with Amazon Location Service (Places API), limited to the covered area."""

from functools import cache, lru_cache

from shared import area


class SearchUnavailableError(Exception):
    pass


@cache
def _client():
    import boto3  # in the Lambda base image

    return boto3.client("geo-places")


@lru_cache(maxsize=512)
def search(text: str, limit: int = 5) -> list[dict]:
    try:
        items = _client().search_text(
            QueryText=text,
            Filter={"BoundingBox": list(area.BBOX)},
            MaxResults=limit,
            Language="en",
        )["ResultItems"]
    except Exception as e:  # noqa: BLE001 - no boto3 locally, AWS errors when deployed
        raise SearchUnavailableError(str(e)) from e
    return [
        {"name": i["Title"], "lat": i["Position"][1], "lon": i["Position"][0]}
        for i in items
        if "Position" in i
    ]
