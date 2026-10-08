"""Lambda entry points for the shade pipeline (Step Functions calls these)."""

import json
import logging
import pickle

from shade import compute_tile_shade, merge_graph
from shared.storage import read_bytes, write_bytes

TRANSPORTS = ("walk", "two_wheeler")
log = logging.getLogger("climaroute.pipeline")
log.setLevel(logging.INFO)


def _read_json(key: str):
    return json.loads(read_bytes(key))


def _write_json(key: str, value) -> None:
    write_bytes(key, json.dumps(value).encode())


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

    edges = {}
    for transport in TRANSPORTS:
        base = pickle.loads(read_bytes(f"graph/{transport}_base.pkl"))
        graph = merge_graph(base, shade, terrain)
        write_bytes(f"graph/{transport}.pkl", pickle.dumps(graph, protocol=5))
        edges[transport] = graph.number_of_edges()
    log.info(json.dumps({"event": "merge", "edges": edges}))
    return {"edges": edges}
