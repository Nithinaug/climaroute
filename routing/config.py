"""Routing weights per transport. Penalties must stay >= 0 (A* heuristic admissibility)."""

ALPHA = {"walk": 2.0, "two_wheeler": 0.6}  # summer: extra cost per metre of full sun
BETA = {"walk": 3.0, "two_wheeler": 4.0}  # monsoon: extra cost per metre at flood_risk 1
BLOCK_THRESHOLD = {"walk": 0.85, "two_wheeler": 0.7}  # flood_risk above this: edge unusable
HEAT_FACTOR = 1.0
SPEED_M_PER_S = {"walk": 1.3, "two_wheeler": 5.0}
RISK_STREET_THRESHOLD = 0.5
SNAP_MAX_M = 200.0
