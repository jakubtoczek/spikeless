"""The chromatogram on screen: a matplotlib canvas the size of its space, text at screen size.

Mouse: the wheel zooms the time range around the cursor (Ctrl+wheel: the height), a right or
middle drag pans, a double-click shows the whole run. A left drag across the trace draws a
region; on a region's edge (the cursor turns ↔) it moves that edge; a click selects a region.
Arrow keys move the selected region's last-touched edge one point. With `stretch` armed, the
next left drag sets the background stretch instead. The canvas only reports what the mouse
did, in minutes; the main window decides what it means (snapping, overlaps, undo).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication

from .plotting import draw, visible_range, y_title

_EDGE_PX = 6          # how close to an edge (pixels) the mouse grabs it
_TEXT, _FIG = "#e0e0e0", "#2b2b2b"


class ChromCanvas(FigureCanvasQTAgg):
    regionDrawn = Signal(float, float, bool)       # from, to (min), exact (Alt: no snapping)
    edgeMoved = Signal(int, str, float, bool)      # region, "start" | "end", t (min), exact
    regionPicked = Signal(int)                     # its index, -1 for none
    stretchDrawn = Signal(float, float)
    dragging = Signal(float, float)                # a drawn span as it is dragged

    def __init__(self):
        self.fig = Figure(facecolor=_FIG, layout="constrained")
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot()
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)
        self.xlim = None          # (from, to) min when zoomed; None: the whole run
        self.ytop = 1.0           # Ctrl+wheel: the height, as a fraction of auto
        self.stretch = False      # the next left drag sets the background stretch
        self.state = None         # what show() last drew
        self._press = None        # the drag in progress
        self._edge = None         # (region, side) last touched, for the arrow keys
        self._temp = None         # the artist shown while dragging
        for ev, fn in (("button_press_event", self._on_press),
                       ("motion_notify_event", self._on_motion),
                       ("button_release_event", self._on_release),
                       ("scroll_event", self._on_scroll)):
            self.mpl_connect(ev, fn)

    # ---------------- drawing
    def show(self, runs, opts, results, sel, sel_region, view):
        """Draw the shown runs. view: {"raw", "spikes", "background"} for the selected run."""
        self.state = (runs, opts, results, sel, sel_region, view)
        ax = self.ax
        ax.clear()
        ax.set_facecolor("#ffffff")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=_TEXT, labelsize=9)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(_TEXT)
        if not any(r.shown for r in runs):
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "Drop a GINA .txt here, or Open… / Ctrl+V", transform=ax.transAxes,
                    ha="center", va="center", color="#909090")
            self.draw_idle()
            return
        # screen-sized lines and labels; the figure keeps its own (Figure window)
        opts = replace(opts, line_width_pt=1.3, label_size=8.5)
        draw(ax, runs, opts, results, raw=view["raw"], spikes=view["spikes"],
             background=view["background"], only=sel, sel=sel, sel_region=sel_region,
             edges=True)
        if view["background"] and sel is not None and sel.shown and sel.id in results                 and not (opts.stack or opts.pct_max):
            ax.text(0.01, 0.98, f"background {results[sel.id].background:.1f} cps (dashed)",
                    transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#606060")
        x_end = max(float(r.x[-1]) for r in runs if r.shown)
        x0, x1 = self.xlim or (0.0, x_end)
        lo, hi = visible_range(runs, opts, x0, x1)
        ax.set_xlim(x0, x1)
        ax.set_ylim(lo * 1.05 if lo < 0 else 0.0, max(hi * 1.05 * self.ytop, 1e-9))
        ax.set_xlabel("Time (min)", color=_TEXT, fontsize=9)
        ax.set_ylabel(y_title(opts), color=_TEXT, fontsize=9)
        if opts.legend and sum(r.shown for r in runs) > 1:
            ax.legend(loc="upper right", frameon=False, fontsize=8)
        self.draw_idle()

    def redraw(self):
        if self.state:
            self.show(*self.state)

    def reset_view(self):
        self.xlim, self.ytop = None, 1.0
        self.redraw()

    # ---------------- mouse
    def _sel(self):
        return self.state[3] if self.state else None

    def _edge_at(self, px):
        """(region index, side) of the selected run's edge within _EDGE_PX of pixel x."""
        sel = self._sel()
        if sel is None or not sel.shown:
            return None
        best = None
        for i, r in enumerate(sel.regions):
            for side in ("start", "end"):
                d = abs(self.ax.transData.transform((getattr(r, side), 0))[0] - px)
                if d <= _EDGE_PX and (best is None or d < best[0]):
                    best = (d, i, side)
        return best[1:] if best else None

    def _region_at(self, t):
        sel = self._sel()
        if sel is None:
            return -1
        return next((i for i, r in enumerate(sel.regions) if r.start <= t <= r.end), -1)

    def _on_press(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or not self.state:
            return
        if ev.dblclick:
            self.reset_view()
            return
        if ev.button in (2, 3):                       # pan
            self._press = ("pan", ev.x, self.ax.get_xlim())
            return
        if ev.button != 1 or self._sel() is None:
            return
        if self.stretch:
            self._press = ("stretch", ev.xdata)
            return
        edge = self._edge_at(ev.x)
        if edge:
            self._edge = edge
            self._press = ("edge", *edge)
            self.regionPicked.emit(edge[0])
            return
        self._press = ("draw", ev.xdata, ev.x)

    def _on_motion(self, ev):
        if self._press is None:
            if ev.inaxes is self.ax and self.state:
                self.setCursor(Qt.SizeHorCursor if self._edge_at(ev.x) else Qt.CrossCursor)
            else:
                self.unsetCursor()
            return
        kind = self._press[0]
        if kind == "pan":
            _, px0, (a, b) = self._press
            inv = self.ax.transData.inverted()
            dx = inv.transform((ev.x, 0))[0] - inv.transform((px0, 0))[0]
            self.xlim = (a - dx, b - dx)
            self.redraw()
            return
        if ev.xdata is None:
            return
        if self._temp is not None:
            self._temp.remove()
            self._temp = None
        if kind == "edge":
            self._temp = self.ax.axvline(ev.xdata, color="#e08000", lw=1.5, zorder=7)
        else:
            a = self._press[1]
            self._temp = self.ax.axvspan(min(a, ev.xdata), max(a, ev.xdata), zorder=7,
                                         color="#909090" if kind == "stretch" else "#e08000",
                                         alpha=0.25)
            if kind == "draw":
                self.dragging.emit(min(a, ev.xdata), max(a, ev.xdata))
        self.draw_idle()

    def _on_release(self, ev):
        press, self._press = self._press, None
        if self._temp is not None:
            self._temp.remove()
            self._temp = None
        if press is None or press[0] == "pan":
            return
        exact = bool(QApplication.keyboardModifiers() & Qt.AltModifier)
        t = ev.xdata if ev.xdata is not None else None
        kind = press[0]
        if kind == "edge":
            if t is not None:
                self.edgeMoved.emit(press[1], press[2], float(t), exact)
            return
        if kind == "stretch":
            self.stretch = False
            if t is not None and t != press[1]:
                self.stretchDrawn.emit(min(press[1], t), max(press[1], t))
            return
        if t is None or abs(ev.x - press[2]) < 4:     # a click, not a drag
            self.regionPicked.emit(self._region_at(press[1]))
            self.draw_idle()
            return
        self.regionDrawn.emit(min(press[1], t), max(press[1], t), exact)

    def _on_scroll(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or not self.state:
            return
        f = 1 / 1.25 if ev.button == "up" else 1.25
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.ytop = float(np.clip(self.ytop * f, 1e-4, 10))
        else:
            a, b = self.ax.get_xlim()
            t = ev.xdata
            self.xlim = (t - (t - a) * f, t + (b - t) * f)
        self.redraw()

    def keyPressEvent(self, e):
        sel = self._sel()
        if e.key() in (Qt.Key_Left, Qt.Key_Right) and sel is not None and self._edge:
            i, side = self._edge
            if i < len(sel.regions):
                step = sel.dt_s / 60.0 * (1 if e.key() == Qt.Key_Right else -1)
                self.edgeMoved.emit(i, side, getattr(sel.regions[i], side) + step, True)
                return
        super().keyPressEvent(e)
