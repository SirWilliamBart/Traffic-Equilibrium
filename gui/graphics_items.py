from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsTextItem,
    QGraphicsItem,
)
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainterPath,
    QPainterPathStroker, QPolygonF
)
from PySide6.QtCore import QPointF, Qt
import math

NODE_RADIUS = 18.0


class NodeItem(QGraphicsEllipseItem):
    """
    Draggable and selectable circular node with an in-place label.

    Performance notes:
    - Calls on_moved_callback continuously during mouse move (geometry-only edge updates).
    - Calls on_released_callback once on mouse release (to finalize label positions).
    """

    def __init__(self, node_id, pos, on_moved_callback=None, on_released_callback=None):
        r = NODE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        self.setBrush(QBrush(QColor("lightblue")))
        self.setPen(QPen(Qt.GlobalColor.black, 1))

        self.node_id = node_id
        self.on_moved_callback = on_moved_callback
        self.on_released_callback = on_released_callback
        self.setPos(pos[0], pos[1])

        self.text = QGraphicsTextItem(str(node_id), parent=self)
        self.text.setDefaultTextColor(QColor("black"))
        self.text.setPos(-r / 2, -r / 2)

        # Optional: keep node label size stable while zooming
        self.text.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.text.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    # Emit continuous updates during drag for smooth edge geometry refresh
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.on_moved_callback:
            p = self.pos()
            self.on_moved_callback(self.node_id, (p.x(), p.y()))

    # Emit a final update on release to reposition edge labels (and anything heavier)
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.on_released_callback:
            p = self.pos()
            self.on_released_callback(self.node_id, (p.x(), p.y()))


