"""Lambda entry points for the shade pipeline (Step Functions calls these)."""

import json
import logging
import pickle
from datetime import date, datetime
from zoneinfo import ZoneInfo

from shade import compute_tile_shade, merge_graph, sun
from shared import area
from shared.storage import read_bytes, write_bytes

TRANSPORTS = ("walk", "two_wheeler")
log = logging.getLogger("climaroute.pipeline")
log.setLevel(logging.INFO)


def _read_json(key: str):
    return json.loads(read_bytes(key))


def _write_json(key: str, value) -> None:
    write_bytes(key, json.dumps(value).encode())


def set_sun(event=None, context=None) -> dict:
    """Rewrite tiles/index.json slots for a date (event {"date": "YYYY-MM-DD"}; default today)."""
    day_str = (event or {}).get("date") or datetime.now(ZoneInfo(area.TIMEZONE)).date().isoformat()
    day = date.fromisoformat(day_str)
    index = _read_json("tiles/index.json")
    index["slots"] = sun.slots(
        day,
        area.CENTER["lat"],
        area.CENTER["lon"],
        area.TIMEZONE,
        area.SLOT_START,
        area.SLOT_MINUTES,
        area.SLOT_COUNT,
    )
    index["shade_date"] = day.isoformat()
    _write_json("tiles/index.json", index)
    log.info(json.dumps({"event": "set_sun", "date": index["shade_date"]}))
    return {"date": index["shade_date"]}


def shade_tile(event, context=None) -> dict:
    tile_id = event["tile_id"]
    slots = _read_json("tiles/index.json")["slots"]
    shade = compute_tile_shade(_read_json(f"tiles/{tile_id}/input.json"), slots)
    _write_json(f"tiles/{tile_id}/shade.json", shade)
    log.info(json.dumps({"event": "shade_tile", "tile_id": tile_id, "edges": len(shade)}))
    return {"tile_id": tile_id, "edges": len(shade)}


def merge(event=None, context=None) -> dict:
    shade: dict[str, list[float]] = {}
    for tile_id in _read_json("tiles/index.json")["tiles"]:
        shade.update(_read_json(f"tiles/{tile_id}/shade.json"))
    terrain = _read_json("terrain/terrain_risk.json")
    shade_date = _read_json("tiles/index.json")["shade_date"]

    edges = {}
    for transport in TRANSPORTS:
        base = pickle.loads(read_bytes(f"graph/{transport}_base.pkl"))
        graph = merge_graph(base, shade, terrain)
        graph.graph["shade_date"] = shade_date
        write_bytes(f"graph/{transport}.pkl", pickle.dumps(graph, protocol=5))
        edges[transport] = graph.number_of_edges()
    log.info(json.dumps({"event": "merge", "edges": edges}))
    return {"edges": edges}
