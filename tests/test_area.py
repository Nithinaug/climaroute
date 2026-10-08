from shared.area import utm_crs


def test_utm_zone_from_longitude():
    assert utm_crs(77.6) == "EPSG:32643"  # Bengaluru, Delhi
    assert utm_crs(72.88) == "EPSG:32643"  # Mumbai
    assert utm_crs(80.27) == "EPSG:32644"  # Chennai
    assert utm_crs(88.36) == "EPSG:32645"  # Kolkata
