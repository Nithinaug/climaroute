"""Build everything the shade pipeline needs: python -m prepare.build

Writes tiles/, graph/*_base.npz, terrain/terrain_risk.json and data/water_points.geojson
through shared.storage (local ./data, or S3 when DATA_BUCKET is set).
"""

import json
import logging

import geopandas as gpd
import pandas as pd

from monsoon import terrain
from prepare import heights, osm
from prepare.graphs import to_schema
from prepare.tiles import slots, tile_inputs
from routing.net import from_graph
from shared import area
from shared.storage import write_bytes

TREE_CANOPY_RADIUS_M, TREE_HEIGHT_M = 4.0, 8.0
log = logging.getLogger("climaroute.prepare")


def shade_casters() -> gpd.GeoDataFrame:
    buildings = heights.assign_heights(osm.buildings().to_crs(area.UTM_CRS))
    log.info("heights by source: %s", buildings["height_source"].value_counts().to_dict())
    trees = osm.trees().to_crs(area.UTM_CRS)
    canopies = gpd.GeoDataFrame(
        geometry=trees.geometry.buffer(TREE_CANOPY_RADIUS_M), crs=area.UTM_CRS
    ).assign(height_m=TREE_HEIGHT_M)
    return gpd.GeoDataFrame(
        pd.concat([buildings[["geometry", "height_m"]], canopies], ignore_index=True),
        crs=area.UTM_CRS,
    )


def main() -> None:
    graphs = [
        to_schema(osm.street_graph("walk"), "walk"),
        to_schema(osm.street_graph("drive"), "two_wheeler"),
    ]
    for g in graphs:
        log.info("%s graph: %d nodes, %d edges", g.graph["transport"], len(g), g.number_of_edges())

    casters = shade_casters()
    tiles = tile_inputs(graphs, casters)
    write_bytes(
        "tiles/index.json",
        json.dumps(
            {"shade_date": graphs[0].graph["shade_date"], "slots": slots(), "tiles": sorted(tiles)}
        ).encode(),
    )
    for tile_id, tile in tiles.items():
        write_bytes(f"tiles/{tile_id}/input.json", json.dumps(tile).encode())
    for g in graphs:
        write_bytes(f"graph/{g.graph['transport']}_base.npz", from_graph(g).to_bytes())

    risk = terrain.write(graphs)
    write_bytes(
        "data/water_points.geojson", osm.water_points()[["geometry"]].to_json(drop_id=True).encode()
    )
    log.info(
        "%d tiles, %d shade casters, %d edges with terrain risk (%d at 1.0)",
        len(tiles),
        len(casters),
        len(risk),
        sum(v == 1.0 for v in risk.values()),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
