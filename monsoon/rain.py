import math

RAIN_SCALE_MM_PER_HOUR = 20.0  # ~63% of full risk at 20 mm/h, ~92% at 50 mm/h


def rain_factor(rain_mm_per_hour: float) -> float:
    """0.0-1.0, non-decreasing, 0 mm -> 0.0."""
    return 1.0 - math.exp(-max(rain_mm_per_hour, 0.0) / RAIN_SCALE_MM_PER_HOUR)
