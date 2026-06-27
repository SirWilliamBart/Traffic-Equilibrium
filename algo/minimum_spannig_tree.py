"""
Minimum spanning tree helper for the algo package.

The application stores the traffic network as a directed graph (nx.DiGraph),
but a minimum spanning tree is normally defined for an undirected graph.

This module therefore converts the directed traffic graph into an undirected
helper graph. If both directions exist between two nodes, the cheaper direction
is used. The returned edges are still returned as directed (u, v) pairs so the
GUI can select/highlight the correct EdgeItem.
"""

from typing import Hashable, List, Literal, Tuple
import math
import networkx as nx

NodeId = Hashable
DirectedEdge = Tuple[NodeId, NodeId]
WeightMode = Literal["current_cost", "zero_flow_cost", "flow"]


def _edge_weight(tgraph, u: NodeId, v: NodeId, weight_mode: WeightMode) -> float:
    """
    Return the numeric weight used by the MST algorithm.

    weight_mode:
    - "current_cost": cost evaluated at the currently stored edge flow
    - "zero_flow_cost": cost evaluated at f = 0
    - "flow": use the currently stored flow itself as edge weight
    """
    data = tgraph.G[u][v]

    if weight_mode == "current_cost":
        flow = float(data.get("flow", 0.0))
        weight = float(tgraph.get_cost(u, v, flow=flow))
    elif weight_mode == "zero_flow_cost":
        weight = float(tgraph.get_cost(u, v, flow=0.0))
    elif weight_mode == "flow":
        weight = float(data.get("flow", 0.0))
    else:
        raise ValueError(f"Unknown MST weight_mode: {weight_mode}")

    if not math.isfinite(weight):
        raise ValueError(f"Edge ({u}, {v}) has non-finite MST weight: {weight}")

    return weight


def minimum_spanning_tree_edges(
    tgraph,
    weight_mode: WeightMode = "current_cost",
) -> List[DirectedEdge]:
    """
    Compute the minimum spanning tree/forest of the current graph.

    Returns:
        List of directed edge tuples [(u, v), ...].

    Notes:
    - The calculation itself is undirected.
    - The returned direction is the original directed edge that was chosen.
    - If the graph is disconnected, NetworkX returns a minimum spanning forest.
    """
    G = tgraph.G

    if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
        return []

    helper = nx.Graph()
    helper.add_nodes_from(G.nodes())

    # For every unordered node pair, keep the cheapest available directed edge.
    best_by_pair = {}

    for u, v in G.edges():
        if u == v:
            continue

        weight = _edge_weight(tgraph, u, v, weight_mode)
        pair_key = frozenset((u, v))

        if pair_key not in best_by_pair:
            best_by_pair[pair_key] = (weight, u, v)
        else:
            old_weight, _, _ = best_by_pair[pair_key]
            if weight < old_weight:
                best_by_pair[pair_key] = (weight, u, v)

    for weight, u, v in best_by_pair.values():
        helper.add_edge(
            u,
            v,
            weight=weight,
            directed_edge=(u, v),
        )

    mst_edges = []
    for u, v, data in nx.minimum_spanning_edges(helper, data=True):
        mst_edges.append(data["directed_edge"])

    return mst_edges


def minimum_spanning_tree_info(
    tgraph,
    weight_mode: WeightMode = "current_cost",
) -> dict:
    """
    Compute MST edges and useful metadata for status messages.

    Returns:
        {
            "edges": [(u, v), ...],
            "total_weight": float,
            "is_connected": bool,
            "component_count": int,
        }
    """
    G = tgraph.G
    edges = minimum_spanning_tree_edges(tgraph, weight_mode=weight_mode)

    helper = nx.Graph()
    helper.add_nodes_from(G.nodes())

    total_weight = 0.0
    for u, v in edges:
        weight = _edge_weight(tgraph, u, v, weight_mode)
        total_weight += weight
        helper.add_edge(u, v)

    if helper.number_of_nodes() == 0:
        is_connected = True
        component_count = 0
    else:
        is_connected = nx.is_connected(helper)
        component_count = nx.number_connected_components(helper)

    return {
        "edges": edges,
        "total_weight": float(total_weight),
        "is_connected": is_connected,
        "component_count": component_count,
    }