from dataclasses import replace

import numpy as np

from routing.net import Net


def merge_graph(
    base: Net,
    shade_by_edge: dict[str, list[float]],
    terrain_by_edge: dict[str, float],
) -> Net:
    """Attach shade (stored as uint8 /255) and terrain_risk to every street.
    Missing values are build errors."""
    ids = base.street_id.tolist()
    missing = [s for s in ids if s not in shade_by_edge or s not in terrain_by_edge]
    if missing:
        raise ValueError(f"{len(missing)} streets missing shade or terrain_risk, e.g. {missing[0]}")
    shade = np.array([shade_by_edge[s] for s in ids], np.float32)
    return replace(
        base,
        shade=np.round(shade * 255).astype(np.uint8),
        terrain=np.array([terrain_by_edge[s] for s in ids], np.float32),
    )
