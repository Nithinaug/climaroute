import networkx as nx


def merge_graph(
    base: nx.MultiDiGraph,
    shade_by_edge: dict[str, list[float]],
    terrain_by_edge: dict[str, float],
) -> nx.MultiDiGraph:
    """Attach shade and terrain_risk to every edge. Missing values are build errors."""
    g = base.copy()
    for _, _, data in g.edges(data=True):
        edge_id = data["edge_id"]
        if edge_id not in shade_by_edge or edge_id not in terrain_by_edge:
            raise ValueError(f"edge {edge_id} is missing shade or terrain_risk")
        data["shade"] = shade_by_edge[edge_id]
        data["terrain_risk"] = terrain_by_edge[edge_id]
    return g
