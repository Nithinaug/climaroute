"""Read OSM from a local .osm.pbf extract (a whole city is too big for Overpass).

Same output as the Overpass path in osm.py: osmnx street graphs and WGS84 GeoDataFrames.
"""

import re
import subprocess
import tempfile
from pathlib import Path

import geopandas as gpd
import osmium
import osmnx as ox
import shapely

# Overpass filter clauses osmnx uses, e.g. ["highway"]["area"!~"yes"]
_CLAUSE = re.compile(r'\["([^"]+)"(?:(!?~)"([^"]*)")?\]')
TAG_COLUMNS = ("height", "building:levels", "building", "name")


def clip(region_pbf: str, bbox: tuple[float, float, float, float], out: str) -> str:
    """Cut the area out of a big regional extract with the osmium CLI (C++, fast)."""
    subprocess.run(
        ["osmium", "extract", "-b", ",".join(map(str, bbox)), region_pbf, "-o", out, "--overwrite"],
        check=True,
    )
    return out


def way_filter(network_type: str):
    """osmnx's own network filter, evaluated on a tag dict instead of by Overpass."""
    # Private osmnx helper, used so walk/drive match graph_from_bbox exactly.
    clauses = _CLAUSE.findall(ox._overpass._get_network_filter(network_type))

    def keep(tags: dict) -> bool:
        for key, op, pattern in clauses:
            value = tags.get(key)
            if not op and value is None:
                return False
            if op == "!~" and value is not None and re.search(pattern, value):
                return False
            if op == "~" and (value is None or not re.search(pattern, value)):
                return False
        return True

    return keep


def street_graph(pbf: str, network_type: str):
    keep = way_filter(network_type)
    with tempfile.TemporaryDirectory() as tmp:
        xml = str(Path(tmp) / "ways.osm")
        with osmium.BackReferenceWriter(xml, ref_src=pbf, overwrite=True) as writer:
            ways = osmium.FileProcessor(pbf, osmium.osm.WAY).with_filter(
                osmium.filter.KeyFilter("highway")
            )
            for way in ways:
                if keep({t.k: t.v for t in way.tags}):
                    writer.add_way(way)
        return ox.graph_from_xml(
            xml, bidirectional=network_type in ox.settings.bidirectional_network_types
        )


def features(pbf: str, tags: dict) -> gpd.GeoDataFrame:
    """Nodes as points, open ways as lines, closed ways/multipolygons as polygons.
    tags: osmnx style, {key: True | [values]}."""

    def match(t) -> bool:
        return any(k in t and (v is True or t[k] in v) for k, v in tags.items())

    wkb = osmium.geom.WKBFactory()
    rows = []
    for o in osmium.FileProcessor(pbf).with_areas():
        if not match(o.tags):
            continue
        try:
            if o.is_node():
                geom = wkb.create_point(o)
            elif o.is_way() and not o.is_closed():
                geom = wkb.create_linestring(o)
            elif o.is_area():
                geom = wkb.create_multipolygon(o)
            else:
                continue  # closed ways come back as areas
        except RuntimeError:  # broken geometry in OSM: skip it
            continue
        rows.append({"wkb": geom} | {c: o.tags.get(c) for c in TAG_COLUMNS})
    if not rows:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    df = gpd.pd.DataFrame(rows)
    geometry = shapely.from_wkb(df.pop("wkb").map(bytes.fromhex))
    return gpd.GeoDataFrame(df.dropna(axis=1, how="all"), geometry=geometry, crs="EPSG:4326")
