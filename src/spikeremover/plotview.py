"""Image-style zoom/pan view for the plot — rendered as a VECTOR (SVG), no dependency.

The matplotlib figure is exported to SVG and shown in a QGraphicsView via QGraphicsSvgItem,
so it stays crisp at any zoom. The whole picture (plot, labels, ticks) zooms/pans as one
image — the mouse **wheel zooms centred on the cursor**, drag with any mouse button pans,
double-click fits to the window. Files dropped here are loaded.

Behind the (possibly semi-transparent) figure sits a selectable app backdrop — a checker whose
cell is a real **plot dimension** (default 1 mm), so it scales with the plot as you zoom and
lines up with the plot area. Visible wherever a figure background alpha < 1.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

_PT_PER_MM = 72.0 / 25.4  # matplotlib SVG is 72 dpi, so scene units are points; mm -> points


@dataclass
class Background:
    """The app backdrop: a checker of two colours, or a solid fill (color_a). size_mm is
    the checker cell size in plot millimetres."""

    checkered: bool = True
    color_a: str = "#c8c8c8"  # checker dark square / solid colour
    color_b: str = "#e8e8e8"  # checker light square
    size_mm: float = 1.0


class ZoomableFigureView(QGraphicsView):
    resized = Signal()
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsSvgItem | None = None
        self._renderer: QSvgRenderer | None = None  # must outlive the item
        self._bg = Background()
        self._axes_origin = QPointF(0, 0)  # scene coords of the plot-area top-left (grid anchor)
        self._tile_key = None
        self._tile = None
        self._zoomed = False
        self._panning = False
        self._pan_from = None

        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)  # wheel zoom anchors manually
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    # ---------------- public API ----------------
    def set_background(self, bg: Background):
        self._bg = bg
        self._tile_key = None
        self.viewport().update()

    def set_figure(self, fig, keep_view: bool = False):
        """Render `fig` to SVG and show it. keep_view keeps the current zoom/pan if possible."""
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", facecolor=fig.get_facecolor(), edgecolor="none")
        self._renderer = QSvgRenderer(QByteArray(buf.getvalue()))
        size = self._renderer.defaultSize()
        w, h = size.width(), size.height()

        if self._item is not None:
            self._scene.removeItem(self._item)
        self._item = QGraphicsSvgItem()
        self._item.setSharedRenderer(self._renderer)
        self._item.setCacheMode(QGraphicsItem.NoCache)  # re-rasterise vector on each zoom
        self._item.setPos(0, 0)
        self._scene.addItem(self._item)

        if fig.axes:  # anchor the mm grid to the plot-area top-left
            pos = fig.axes[0].get_position()
            self._axes_origin = QPointF(pos.x0 * w, (1.0 - pos.y0 - pos.height) * h)
        self._scene.setSceneRect(QRectF(-w, -h, 3 * w, 3 * h))
        if not (keep_view and self._zoomed):
            self._fit()
        self.viewport().update()

    def clear(self):
        if self._item is not None:
            self._scene.removeItem(self._item)
            self._item = None
        self._zoomed = False
        self.viewport().update()

    # ---------------- view helpers ----------------
    def _fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self._zoomed = False

    def _checker_tile(self, d: int) -> QPixmap:
        key = (d, self._bg.color_a, self._bg.color_b)
        if key != self._tile_key:
            tile = QPixmap(2 * d, 2 * d)
            tile.fill(QColor(self._bg.color_b))
            p = QPainter(tile)
            p.fillRect(0, 0, d, d, QColor(self._bg.color_a))
            p.fillRect(d, d, d, d, QColor(self._bg.color_a))
            p.end()
            self._tile, self._tile_key = tile, key
        return self._tile

    # ---------------- painting ----------------
    def drawBackground(self, painter: QPainter, rect):
        # painted in device pixels, but the cell size and phase track the scene mm grid,
        # so the checker scales with zoom and stays aligned to the plot area.
        bg = self._bg
        painter.save()
        painter.resetTransform()
        vp = self.viewport().rect()
        if not bg.checkered:
            painter.fillRect(vp, QColor(bg.color_a))
            painter.restore()
            return
        cell_scene = max(0.1, bg.size_mm) * _PT_PER_MM
        dev = cell_scene * self.transform().m11()  # device px per cell
        if dev < 2:  # too dense to draw as a checker -> solid, keeps painting cheap
            painter.fillRect(vp, QColor(bg.color_a))
            painter.restore()
            return
        d = max(1, int(round(dev)))
        brush = QBrush(self._checker_tile(d))
        p0 = self.mapFromScene(self._axes_origin)  # device position of the grid origin
        brush.setTransform(QTransform().translate(p0.x(), p0.y()))
        painter.fillRect(vp, brush)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect):
        if self._item is not None:
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor("#909090"))
        painter.drawText(self.viewport().rect(), Qt.AlignCenter,
                         "Load a GINA .txt to begin\n(drag it here or use Browse…)")
        painter.restore()

    # ---------------- interaction ----------------
    def wheelEvent(self, e):
        if self._item is None:
            return
        step = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
        pos = e.position().toPoint()
        before = self.mapToScene(pos)
        self.scale(step, step)
        after = self.mapToScene(pos)
        d = after - before
        self.translate(d.x(), d.y())
        self._zoomed = True

    def mouseDoubleClickEvent(self, e):
        self._fit()

    def mousePressEvent(self, e):
        if self._item is not None:
            self._panning = True
            self._pan_from = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._panning and self._pan_from is not None:
            d = e.position() - self._pan_from
            self._pan_from = e.position()
            hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
            hb.setValue(hb.value() - int(d.x()))
            vb.setValue(vb.value() - int(d.y()))
            self._zoomed = True

    def mouseReleaseEvent(self, e):
        self._panning = False
        self.unsetCursor()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._zoomed:
            self._fit()
        self.resized.emit()

    # ---------------- drag & drop ----------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".txt")
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".txt")]
        if paths:
            self.filesDropped.emit(paths)
            e.acceptProposedAction()
