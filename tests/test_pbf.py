import pytest

pytest.importorskip("osmium")
from prepare import pbf  # noqa: E402

OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" version="1" lat="12.930" lon="77.620"/>
  <node id="2" version="1" lat="12.931" lon="77.620"/>
  <node id="3" version="1" lat="12.932" lon="77.620"/>
  <node id="4" version="1" lat="12.932" lon="77.621"/>
  <node id="5" version="1" lat="12.9300" lon="77.6210"/>
  <node id="6" version="1" lat="12.9300" lon="77.6212"/>
  <node id="7" version="1" lat="12.9302" lon="77.6212"/>
  <node id="8" version="1" lat="12.9310" lon="77.6215"><tag k="natural" v="tree"/></node>
  <node id="9" version="1" lat="12.933" lon="77.620"/>
  <way id="10" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="residential"/></way>
  <way id="11" version="1"><nd ref="3"/><nd ref="4"/><tag k="highway" v="footway"/></way>
  <way id="12" version="1"><nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="5"/>
    <tag k="building" v="apartments"/><tag k="building:levels" v="4"/></way>
  <way id="13" version="1"><nd ref="3"/><nd ref="9"/>
    <tag k="highway" v="residential"/><tag k="access" v="private"/></way>
</osm>
"""


@pytest.fixture
def osm_file(tmp_path):
    path = tmp_path / "area.osm"
    path.write_text(OSM)
    return str(path)


def test_way_filter_matches_osmnx_rules():
    drive, walk = pbf.way_filter("drive"), pbf.way_filter("walk")
    assert drive({"highway": "residential"}) and walk({"highway": "residential"})
    assert walk({"highway": "footway"}) and not drive({"highway": "footway"})
    assert not drive({"highway": "residential", "access": "private"})
    assert not drive({"building": "yes"})


def test_street_graphs(osm_file):
    walk = pbf.street_graph(osm_file, "walk")
    drive = pbf.street_graph(osm_file, "drive")
    assert set(walk.nodes) == {1, 4}  # 3 is simplified away; 9 is private
    assert set(drive.nodes) == {1, 3}  # no footway, no private road


def test_features(osm_file):
    buildings = pbf.features(osm_file, {"building": True})
    assert list(buildings.geom_type) == ["MultiPolygon"]
    assert buildings.iloc[0]["building:levels"] == "4"
    trees = pbf.features(osm_file, {"natural": ["tree", "tree_row"]})
    assert list(trees.geom_type) == ["Point"]
