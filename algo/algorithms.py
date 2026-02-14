"""
Traffic assignment solver (Frank–Wolfe with feasible iterates).

Key properties:
- Works on a directed network (nx.DiGraph).
- Supports multiple OD pairs: demands = [(o, d, D), ...].
- Maintains feasibility (sum of flows equals total demand on used links).
- Converges as tol -> small; user can set tol (10^-x) from the GUI.

NOTE:
We initialize with an All-Or-Nothing (AON) assignment on zero-flow costs,
then use the classic FW step alpha = 2/(k+2) so iterates remain feasible.
"""

from typing import List, Tuple
import networkx as nx
import numpy as np

def frank_wolfe_assignment(tgraph, demands: List[Tuple[int,int,float]], max_iter=100, tol=1e-4):
    G = tgraph.G
    edges = list(G.edges())
    m = len(edges)
    edge_index = {e:i for i,e in enumerate(edges)}

    def costs_at(fvec):
        c = np.zeros(m)
        for (u,v), idx in edge_index.items():
            c[idx] = tgraph.get_cost(u,v,flow=float(fvec[idx]))
        return c

    def aon(costs):
        H = nx.DiGraph()
        for idx,(u,v) in enumerate(edges):
            H.add_edge(u,v,weight=float(costs[idx]))
        y = np.zeros(m)
        for (o,d,D) in demands:
            try:
                path = nx.shortest_path(H,o,d,weight='weight')
                for a,b in zip(path[:-1],path[1:]):
                    y[edge_index[(a,b)]] += D
            except:
                pass
        return y

    # start with AON on zero-flow cost
    tgraph.reset_flows()
    f = aon(costs_at(np.zeros(m)))

    for _ in range(max_iter):
        c = costs_at(f)
        y = aon(c)
        d = y - f

        if np.linalg.norm(d) < tol:
            break

        # ---- Line search ----
        # minimize total travel cost integral via scalar search on α ∈ [0,1]
        def objective(alpha):
            trial = f + alpha*d
            cost_trial = costs_at(trial)
            return np.dot(cost_trial, trial)

        a, b = 0.0, 1.0
        phi = (np.sqrt(5)-1)/2
        for _ in range(20):  # golden section iterations
            c1 = b - phi*(b-a)
            c2 = a + phi*(b-a)
            if objective(c1) < objective(c2):
                b = c2
            else:
                a = c1
        alpha = (a+b)/2

        f = f + alpha*d

    for (u,v),idx in edge_index.items():
        tgraph.set_flow(u,v,float(f[idx]))

    return {(u,v):float(G[u][v]['flow']) for (u,v) in edges}


def compute_od_travel_times(tgraph, demands):
    """
    Compute shortest-path travel times for each OD pair based on
    current flows stored in tgraph.

    Returns:
        od_costs = {(o,d): travel_time or None}
    """
    import networkx as nx

    G = tgraph.G

    # Build weighted graph with final travel times
    H = nx.DiGraph()
    for u, v in G.edges():
        flow = G[u][v].get("flow", 0.0)
        cost = tgraph.get_cost(u, v, flow)
        H.add_edge(u, v, weight=cost)

    od_costs = {}
    for (o, d, _) in demands:
        try:
            path = nx.shortest_path(H, o, d, weight="weight")
            total_cost = sum(
                tgraph.get_cost(a, b, G[a][b].get("flow", 0.0))
                for a, b in zip(path[:-1], path[1:])
            )
            od_costs[(o, d)] = total_cost
        except:
            od_costs[(o, d)] = None  # no path available

    return od_costs

