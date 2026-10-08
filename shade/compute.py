"""Fraction of each street edge in building shadow, per time slot (brief section 3)."""

import math

import numpy as np
import shapely

LOW_SUN_DEG = 10.0  # at or below this the whole street counts as shaded


def shadows(
    footprints: np.ndarray, heights: np.ndarray, elevation_deg: float, azimuth_deg: float
) -> np.ndarray:
    """Shadow polygon per building: convex hull of the footprint and its copy moved
    away from the sun by height / tan(elevation)."""
    length = heights / math.tan(math.radians(elevation_deg))
    az = math.radians(azimuth_deg)
    dx, dy = -length * math.sin(az), -length * math.cos(az)  # away from the sun

    coords, index = shapely.get_coordinates(footprints, return_index=True)
    moved = coords + np.column_stack([dx[index], dy[index]])
    all_index = np.concatenate([index, index])
    order = np.argsort(all_index, kind="stable")  # shapely needs indices grouped by building
    points = shapely.multipoints(np.vstack([coords, moved])[order], indices=all_index[order])
    return shapely.convex_hull(points)


def compute_tile_shade(tile_input: dict, slots: list[dict]) -> dict[str, list[float]]:
    edge_ids = [e["edge_id"] for e in tile_input["edges"]]
    edges = shapely.from_wkt([e["wkt"] for e in tile_input["edges"]])
    lengths = shapely.length(edges)
    footprints = shapely.from_wkt([b["wkt"] for b in tile_input["buildings"]])
    heights = np.array([b["height_m"] for b in tile_input["buildings"]], dtype=float)
    shapely.prepare(edges)

    per_slot = []
    for slot in slots:
        if slot["elevation_deg"] <= LOW_SUN_DEG or len(footprints) == 0:
            per_slot.append(
                np.ones(len(edges))
                if slot["elevation_deg"] <= LOW_SUN_DEG
                else np.zeros(len(edges))
            )
            continue
        shade = shapely.union_all(
            shadows(footprints, heights, slot["elevation_deg"], slot["azimuth_deg"])
        )
        shaded = shapely.length(shapely.intersection(edges, shade))
        per_slot.append(np.clip(shaded / np.maximum(lengths, 1e-9), 0.0, 1.0))

    by_slot = np.round(np.column_stack(per_slot), 3) if per_slot else np.zeros((len(edges), 0))
    return {edge_id: row.tolist() for edge_id, row in zip(edge_ids, by_slot, strict=True)}
