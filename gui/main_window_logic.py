from PySide6.QtWidgets import (
    QFileDialog, QMessageBox, QInputDialog, QTableWidgetItem
)
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QPixmap, QColor, QKeySequence, QShortcut

from graphdata.graph_model import UnsafeExpression
from algo.algorithms import frank_wolfe_assignment, compute_od_travel_times
from gui.graphics_items import NodeItem, EdgeItem
from gui.main_window_ui import MainWindowUI

import sys
import os
import time
import webbrowser

def resource_path(relative_path):
    # When bundled, data files are unpacked to sys._MEIPASS
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

class MainWindow(MainWindowUI):
    """Main window with logic and event handling."""

    def __init__(self):
        super().__init__()
        self._connect_signals()
        self._setup_shortcuts()
        self.view.viewport().installEventFilter(self)
        self._populate_default_example()

    def _setup_shortcuts(self):
        # Delete selected nodes/edges
        QShortcut(QKeySequence(Qt.Key_Delete), self, activated=self.remove_selected_items)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_graph)

    def _connect_signals(self):
        """Connect all UI signals to their handlers."""
        self.theme_switch.stateChanged.connect(self.toggle_theme)
        self.clear_graph_btn.clicked.connect(self.clear_graph)
        self.set_accuracy_btn.clicked.connect(self.set_solver_accuracy)
        self.add_node_btn.clicked.connect(self.enable_add_node_mode)
        self.remove_btn.clicked.connect(self.remove_selected_items)
        self.add_edge_btn.clicked.connect(self.add_edge_between_selected)
        self.edit_edge_btn.clicked.connect(self.edit_selected_edge)
        self.load_background_action.triggered.connect(self.load_background)
        self.clear_background_action.triggered.connect(self.clear_background)
        self.add_od_btn.clicked.connect(self.add_od_pair)
        self.remove_od_btn.clicked.connect(self.remove_selected_od_pairs)
        self.run_btn.clicked.connect(self.recalculate)
        self.load_graph_action.triggered.connect(self.load_graph)
        self.save_graph_action.triggered.connect(self.save_graph)
        self.open_help_action.triggered.connect(self.open_help)

    # ============================================================
    # SOLVER ACCURACY
    # ============================================================

    def set_solver_accuracy(self):
        """Set the solver tolerance via user input."""
        text, ok = QInputDialog.getText(
            self, "Set Accuracy",
            "Enter exponent x for tolerance = 10^(-x):",
            text="4"
        )
        if not ok:
            return
        try:
            x = float(text)
            self.current_tol = 10 ** (-x)
            self.status.setText(f"Accuracy set: tol = {self.current_tol:.1e}")
        except:
            QMessageBox.warning(self, "Invalid input", "x must be numeric.")

    # ============================================================
    # NODE MANAGEMENT
    # ============================================================

    def enable_add_node_mode(self):
        """Enable node placement mode."""
        self.add_node_mode = True
        self.status.setText("Click on canvas to add node")

    def eventFilter(self, obj, event):
        """Handle mouse events for node placement."""
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self.add_node_mode:
                pos = self.view.mapToScene(event.pos())
                self.add_node((pos.x(), pos.y()))
                self.add_node_mode = False
                return True
        return super().eventFilter(obj, event)

    def add_node(self, pos_xy):
        """Add a new node at the specified position."""
        existing = list(self.tgraph.G.nodes())
        nid = max(existing) + 1 if existing else 1
        self.tgraph.add_node(nid, pos=pos_xy)
        n = NodeItem(
            nid,
            pos_xy,
            on_moved_callback=self.on_node_moved_fast,
            on_released_callback=self.on_node_released
        )
        self.scene.addItem(n)
        self.node_items[nid] = n

        # NEW: immediately apply current theme so the node matches dark/light mode
        self.update_graph_colors_for_theme()

    def on_node_moved_fast(self, node_id, pos):
        """Fast update during node drag (geometry only)."""
        self.tgraph.set_node_pos(node_id, pos)
        for e in self.incident_edges.get(node_id, ()):
            e.update_geometry_fast()

    def on_node_released(self, node_id, pos):
        """Update after node release (reposition labels)."""
        self.tgraph.set_node_pos(node_id, pos)
        for e in self.incident_edges.get(node_id, ()):
            e.update_position(reposition_label=True)

    # ============================================================
    # EDGE MANAGEMENT
    # ============================================================

    def add_edge_between_selected(self):
        """Add a directed edge between two selected nodes."""
        selected = [i for i in self.scene.selectedItems() if isinstance(i, NodeItem)]

        #
        # CASE 1: No nodes selected -> ask for u,v typed input
        #
        if len(selected) == 0:
            text, ok = QInputDialog.getText(
                self, "Add edge",
                "Enter two node IDs as u,v (e.g. 1,2):"
            )
            if not ok:
                return

            # Parse input
            try:
                u_s, v_s = text.split(',')
                u, v = int(u_s.strip()), int(v_s.strip())
            except:
                QMessageBox.critical(self, "Error", "Bad format. Use u,v where u and v are integers.")
                return

            # Validate nodes exist
            if u not in self.tgraph.G.nodes():
                QMessageBox.critical(self, "Error", f"Node {u} does not exist.")
                return
            if v not in self.tgraph.G.nodes():
                QMessageBox.critical(self, "Error", f"Node {v} does not exist.")
                return

            if u == v:
                QMessageBox.critical(self, "Error", "Cannot create an edge from a node to itself.")
                return

            # Find NodeItem objects
            try:
                a = next(item for item in self.scene.items()
                         if isinstance(item, NodeItem) and item.node_id == u)
                b = next(item for item in self.scene.items()
                         if isinstance(item, NodeItem) and item.node_id == v)
            except StopIteration:
                QMessageBox.critical(self, "Error", "Internal error: NodeItem not found.")
                return

            selected = [a, b]

        #
        # CASE 2: Selected exactly 2 (original behavior)
        #
        elif len(selected) != 2:
            QMessageBox.information(self, "Select 2", "Select exactly two nodes.")
            return

        # From here forward: we have exactly two node items
        a, b = selected
        a_id, b_id = a.node_id, b.node_id

        direction, ok = QInputDialog.getItem(
            self, "Direction", "Choose direction:",
            [f"{a_id} → {b_id}", f"{b_id} → {a_id}"], 0, False
        )
        if not ok:
            return

        if direction.startswith(str(a_id)):
            u, v = a_id, b_id
            u_item, v_item = a, b
        else:
            u, v = b_id, a_id
            u_item, v_item = b, a

        if self.tgraph.G.has_edge(u, v):
            QMessageBox.critical(self, "Error", f"Edge {u} → {v} already exists.")
            return

        expr, ok = QInputDialog.getText(
            self, "Cost", f"Cost for {u}->{v}", text="1 + 0.01*f"
        )
        if not ok:
            return

        try:
            self.tgraph.add_edge(u, v, expr)
        except UnsafeExpression as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        offset = 0.0
        if (v, u) in self.edge_items:
            offset = +self.PARALLEL_OFFSET
            self.edge_items[(v, u)].offset = -self.PARALLEL_OFFSET
            self.edge_items[(v, u)].update_position(reposition_label=True)

        e = EdgeItem(u_item, v_item, u, v, offset=offset)
        self.scene.addItem(e)
        self.edge_items[(u, v)] = e
        self.incident_edges[u].append(e)
        self.incident_edges[v].append(e)

        # Set label immediately
        expr = self.tgraph.G[u][v].get('func_expr', '')
        initial_cost = self.tgraph.get_cost(u, v, 0.0)

        e.label.setPlainText(f"c={expr}\nf=0.0\nt={initial_cost:.2f}")
        e.setToolTip(f"Edge {u} → {v}\nExpression: {expr}\nFlow = 0.0\nCost = {initial_cost:.2f}")
        e.update_position(reposition_label=True)

    def edit_selected_edge(self):
        """Edit the cost expression of a selected edge."""
        selected_edges = [it for it in self.scene.selectedItems() if isinstance(it, EdgeItem)]
        if len(selected_edges) == 1:
            edge_item = selected_edges[0]
            u, v = edge_item.u, edge_item.v
            current = self.tgraph.G[u][v].get('func_expr', "1.0")
            expr, ok = QInputDialog.getText(
                self, "Edit edge cost",
                f"Cost expression for {u} → {v} (use 'f' for flow):",
                text=current
            )
            if not ok:
                return
            try:
                self.tgraph.set_edge_expr(u, v, expr)
            except UnsafeExpression as e:
                QMessageBox.critical(self, "Invalid expression", str(e))
                return
            return

        if len(selected_edges) > 1:
            QMessageBox.information(self, "Pick one edge", "Select exactly one edge to edit.")
            return

        text, ok = QInputDialog.getText(self, "Edit edge", "Enter edge as u,v (e.g. 1,2):")
        if not ok:
            return
        try:
            u_s, v_s = text.split(',')
            u, v = int(u_s.strip()), int(v_s.strip())
        except:
            QMessageBox.critical(self, "Error", "Bad format. Use u,v integers.")
            return
        if not self.tgraph.G.has_edge(u, v):
            QMessageBox.critical(self, "Error", f"No edge {u}->{v}")
            return
        current = self.tgraph.G[u][v].get('func_expr', "1.0")
        expr, ok = QInputDialog.getText(
            self, "Edit edge cost",
            f"Cost expression for {u} → {v} (use 'f' for flow):",
            text=current
        )
        if not ok:
            return
        try:
            self.tgraph.set_edge_expr(u, v, expr)
        except UnsafeExpression as e:
            QMessageBox.critical(self, "Invalid expression", str(e))
            return
        self.recalculate()

    # ============================================================
    # REMOVAL
    # ============================================================

    def remove_selected_items(self):
        """Remove selected nodes and edges from the graph."""

        selected = self.scene.selectedItems()

        #
        # CASE: Nothing selected → ask user what to remove
        #
        if len(selected) == 0:
            # Ask for edges to delete
            text_edges, ok_e = QInputDialog.getText(
                self, "Remove edges",
                "Enter edges to remove as u,v pairs separated by spaces.\n"
                "Example: 1,2  3,4  10,2\n"
                "(Leave empty to skip)"
            )
            if not ok_e:
                return

            # Ask for nodes to delete
            text_nodes, ok_n = QInputDialog.getText(
                self, "Remove nodes",
                "Enter node IDs separated by spaces.\n"
                "Example: 1  5  7\n"
                "(Leave empty to skip)"
            )
            if not ok_n:
                return

            # --- Process edge removals ---
            if text_edges.strip():
                pairs = text_edges.split()
                for p in pairs:
                    try:
                        u_s, v_s = p.split(',')
                        u, v = int(u_s.strip()), int(v_s.strip())
                    except:
                        QMessageBox.critical(self, "Error", f"Bad edge format: '{p}'")
                        continue

                    if not self.tgraph.G.has_edge(u, v):
                        QMessageBox.critical(self, "Error", f"No such edge: {u}->{v}")
                        continue

                    self._remove_edge(u, v)

            # --- Process node removals ---
            if text_nodes.strip():
                nodes_to_delete = text_nodes.split()
                for n_s in nodes_to_delete:
                    try:
                        nid = int(n_s)
                    except:
                        QMessageBox.critical(self, "Error", f"Bad node ID: '{n_s}'")
                        continue

                    if not self.tgraph.G.has_node(nid):
                        QMessageBox.critical(self, "Error", f"Node {nid} does not exist.")
                        continue

                    # Remove all edges touching this node
                    for (u, v) in list(self.edge_items.keys()):
                        if u == nid or v == nid:
                            self._remove_edge(u, v)

                    # Remove node
                    for item in list(self.scene.items()):
                        if isinstance(item, NodeItem) and item.node_id == nid:
                            self.scene.removeItem(item)
                            break

                    self.tgraph.remove_node(nid)
                    self.node_items.pop(nid, None)
                    self.incident_edges.pop(nid, None)

            return  # Done handling "nothing selected" case

        #
        # CASE: Something is selected → original behavior
        #
        for item in list(selected):
            if isinstance(item, NodeItem):
                nid = item.node_id
                for (u, v) in list(self.edge_items.keys()):
                    if u == nid or v == nid:
                        self._remove_edge(u, v)
                if self.tgraph.G.has_node(nid):
                    self.tgraph.remove_node(nid)
                self.scene.removeItem(item)
                self.node_items.pop(nid, None)
                self.incident_edges.pop(nid, None)

            elif isinstance(item, EdgeItem):
                self._remove_edge(item.u, item.v)

    def _remove_edge(self, u, v):
        """Remove an edge from the graph."""
        if self.tgraph.G.has_edge(u, v):
            self.tgraph.G.remove_edge(u, v)
        if (u, v) in self.edge_items:
            e = self.edge_items.pop((u, v))
            if u in self.incident_edges:
                try:
                    self.incident_edges[u].remove(e)
                except ValueError:
                    pass
            if v in self.incident_edges:
                try:
                    self.incident_edges[v].remove(e)
                except ValueError:
                    pass
            self.scene.removeItem(e)
        if (v, u) in self.edge_items:
            self.edge_items[(v, u)].offset = 0.0
            self.edge_items[(v, u)].update_position(reposition_label=True)

    # ============================================================
    # OD PAIRS
    # ============================================================

    def add_od_pair(self):
        """Add a new OD pair to the table."""
        row = self.od_table.rowCount()
        self.od_table.insertRow(row)
        self.od_table.setItem(row, 0, QTableWidgetItem("1"))
        self.od_table.setItem(row, 1, QTableWidgetItem("2"))
        self.od_table.setItem(row, 2, QTableWidgetItem("100"))

    def remove_selected_od_pairs(self):
        """Remove selected OD pairs from the table."""
        selected = self.od_table.selectionModel().selectedRows()
        for idx in reversed(sorted(selected)):
            self.od_table.removeRow(idx.row())

    # ============================================================
    # BACKGROUND
    # ============================================================

    def load_background(self):
        """Load a background image for the graph."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select background image", "", "Images (*.png *.jpg *.bmp)"
        )
        if not path:
            return
        img = QImage(path)
        pix = QPixmap.fromImage(img)
        if self.bg_pixmap_item:
            self.scene.removeItem(self.bg_pixmap_item)
        self.bg_pixmap_item = self.scene.addPixmap(pix)
        self.bg_pixmap_item.setZValue(-10)
        self.bg_pixmap_item.setOpacity(0.6)

    def clear_background(self):
        """Remove the background image from the scene."""
        if self.bg_pixmap_item:
            self.scene.removeItem(self.bg_pixmap_item)
            self.bg_pixmap_item = None
            self.status.setText("Background cleared.")
        else:
            self.status.setText("No background to clear.")

    # ============================================================
    # CALCULATION
    # ============================================================

    def recalculate(self):
        """Run the traffic assignment calculation and update display."""
        demands = []
        for row in range(self.od_table.rowCount()):
            try:
                o = int(self.od_table.item(row, 0).text())
                d = int(self.od_table.item(row, 1).text())
                q = float(self.od_table.item(row, 2).text())
                demands.append((o, d, q))
            except:
                continue

        if not demands:
            self.status.setText("No OD pairs defined.")
            return

        start_time = time.perf_counter()

        flows = frank_wolfe_assignment(self.tgraph, demands, max_iter=80, tol=self.current_tol)
        od_costs = compute_od_travel_times(self.tgraph, demands)
        elapsed = time.perf_counter() - start_time

        for (u, v), edge in self.edge_items.items():
            f = flows.get((u, v), 0.0)
            c = self.tgraph.get_cost(u, v, f)
            expr = self.tgraph.G[u][v].get('func_expr', '')

            # Show cost expression, flow and travel time
            edge.label.setPlainText(f"c={expr}\nf={f:.1f}\nt={c:.2f}")

            # Tooltip
            edge.setToolTip(
                f"Edge {u} → {v}\nExpression: {expr}\nFlow = {f:.1f}\nCost = {c:.2f} \n(left-click to select)"
            )

            edge.update_position(reposition_label=True)

        for row in range(self.od_table.rowCount()):
            try:
                o = int(self.od_table.item(row, 0).text())
                d = int(self.od_table.item(row, 1).text())
            except:
                continue

            T = od_costs.get((o, d), None)
            text = "No path" if T is None else f"{T:.2f}"

            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.od_table.setItem(row, 3, item)

        self.status.setText(f"Solved in {elapsed:.3f} s (tol={self.current_tol:.1e})")

    # ============================================================
    # CLEAR
    # ============================================================

    def clear_graph(self):
        """Clear all graph data and reset the scene."""
        self.tgraph.G.clear()
        self.scene.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.incident_edges.clear()
        self.od_table.setRowCount(0)
        self.bg_pixmap_item = None
        self.status.setText("Cleared.")

    # ============================================================
    # LOAD GRAPH
    # ============================================================

    def load_graph(self):
        """Load a graph from a file (JSON or XML), including OD pairs."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Graph", "", "Graph Files (*.json *.xml);;All Files (*)"
        )
        if not path:
            return

        try:
            self.clear_graph()

            # Load nodes, edges, return OD list
            if path.lower().endswith(".json"):
                od_pairs = self.tgraph.load_from_json(path)
            elif path.lower().endswith(".xml"):
                od_pairs = self.tgraph.load_from_xml(path)
            else:
                QMessageBox.warning(self, "Error", "Unsupported format.")
                return

            # --- Rebuild nodes in scene ---
            for nid, pos in self.tgraph.nodes_positions().items():
                n = NodeItem(
                    nid,
                    pos,
                    on_moved_callback=self.on_node_moved_fast,
                    on_released_callback=self.on_node_released
                )
                self.scene.addItem(n)
                self.node_items[nid] = n

            # --- Rebuild edges in scene ---
            added = set()
            for (u, v, _) in self.tgraph.G.edges(data=True):
                if (u, v) in added:
                    continue

                if self.tgraph.G.has_edge(v, u):
                    # Parallel edges
                    e1 = EdgeItem(
                        self.node_items[u], self.node_items[v], u, v,
                        offset=+self.PARALLEL_OFFSET
                    )
                    e2 = EdgeItem(
                        self.node_items[v], self.node_items[u], v, u,
                        offset=-self.PARALLEL_OFFSET
                    )
                    self.scene.addItem(e1)
                    self.scene.addItem(e2)

                    self.edge_items[(u, v)] = e1
                    self.edge_items[(v, u)] = e2

                    self.incident_edges[u].append(e1)
                    self.incident_edges[v].append(e1)
                    self.incident_edges[v].append(e2)
                    self.incident_edges[u].append(e2)

                    for (e_item, uu, vv) in [(e1, u, v), (e2, v, u)]:
                        expr = self.tgraph.G[uu][vv].get("func_expr", "")
                        initial_cost = self.tgraph.get_cost(uu, vv, 0.0)
                        e_item.label.setPlainText(f"c={expr}\nf=0.0\nt={initial_cost:.2f}")
                        e_item.setToolTip(
                            f"Edge {uu} → {vv}\nExpression: {expr}\nFlow = 0.0\nCost = {initial_cost:.2f}"
                        )
                        e_item.update_position(reposition_label=True)

                    added.add((u, v))
                    added.add((v, u))

                else:
                    # Single directed edge
                    e = EdgeItem(self.node_items[u], self.node_items[v], u, v)
                    self.scene.addItem(e)
                    self.edge_items[(u, v)] = e
                    self.incident_edges[u].append(e)
                    self.incident_edges[v].append(e)

                    expr = self.tgraph.G[u][v].get("func_expr", "")
                    initial_cost = self.tgraph.get_cost(u, v, 0.0)
                    e.label.setPlainText(f"c={expr}\nf=0.0\nt={initial_cost:.2f}")
                    e.setToolTip(
                        f"Edge {u} → {v}\nExpression: {expr}\nFlow = 0.0\nCost = {initial_cost:.2f}"
                    )
                    e.update_position(reposition_label=True)

                    added.add((u, v))

            # --- Load OD pairs into table ---
            self.od_table.setRowCount(0)
            for o, d, q in od_pairs:
                row = self.od_table.rowCount()
                self.od_table.insertRow(row)
                self.od_table.setItem(row, 0, QTableWidgetItem(str(o)))
                self.od_table.setItem(row, 1, QTableWidgetItem(str(d)))
                self.od_table.setItem(row, 2, QTableWidgetItem(str(q)))

            QMessageBox.information(self, "Success", f"Loaded {os.path.basename(path)}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load graph:\n{e}")

    # ============================================================
    # SAVE GRAPH
    # ============================================================

    def save_graph(self):
        """Save/export the current graph and OD pairs to JSON or XML."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Graph", "", "JSON (*.json);;XML (*.xml)"
        )
        if not path:
            return

        try:
            # --- Extract OD pairs from table ---
            od_pairs = []
            for row in range(self.od_table.rowCount()):
                try:
                    o = int(self.od_table.item(row, 0).text())
                    d = int(self.od_table.item(row, 1).text())
                    q = float(self.od_table.item(row, 2).text())
                    od_pairs.append((o, d, q))
                except:
                    pass

            # --- Save file ---
            if path.lower().endswith(".json"):
                self.tgraph.save_to_json(path, od_pairs=od_pairs)

            elif path.lower().endswith(".xml"):
                self.tgraph.save_to_xml(path, od_pairs=od_pairs)

            else:
                # Default to JSON
                path = path + ".json"
                self.tgraph.save_to_json(path, od_pairs=od_pairs)

            QMessageBox.information(self, "Saved", f"Graph exported to:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save graph:\n{e}")

    # ============================================================
    # THEME
    # ============================================================

    def toggle_theme(self):
        """Toggle between light and dark theme."""
        self.dark_mode = self.theme_switch.isChecked()

        if self.dark_mode:
            self.apply_theme(resource_path("styles/dark.qss"))

        else:
            self.apply_theme(resource_path("styles/light.qss"))

        self.update_graph_colors_for_theme()

    # ============================================================
    # HELP
    # ============================================================

    def open_help(self):
        """Open the help documentation in a web browser."""
        help_path = resource_path("files/help.html")
        if not os.path.exists(help_path):
            QMessageBox.warning(self, "Help file not found", f"Cannot find:\n{help_path}")
            return
        webbrowser.open(f"file://{help_path}")

    # ============================================================
    # DEFAULT EXAMPLE
    # ============================================================

    def _populate_default_example(self):
        """Load a default example graph."""
        nodes = {1: (0, 0), 2: (220, 0), 3: (0, 200), 4: (220, 200)}
        for nid, pos in nodes.items():
            self.tgraph.add_node(nid, pos)
            n = NodeItem(
                nid,
                pos,
                on_moved_callback=self.on_node_moved_fast,
                on_released_callback=self.on_node_released
            )
            self.scene.addItem(n)
            self.node_items[nid] = n

        self.tgraph.add_edge(1, 2, "0+0.01*f")
        self.tgraph.add_edge(1, 3, "45")
        self.tgraph.add_edge(2, 4, "45")
        self.tgraph.add_edge(3, 4, "0+0.01*f")
        self.tgraph.add_edge(2, 3, "0")
        self.tgraph.add_edge(3, 2, "0")

        added = set()
        for (u, v, _) in self.tgraph.G.edges(data=True):
            if (u, v) in added:
                continue
            if self.tgraph.G.has_edge(v, u):
                e1 = EdgeItem(
                    self.node_items[u], self.node_items[v], u, v, offset=+self.PARALLEL_OFFSET
                )
                e2 = EdgeItem(
                    self.node_items[v], self.node_items[u], v, u, offset=-self.PARALLEL_OFFSET
                )
                self.scene.addItem(e1)
                self.scene.addItem(e2)
                self.edge_items[(u, v)] = e1
                self.edge_items[(v, u)] = e2
                self.incident_edges[u].append(e1)
                self.incident_edges[v].append(e1)
                self.incident_edges[v].append(e2)
                self.incident_edges[u].append(e2)
                e1.update_position(True)
                e2.update_position(True)
                added.add((u, v))
                added.add((v, u))
            else:
                e = EdgeItem(self.node_items[u], self.node_items[v], u, v)
                self.scene.addItem(e)
                self.edge_items[(u, v)] = e
                self.incident_edges[u].append(e)
                self.incident_edges[v].append(e)
                e.update_position(True)
                added.add((u, v))

        self.add_od_pair()
        self.od_table.item(0, 0).setText("1")
        self.od_table.item(0, 1).setText("4")
        self.od_table.item(0, 2).setText("4000")

        self.recalculate()