class EdgeItem(QGraphicsItem):
    """
    Directed edge drawn as a straight line (offset=0) or a quadratic Bezier curve (offset!=0),
    with a visible arrowhead near the destination node. Parent of its own label.

    Performance design:
    - update_geometry_fast(): recompute path only (no prepareGeometryChange, no label work).
      Use this repeatedly while a connected node is dragged.
    - update_position(reposition_label=True): full update with prepareGeometryChange and
      label reposition; call on mouse release or when structure changes.
    """

    ARROW_SIZE = 12.0
    # how far before the node center the arrow tip should be placed (keeps it visible)
    ARROW_INSET = NODE_RADIUS + 3.0
    LABEL_NUDGE = 14.0

    def __init__(self, u_item, v_item, u, v, offset=0.0):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        self.u_item = u_item
        self.v_item = v_item
        self.u = u
        self.v = v
        self.offset = float(offset)  # positive or negative

        # Edges render under nodes, but arrow tip is placed before node boundary to stay visible
        self.setZValue(-1)

        self.pen_normal = QPen(Qt.GlobalColor.black, 2)
        self.pen_selected = QPen(Qt.GlobalColor.red, 3)

        # Label is a child of the edge: safe ownership inside the scene graph
        self.label = QGraphicsTextItem("", parent=self)
        self.label.setDefaultTextColor(QColor("black"))
        # Cache label drawing and keep its size stable while view scales
        self.label.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setToolTip(f"Edge {u} → {v}\nNo flow yet.")

        # Cached painter path (updated when endpoints move or offset changes)
        self._path = QPainterPath()

        # Initial full update (computes path and positions label)
        self.update_position(reposition_label=True)

    def set_theme_colors(self, edge_color: QColor, text_color: QColor):
        """Set edge stroke and label colors according to the current theme."""
        self.pen_normal.setColor(edge_color)
        # Keep selected pen red, or customize here if you want:
        # self.pen_selected.setColor(edge_color_selected)
        self.label.setDefaultTextColor(text_color)
        self.update()  # repaint with the new colors

    # ---------- geometry helpers ----------

    def _consistent_perp(self, p1: QPointF, p2: QPointF):
        """
        Compute a perpendicular unit vector consistently for the *undirected* segment.
        We base the direction on u/v ids so that for reciprocal edges the same
        base perp is used, and the sign of 'offset' flips the side.
        """
        # Choose a consistent ordering based on node ids
        if self.u < self.v:
            a, b = p1, p2
        else:
            a, b = p2, p1

        dx = b.x() - a.x()
        dy = b.y() - a.y()
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return 0.0, 0.0
        # Perpendicular to (dx,dy) -> (-dy, dx), normalized
        return -dy / L, dx / L

    def _compute_path(self, p1: QPointF, p2: QPointF, offset: float) -> QPainterPath:
        """Return a QPainterPath from p1 to p2, straight or quadratic with offset."""
        path = QPainterPath(p1)

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        L = math.hypot(dx, dy)

        if L < 1e-6 or abs(offset) < 1e-4:
            # straight line
            path.lineTo(p2)
            return path

        # quadratic curve: control point = midpoint shifted by consistent perp * offset
        mx = (p1.x() + p2.x()) / 2.0
        my = (p1.y() + p2.y()) / 2.0
        px, py = self._consistent_perp(p1, p2)
        cx = mx + px * offset
        cy = my + py * offset
        path.quadTo(QPointF(cx, cy), p2)
        return path

    # ---------- public updates ----------

    def update_geometry_fast(self):
        """
        Recompute the curve path only.
        - No prepareGeometryChange() for speed (bounding rect may lag during drag).
        - No label repositioning or text changes.
        Call this frequently while a connected node is being dragged.
        """
        p1 = self.u_item.pos()
        p2 = self.v_item.pos()
        self._path = self._compute_path(p1, p2, self.offset)
        self.update()  # schedule repaint of this item

    def update_position(self, reposition_label=True):
        self.prepareGeometryChange()
        p1 = self.u_item.pos()
        p2 = self.v_item.pos()
        self._path = self._compute_path(p1, p2, self.offset)

        if reposition_label:
            # midpoint of path
            mid = self._path.pointAtPercent(0.5)

            # center label around midpoint first
            b = self.label.boundingRect()
            x = mid.x() - b.width() / 2.0
            y = mid.y() - b.height() / 2.0

            # get perpendicular direction of the segment (consistent for both twin edges)
            px, py = self._consistent_perp(p1, p2)

            # push the label fully off the curve:
            # sign from offset decides which side, magnitude is how far
            margin = 30.0  # adjust to how far away you want the label
            sign = 1.0 if self.offset >= 0 else -1.0
            x += px * sign * margin
            y += py * sign * margin

            self.label.setPos(x, y)

        self.update()

    # ---------- QGraphicsItem overrides ----------

    def boundingRect(self):
        # Use shape's bounding rect to include the stroked width
        return self.shape().boundingRect()

    def shape(self):
        # wider hitbox so user doesn't need pixel-perfect clicks
        stroker = QPainterPathStroker()
        stroker.setWidth(14)
        return stroker.createStroke(self._path)

    # ---------- painting ----------

    def _arrow_tip_and_angle(self):
        """
        Compute a robust direction at the end of the path and return:
        (arrow_tip_point, angle_radians).
        Arrow tip is inset along the reverse of the tangent so it sits before the node.
        """
        end = self._path.pointAtPercent(1.0)
        # robust finite-difference for tangent near the end
        t2 = 1.0
        t1 = max(0.0, t2 - 1e-3)
        prev = self._path.pointAtPercent(t1)
        vx = end.x() - prev.x()
        vy = end.y() - prev.y()
        L = math.hypot(vx, vy)
        if L < 1e-9:
            # degenerate; just point from start to end
            start = self._path.pointAtPercent(0.0)
            vx = end.x() - start.x()
            vy = end.y() - start.y()
            L = math.hypot(vx, vy)
            if L < 1e-9:
                return end, 0.0

        ux = vx / L
        uy = vy / L

        # Arrow tip placed before the node center for visibility
        tip = QPointF(end.x() - ux * self.ARROW_INSET, end.y() - uy * self.ARROW_INSET)
        angle = math.atan2(uy, ux)
        return tip, angle

    def paint(self, painter, option, widget=None):
        # main path
        painter.setPen(self.pen_selected if self.isSelected() else self.pen_normal)
        painter.drawPath(self._path)

        # arrowhead
        tip, angle = self._arrow_tip_and_angle()
        a = math.radians(25.0)
        s = self.ARROW_SIZE

        left = QPointF(
            tip.x() - math.cos(angle - a) * s,
            tip.y() - math.sin(angle - a) * s
        )
        right = QPointF(
            tip.x() - math.cos(angle + a) * s,
            tip.y() - math.sin(angle + a) * s
        )

        painter.setBrush(painter.pen().color())
        painter.drawPolygon(QPolygonF([tip, left, right]))
