"""Building footprints from Overture Maps (OSM + Microsoft + Google, deduplicated), read from
its public S3 bucket. Much more complete than OSM alone in many Indian cities."""

import re
import urllib.request

import duckdb
import geopandas as gpd
import shapely

BUCKET = "overturemaps-us-west-2"


def latest_release() -> str:
    url = f"https://{BUCKET}.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
    with urllib.request.urlopen(url) as resp:
        return sorted(re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", resp.read().decode()))[-1]


def buildings(
    bbox: tuple[float, float, float, float], source: str | None = None
) -> gpd.GeoDataFrame:
    """WGS84 footprints with the same columns as the OSM path (height, building:levels,
    building, name). Only row groups overlapping bbox are downloaded."""
    source = source or (f"s3://{BUCKET}/release/{latest_release()}/theme=buildings/type=building/*")
    w, s, e, n = bbox
    con = duckdb.connect()
    if source.startswith("s3://"):
        con.sql("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    df = con.execute(
        f"""SELECT ST_AsWKB(geometry) AS wkb, height, num_floors AS "building:levels",
                   class AS building, names.primary AS name
            FROM read_parquet('{source}')
            WHERE bbox.xmin < ? AND bbox.xmax > ? AND bbox.ymin < ? AND bbox.ymax > ?""",
        [e, w, n, s],
    ).df()
    geometry = shapely.from_wkb(df.pop("wkb").map(bytes))
    df = df.astype(object).where(df.notna(), None)  # missing tags as None, like OSM
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
