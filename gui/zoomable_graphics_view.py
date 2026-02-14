from PySide6.QtWidgets import QGraphicsView
from PySide6.QtCore import Qt

class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._zoom_factor = 1.15
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:  # zoom only with CTRL + wheel
            if event.angleDelta().y() > 0:
                self.scale(self._zoom_factor, self._zoom_factor)
            else:
                self.scale(1 / self._zoom_factor, 1 / self._zoom_factor)
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        # Zoom with + and -
        if event.key() in (Qt.Key_Plus, Qt.Key_Equal):   # '+' key (both keyboard and numpad)
            self.scale(self._zoom_factor, self._zoom_factor)
        elif event.key() == Qt.Key_Minus:
            self.scale(1 / self._zoom_factor, 1 / self._zoom_factor)
        else:
            super().keyPressEvent(event)
