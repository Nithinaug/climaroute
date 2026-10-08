import pytest

duckdb = pytest.importorskip("duckdb")
from prepare import overture  # noqa: E402


def test_buildings_from_parquet(tmp_path):
    path = str(tmp_path / "b.parquet")
    duckdb.sql(f"""COPY (
        SELECT 'POLYGON((77.62 12.93, 77.6202 12.93, 77.6202 12.9302, 77.62 12.93))'::GEOMETRY
                   AS geometry,
               {{'xmin': 77.62, 'xmax': 77.6202, 'ymin': 12.93, 'ymax': 12.9302}} AS bbox,
               12.5 AS height, NULL::INTEGER AS num_floors, 'house' AS class,
               {{'primary': 'Home'}} AS names
        UNION ALL
        SELECT 'POINT(80 13)'::GEOMETRY, {{'xmin': 80, 'xmax': 80, 'ymin': 13, 'ymax': 13}},
               NULL, 4, 'office', {{'primary': NULL}}
    ) TO '{path}'""")
    gdf = overture.buildings((77.61, 12.92, 77.63, 12.94), source=path)
    assert len(gdf) == 1 and gdf.crs == "EPSG:4326"
    row = gdf.iloc[0]
    assert row["height"] == 12.5 and row["building:levels"] is None and row["building"] == "house"
    assert row.geometry.geom_type == "Polygon"
