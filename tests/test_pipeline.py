import json

import pytest

from pipeline.handlers import merge, shade_tile
from routing.net import Net, from_graph
from shade import merge_graph
from shared.storage import read_bytes
from tests import dummy_area as make_dummy_tiles


def test_full_pipeline_locally(local_data):
    make_dummy_tiles.main()
    for tile_id in json.loads(read_bytes("tiles/index.json"))["tiles"]:
        shade_tile({"tile_id": tile_id})
    result = merge()

    for transport in ("walk", "two_wheeler"):
        net = Net.from_bytes(read_bytes(f"graph/{transport}.npz"))
        assert len(net.src) == result["edges"][transport]
        assert net.shade.shape == (len(net.street_id), net.meta["slot_count"])
        assert ((net.terrain >= 0) & (net.terrain <= 1)).all()


def test_two_wheeler_has_one_way_streets():
    walk = make_dummy_tiles.build_graph("walk")
    two = make_dummy_tiles.build_graph("two_wheeler")
    assert two.number_of_edges() < walk.number_of_edges()


def test_merge_rejects_missing_values():
    g = make_dummy_tiles.build_graph("walk")
    with pytest.raises(ValueError):
        merge_graph(from_graph(g), shade_by_edge={}, terrain_by_edge={})


def test_set_sun_rewrites_slots_for_the_date(local_data):
    make_dummy_tiles.main()
    from pipeline.handlers import set_sun

    assert set_sun({"date": "2026-12-21"}) == {"date": "2026-12-21"}
    index = json.loads(read_bytes("tiles/index.json"))
    assert index["shade_date"] == "2026-12-21"
    assert len(index["slots"]) == 52
    noon = max(s["elevation_deg"] for s in index["slots"])
    assert 50 < noon < 56  # December sun is low over Bengaluru (pvlib: 53.4 deg)
