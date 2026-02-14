"""
Graph data model for traffic assignment.

Responsibilities:
- Maintain networkx.DiGraph with nodes and edges.
- Each edge stores:
    - 'func_expr': original expression string (e.g. "10 + 0.1*f")
    - 'cost_func': compiled callable cost(f)
    - 'flow': current flow value (float)
- Provide safe parsing of user-provided expressions using ast.
- Provide load_from_json and load_from_xml helpers for file import.
"""

from typing import Callable, Tuple
import networkx as nx
import math
import ast
import json
import xml.etree.ElementTree as ET

# Safe math functions/constants available to expressions
SAFE_MATH = {
    'sqrt': math.sqrt,
    'log': math.log,
    'exp': math.exp,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'abs': abs,
    'min': min,
    'max': max,
    'pi': math.pi,
    'e': math.e,
}


class UnsafeExpression(Exception):
    """Raised when a user-provided expression contains disallowed syntax or names."""
    pass


def compile_cost_expr(expr: str) -> Callable[[float], float]:
    """
    Compile a user-specified expression into a callable cost(f).
    Only a restricted set of AST nodes and names are allowed.
    """
    if expr is None:
        expr = ""
    expr = expr.strip()
    if expr == "":
        expr = "1.0"

    node = ast.parse(expr, mode='eval')

    allowed_nodes = (
        ast.Expression, ast.Call, ast.Name, ast.Load, ast.BinOp,
        ast.UnaryOp, ast.Num, ast.Constant, ast.Add, ast.Sub, ast.Mult,
        ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Tuple
    )

    for n in ast.walk(node):
        if not isinstance(n, allowed_nodes):
            raise UnsafeExpression(f"Disallowed expression element: {type(n).__name__}")
        if isinstance(n, ast.Name):
            if n.id != 'f' and n.id not in SAFE_MATH:
                raise UnsafeExpression(f"Unknown name: {n.id}")

    code = compile(node, '<string>', 'eval')

    def cost(f: float) -> float:
        local_ns = {'f': float(f)}
        local_ns.update(SAFE_MATH)
        val = eval(code, {'__builtins__': {}}, local_ns)
        return float(val)

    return cost


class TrafficGraph:
    """Container around a networkx.DiGraph storing cost expressions and flows."""

    def __init__(self):
        self.G = nx.DiGraph()

    # Node helpers
    def add_node(self, node_id, pos: Tuple[float, float] = (0, 0)):
        self.G.add_node(node_id, pos=pos)

    def remove_node(self, node_id):
        self.G.remove_node(node_id)

    def set_node_pos(self, node, pos):
        self.G.nodes[node]['pos'] = tuple(pos)

    def nodes_positions(self):
        return {n: data.get('pos', (0, 0)) for n, data in self.G.nodes(data=True)}

    # Edge helpers
    def add_edge(self, u, v, func_expr="1.0"):
        try:
            cost_func = compile_cost_expr(func_expr)
        except UnsafeExpression:
            raise
        # Directed edge; opposite edge (v,u) is independent
        self.G.add_edge(u, v, func_expr=func_expr, cost_func=cost_func, flow=0.0)

    def set_edge_expr(self, u, v, expr):
        try:
            cost_func = compile_cost_expr(expr)
        except UnsafeExpression:
            raise
        self.G[u][v]['func_expr'] = expr
        self.G[u][v]['cost_func'] = cost_func

    def set_flow(self, u, v, flow: float):
        self.G[u][v]['flow'] = float(flow)

    def get_cost(self, u, v, flow=None):
        if flow is None:
            flow = self.G[u][v].get('flow', 0.0)
        func = self.G[u][v]['cost_func']
        return func(flow)

    def all_edges(self):
        return list(self.G.edges(data=True))

    def reset_flows(self):
        for u, v, d in self.G.edges(data=True):
            d['flow'] = 0.0

    # File import helpers
    def load_from_json(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.G.clear()

        for node in data.get("nodes", []):
            nid = int(node["id"])
            pos = tuple(node.get("pos", (0, 0)))
            self.add_node(nid, pos=pos)

        for edge in data.get("edges", []):
            u = int(edge["u"])
            v = int(edge["v"])
            expr = edge.get("expr", "1.0")
            self.add_edge(u, v, expr)

        # FIX: convert dict → tuple
        od_pairs = []
        for od in data.get("od_pairs", []):
            o = int(od["origin"])
            d = int(od["dest"])
            q = float(od["demand"])
            od_pairs.append((o, d, q))

        return od_pairs

    def load_from_xml(self, path: str):
        tree = ET.parse(path)
        root = tree.getroot()

        self.G.clear()

        nodes_section = root.find("nodes")
        if nodes_section is not None:
            for node_el in nodes_section:
                nid = int(node_el.attrib["id"])
                x = float(node_el.attrib.get("x", 0))
                y = float(node_el.attrib.get("y", 0))
                self.add_node(nid, pos=(x, y))

        edges_section = root.find("edges")
        if edges_section is not None:
            for edge_el in edges_section:
                u = int(edge_el.attrib["u"])
                v = int(edge_el.attrib["v"])
                expr = edge_el.attrib.get("expr", "1.0")
                self.add_edge(u, v, expr)

        # FIX: convert XML attrs → tuple
        od_pairs = []
        od_section = root.find("od_pairs")
        if od_section is not None:
            for od_el in od_section:
                o = int(od_el.attrib["origin"])
                d = int(od_el.attrib["dest"])
                q = float(od_el.attrib["demand"])
                od_pairs.append((o, d, q))

        return od_pairs

    def save_to_json(self, filename, od_pairs=None):
        data = {
            "nodes": [
                {"id": n, "pos": list(self.G.nodes[n].get("pos", (0, 0)))}
                for n in self.G.nodes()
            ],
            "edges": [
                {"u": u, "v": v, "expr": self.G[u][v].get("func_expr", "")}
                for (u, v) in self.G.edges()
            ],
            "od_pairs": [
                {"origin": o, "dest": d, "demand": q}
                for (o, d, q) in (od_pairs or [])
            ]
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def save_to_xml(self, filename, od_pairs=None):
        root = ET.Element("graph")

        nodes_el = ET.SubElement(root, "nodes")
        for n in self.G.nodes():
            x, y = self.G.nodes[n].get("pos", (0, 0))
            ET.SubElement(nodes_el, "node", id=str(n), x=str(x), y=str(y))

        edges_el = ET.SubElement(root, "edges")
        for u, v in self.G.edges():
            expr = self.G[u][v].get("func_expr", "")
            ET.SubElement(edges_el, "edge", u=str(u), v=str(v), expr=expr)

        od_el = ET.SubElement(root, "od_pairs")
        for o, d, q in (od_pairs or []):
            ET.SubElement(od_el, "pair", origin=str(o), dest=str(d), demand=str(q))

        tree = ET.ElementTree(root)
        tree.write(filename, encoding="utf-8", xml_declaration=True)

