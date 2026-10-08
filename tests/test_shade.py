import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from shade import compute_tile_shade
from shade.compute import shadows


def _tile(edge: LineString, height: float = 10.0) -> dict:
    return {
        "tile_id": "t",
        "bbox": [0, 0, 100, 100],
        "edges": [{"edge_id": "e", "wkt": edge.wkt}],
        "buildings": [{"wkt": box(0, 0, 10, 10).wkt, "height_m": height}],
    }


def test_shadow_falls_away_from_sun():
    # Sun due east (azimuth 90) at 45 deg: a 10 m building casts a 10 m shadow to the west.
    hull = shadows(np.array([box(0, 0, 10, 10)]), np.array([10.0]), 45.0, 90.0)[0]
    assert hull.bounds == pytest.approx((-10.0, 0.0, 10.0, 10.0))


def test_street_west_of_building_is_shaded_in_the_morning_not_afternoon():
    street = LineString([(-8, 0), (-8, 10)])  # runs north-south, 8 m west of the building
    morning = {"slot": 0, "elevation_deg": 45.0, "azimuth_deg": 90.0}
    afternoon = {"slot": 1, "elevation_deg": 45.0, "azimuth_deg": 270.0}
    shade = compute_tile_shade(_tile(street), [morning, afternoon])["e"]
    assert shade[0] == pytest.approx(1.0)
    assert shade[1] == pytest.approx(0.0)


def test_low_sun_counts_as_shaded():
    street = LineString([(50, 50), (60, 50)])
    shade = compute_tile_shade(_tile(street), [{"slot": 0, "elevation_deg": 5, "azimuth_deg": 90}])
    assert shade["e"] == [1.0]


def test_partial_shade_fraction():
    # Street from x=-20 to x=0 just north of the building's west half; sun east at 45 deg.
    street = LineString([(-20, 5), (0, 5)])
    shade = compute_tile_shade(_tile(street), [{"slot": 0, "elevation_deg": 45, "azimuth_deg": 90}])
    assert shade["e"][0] == pytest.approx(0.5)
    assert shapely.length(street) == 20
