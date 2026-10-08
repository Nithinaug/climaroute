COMFORT_C, FULL_HEAT_C, MAX_FACTOR = 26.0, 34.0, 1.5
CLOUD_SHADE = 0.8  # full overcast removes 80% of the sun's heat


def heat_factor(temperature_c: float, cloud_cover_pct: float) -> float:
    """0 at <= 26 C, 1 at 34 C, capped at 1.5; reduced by cloud cover."""
    heat = min(max((temperature_c - COMFORT_C) / (FULL_HEAT_C - COMFORT_C), 0.0), MAX_FACTOR)
    return round(heat * (1 - CLOUD_SHADE * cloud_cover_pct / 100), 2)
