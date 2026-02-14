from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGraphicsScene, QGraphicsView, QVBoxLayout,
    QPushButton, QHBoxLayout, QLabel, QTableWidget, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QBrush
from collections import defaultdict

from graphdata.graph_model import TrafficGraph
from gui.zoomable_graphics_view import ZoomableGraphicsView
import os
import sys

#clean is now in main_window_ui and main_window_logic, should be in only one
def resource_path(relative_path):
    # When bundled, data files are unpacked to sys._MEIPASS
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class ToggleSwitch(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self._thumb_pos = 0
        self._animation = QPropertyAnimation(self, b"thumbPos", self)
        self._animation.setDuration(200)
        self._animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.setFixedSize(52, 28)

        self.update_style(False)

    def update_style(self, checked):
        if checked:
            self._track_color = QColor("#2196F3")
            self._thumb_color = QColor("#FFFFFF")
        else:
            self._track_color = QColor("#b3b3b3")
            self._thumb_color = QColor("#FFFFFF")

        self.update()

    def getThumbPos(self):
        return self._thumb_pos

    def setThumbPos(self, pos):
        self._thumb_pos = pos
        self.update()

    thumbPos = Property(int, getThumbPos, setThumbPos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw track
        painter.setBrush(QBrush(self._track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 14, 14)

        # Draw thumb
        thumb_radius = 22
        x = 3 + self._thumb_pos
        painter.setBrush(QBrush(self._thumb_color))
        painter.drawEllipse(x, 3, thumb_radius, thumb_radius)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        start = 0 if not self.isChecked() else self.width() - 25
        end = self.width() - 25 if not self.isChecked() else 0
        self._animation.stop()
        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.start()
        self.update_style(not self.isChecked())


class MainWindowUI(QMainWindow):
    PARALLEL_OFFSET = 20.0

    def __init__(self):
        super().__init__()
        self.dark_mode = False
        self.current_tol = 1e-4

        # Data structures
        self.tgraph = TrafficGraph()
        self.node_items = {}
        self.edge_items = {}
        self.incident_edges = defaultdict(list)
        self.add_node_mode = False
        self.bg_pixmap_item = None

        # Setup UI
        self._setup_window()
        self._setup_central_widget()
        self._setup_menu_bar()

        # Apply initial theme
        self.apply_theme(resource_path("styles/light.qss"))

    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle("Traffic Graph Explorer (Directed + Multi-OD)")
        self.resize(1150, 720)

    def _setup_central_widget(self):
        """Setup the central widget with graphics view and a resizable side panel."""
        central = QWidget()
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Horizontal)

        # Graphics View (left)
        self._setup_graphics_view(splitter)

        # Side Panel (right)
        self._setup_side_panel(splitter)

        layout = QHBoxLayout(central)
        layout.addWidget(splitter)

    def _setup_graphics_view(self, parent_splitter):
        """Setup the graphics scene and view."""
        self.scene = QGraphicsScene()
        self.scene.setItemIndexMethod(QGraphicsScene.NoIndex)

        self.view = ZoomableGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)

        parent_splitter.addWidget(self.view)

    def _setup_side_panel(self, parent_splitter):
        """Setup the side panel with all controls."""
        side_widget = QWidget()
        panel = QVBoxLayout(side_widget)

        # Status Label
        self.status = QLabel("")
        panel.addWidget(self.status)

        panel.addStretch()

        # 🔹 Add the completed side widget to the splitter
        parent_splitter.addWidget(side_widget)

        # Theme Toggle
        self.theme_switch = QCheckBox("Switch theme")
        self.theme_switch.setToolTip("Switch between light and dark interface theme.")
        self.theme_switch.setChecked(False)
        panel.addWidget(self.theme_switch)

        # Add Node Button
        self.add_node_btn = QPushButton("Add node")
        self.add_node_btn.setToolTip("Activate placement mode, then left-click canvas to add a node.")
        panel.addWidget(self.add_node_btn)

        # Add Edge Button
        self.add_edge_btn = QPushButton("Add edge")
        self.add_edge_btn.setToolTip("Select exactly two nodes to create a directed edge.")
        panel.addWidget(self.add_edge_btn)

        # Edit Edge Button
        self.edit_edge_btn = QPushButton("Edit edge")
        self.edit_edge_btn.setToolTip("Modify the cost formula of the selected edge.")
        panel.addWidget(self.edit_edge_btn)

        # Remove Selected Button
        self.remove_btn = QPushButton("Remove items")
        self.remove_btn.setToolTip("Delete all selected nodes and edges.")
        panel.addWidget(self.remove_btn)

        # Clear Graph Button
        self.clear_graph_btn = QPushButton("Clear graph")
        self.clear_graph_btn.setToolTip("Remove all nodes, edges, OD pairs and background.")
        panel.addWidget(self.clear_graph_btn)

        # OD Pairs Table
        panel.addWidget(QLabel("OD Pairs:"))
        self.od_table = QTableWidget(0, 4)
        self.od_table.setToolTip("Each row represents a travel demand from Origin → Destination and computed travel time")
        self.od_table.setHorizontalHeaderLabels(["Origin", "Destination", "Demand", "Time"])
        panel.addWidget(self.od_table)

        # Add OD Pair Button
        self.add_od_btn = QPushButton("Add OD Pair")
        self.add_od_btn.setToolTip("Insert a new OD demand record.")
        panel.addWidget(self.add_od_btn)

        # Remove OD Pair Button
        self.remove_od_btn = QPushButton("Remove OD Pair/s")
        self.remove_od_btn.setToolTip("Delete highlighted OD entries from the table.")
        panel.addWidget(self.remove_od_btn)

        # Solver Accuracy Button
        self.set_accuracy_btn = QPushButton("Set solver accuracy")
        self.set_accuracy_btn.setToolTip("Adjust tolerance level for the equilibrium solver.")
        panel.addWidget(self.set_accuracy_btn)

        # Calculate Flows Button
        self.run_btn = QPushButton("Calculate flows")
        self.run_btn.setToolTip("Run equilibrium solver and update flows and travel costs.")
        panel.addWidget(self.run_btn)

        # Status Label
        self.status = QLabel("")
        panel.addWidget(self.status)

        panel.addStretch()

    def _setup_menu_bar(self):
        """Setup menu bar with File and Help menus."""
        file_menu = self.menuBar().addMenu("File")
        self.load_graph_action = file_menu.addAction("Load Graph")
        self.save_graph_action = file_menu.addAction("Save Graph")

        help_menu = self.menuBar().addMenu("Help")
        self.open_help_action = help_menu.addAction("Open Help")

        background_menu = self.menuBar().addMenu("Background")
        background_menu.setToolTipsVisible(True)
        self.load_background_action = background_menu.addAction("Load background")
        self.load_background_action.setToolTip("Place a map or blueprint image behind the graph.")
        self.clear_background_action = background_menu.addAction("Cleare background")
        self.clear_background_action.setToolTip("Remove the background image")

    def apply_theme(self, qss_path):
        """Load and apply a QSS stylesheet."""
        try:
            with open(qss_path, "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print("Failed to apply theme:", e)

    def update_graph_colors_for_theme(self):
        """Recolor nodes and labels according to current theme."""
        if self.dark_mode:
            node_brush = QColor("#3A6EA5")
            text_color = QColor("white")
        else:
            node_brush = QColor("#ADD8FF")
            text_color = QColor("black")

        for n in self.node_items.values():
            n.setBrush(node_brush)
            n.text.setDefaultTextColor(text_color)

        for e in self.edge_items.values():
            e.label.setDefaultTextColor(text_color)

        self.scene.update()