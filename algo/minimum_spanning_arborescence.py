"""
Directed spanning tree helper for the algo package.

This module calculates a directed equivalent of a minimum spanning tree:
a minimum spanning arborescence.

Difference from the classic MST:
- Classic MST treats the graph as undirected.
- Directed arborescence respects edge direction.
- A directed arborescence normally has a root node.
- From the root, all other nodes must be reachable through directed edges.

Typical use in the GUI:
    from algo.directed_spanning_tree import directed_spanning_tree_info

    result = directed_spanning_tree_info(tgraph, root=1)
    selected_edges = result["edges"]
"""

from typing import Hashable, List, Literal, Optional, Tuple
import math

import networkx as nx
from networkx.algorithms.tree.branchings import minimum_spanning_arborescence


NodeId = Hashable
DirectedEdge = Tuple[NodeId, NodeId]
WeightMode = Literal["current_cost", "zero_flow_cost", "flow"]


def _edge_weight(tgraph, u: NodeId, v: NodeId, weight_mode: WeightMode) -> float:
    """
    Return the numeric edge weight used by the directed algorithm.

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
        raise ValueError(f"Unknown weight_mode: {weight_mode}")

    if not math.isfinite(weight):
        raise ValueError(f"Edge ({u}, {v}) has non-finite weight: {weight}")

    return weight


def directed_spanning_tree_edges(
    tgraph,
    weight_mode: WeightMode = "current_cost",
    root: Optional[NodeId] = None,
) -> List[DirectedEdge]:
    """
    Compute a directed minimum spanning arborescence.

    Returns:
        List of directed edges [(u, v), ...].

    Important:
    - Edge direction is respected.
    - If root is provided, the tree is forced to start from that root.
    - If root is None, NetworkX chooses a possible root automatically.
    - If the graph does not contain a valid directed spanning arborescence,
      ValueError is raised.
    """
    G = tgraph.G

    if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
        return []

    if G.number_of_nodes() == 1:
        return []

    if root is not None and root not in G.nodes:
        raise ValueError(f"Root node {root} does not exist.")

    helper = nx.DiGraph()
    helper.add_nodes_from(G.nodes())

    for u, v in G.edges():
        if u == v:
            continue

        # If a root is specified, it must be the only node without
        # an incoming tree edge. Removing incoming edges into the root
        # forces the arborescence to be rooted there.
        if root is not None and v == root:
            continue

        helper.add_edge(
            u,
            v,
            weight=_edge_weight(tgraph, u, v, weight_mode),
        )

    try:
        arborescence = minimum_spanning_arborescence(
            helper,
            attr="weight",
        )
    except nx.NetworkXException as exc:
        if root is None:
            raise ValueError(
                "The directed graph does not contain a directed spanning tree. "
                "There is no directed way to reach all nodes from one root."
            ) from exc

        raise ValueError(
            f"The directed graph does not contain a directed spanning tree "
            f"rooted at node {root}. Check whether all nodes are reachable "
            f"from node {root} through directed edges."
        ) from exc

    return [(u, v) for u, v in arborescence.edges()]


def directed_spanning_tree_info(
    tgraph,
    weight_mode: WeightMode = "current_cost",
    root: Optional[NodeId] = None,
) -> dict:
    """
    Compute directed spanning tree edges and metadata for GUI status messages.

    Returns:
        {
            "edges": [(u, v), ...],
            "total_weight": float,
            "root": node_id or None,
            "is_connected": bool,
            "component_count": int,
        }
    """
    G = tgraph.G
    edges = directed_spanning_tree_edges(
        tgraph,
        weight_mode=weight_mode,
        root=root,
    )

    selected = nx.DiGraph()
    selected.add_nodes_from(G.nodes())
    selected.add_edges_from(edges)

    total_weight = 0.0
    for u, v in edges:
        total_weight += _edge_weight(tgraph, u, v, weight_mode)

    if selected.number_of_nodes() == 0:
        detected_root = None
        is_connected = True
        component_count = 0
    elif selected.number_of_nodes() == 1:
        detected_root = next(iter(selected.nodes()))
        is_connected = True
        component_count = 1
    else:
        roots = [node for node in selected.nodes() if selected.in_degree(node) == 0]
        detected_root = root if root is not None else roots[0] if roots else None
        is_connected = nx.is_weakly_connected(selected)
        component_count = nx.number_weakly_connected_components(selected)

    return {
        "edges": edges,
        "total_weight": float(total_weight),
        "root": detected_root,
        "is_connected": is_connected,
        "component_count": component_count,
    }
