"""The chromatogram on screen: a matplotlib canvas the size of its space, text at screen size.

Mouse (Options › Chromatogram sets the buttons): a left click puts a reading line there — its
time, point and count rate — and centres a zoomed view on it; a left drag zooms to the span
(the height fitted to it); a right or middle drag pans; the wheel zooms the time around the
cursor (the height too, if unlocked; Ctrl+wheel: the height alone); a double-click shows the
whole run. The view is elastic: dragged or zoomed out past the data, it springs back.

On an edge of the selected run's regions, or of its background stretch, the cursor turns ↔
and a drag moves that edge; ← → move the last-touched edge one point. set_mode("region") or
("stretch") arms drawing (the cursor an open cross): a drag across the span, or a click on
each of its edges; a right click or Esc cancels. The canvas only reports what the mouse did,
in minutes; the main window decides what it means (snapping, overlaps, undo).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from .options import PREFS
from .plotting import curves, draw, fit_y, place_legend, y_span, y_title

_EDGE_PX = 6          # how close to an edge (pixels) the mouse grabs it
_CLICK_PX = 4         # a press that moves less than this is a click
_RUBBER = 0.35        # past the data, a drag moves the view this much
_TEXT, _FIG = "#e0e0e0", "#2b2b2b"


def _open_cross() -> QCursor:
    """A cross open at its centre: drawing is armed (the usual cursor is the arrow)."""
    pm = QPixmap(25, 25)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    for color, w in (("#ffffff", 3), ("#000000", 1)):
        p.setPen(QPen(QColor(color), w))
        for x0, y0, x1, y1 in ((12, 1, 12, 8), (12, 16, 12, 23), (1, 12, 8, 12), (16, 12, 23, 12)):
            p.drawLine(x0, y0, x1, y1)
    p.end()
    return QCursor(pm, 12, 12)


class ChromCanvas(FigureCanvasQTAgg):
    regionDrawn = Signal(float, float, bool)       # from, to (min), exact (Alt: no snapping)
    edgeMoved = Signal(int, str, float, bool)      # region (-1: the stretch), side, t, exact
    regionPicked = Signal(int)                     # its index, -1 for none
    stretchDrawn = Signal(float, float)
    dragging = Signal(float, float)                # a drawn span as it is dragged
    modeEnded = Signal()                           # drawing armed no more (drawn, cancelled)
    anim_ms = 180                                  # a spring back, a zoom (0: at once)

    def __init__(self):
        self.fig = Figure(facecolor=_FIG, layout="constrained")
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot()
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)
        self.xlim = None          # (from, to) min when zoomed; None: the whole run
        self.ylim = None          # (lo, hi) when the height is zoomed; None: fitted
        self.mode = None          # "region" | "stretch": the next drag, or two clicks, draws
        self.anchor = None        # the first click of a two-click draw (min)
        self.cursor_t = None      # the reading line (min)
        self.state = None         # what show() last drew
        self._curves = []         # what the fitted height is computed on
        self._press = None        # the drag in progress
        self._edge = None         # (region, side) last touched, for the arrow keys
        self._temp = []           # artists shown while dragging
        self._cross = _open_cross()
        self._anim = QTimer(self, interval=15, timeout=self._frame)
        self._anim_path = None
        self._settle_later = QTimer(self, singleShot=True, interval=150, timeout=self._settle)
        for ev, fn in (("button_press_event", self._on_press),
                       ("motion_notify_event", self._on_motion),
                       ("button_release_event", self._on_release),
                       ("scroll_event", self._on_scroll)):
            self.mpl_connect(ev, fn)

    # ---------------- drawing
    def show(self, runs, opts, results, sel, sel_region, view):
        """Draw the shown runs. view: {"raw", "spikes", "background"} for the selected run
        (every run when none is)."""
        self.state = (runs, opts, results, sel, sel_region, view)
        self._temp = []
        ax = self.ax
        ax.clear()
        ax.set_facecolor("#ffffff")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=_TEXT, labelsize=9)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(_TEXT)
        if not any(r.shown for r in runs):
            self._curves = []
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
        if sel is not None and sel.shown and sel.bg_mode == "stretch" and sel.bg_stretch:
            a, b = sorted(sel.bg_stretch)
            ax.axvspan(a, b, color="#9090a0", alpha=0.18, lw=0, zorder=0.5)
            for t in (a, b):
                ax.axvline(t, color="#707080", lw=0.9, ls="--", zorder=5)
            ax.text((a + b) / 2, 0.02, "background stretch", ha="center", va="bottom",
                    fontsize=7.5, color="#606070",
                    transform=blended_transform_factory(ax.transData, ax.transAxes))
        if view["background"] and sel is not None and sel.shown and sel.id in results \
                and opts.y_mode == "cps" and not opts.stack:
            ax.text(0.01, 0.98, f"background {results[sel.id].background:.1f} cps (dashed)",
                    transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#606060")
        self._curves = curves(runs, opts)
        ax.set_xlabel("Time (min)", color=_TEXT, fontsize=9)
        ax.set_ylabel(y_title(opts), color=_TEXT, fontsize=9)
        self._apply(*self._view())
        place_legend(ax, opts, 8)
        self._reading()
        self.draw_idle()

    def redraw(self):
        if self.state:
            self.show(*self.state)

    # ---------------- the view
    def _full_x(self):
        runs = self.state[0] if self.state else []
        return 0.0, max((float(r.x[-1]) for r in runs if r.shown), default=1.0)

    def _auto_y(self, x0, x1):
        return y_span(*fit_y(self._curves, x0, x1))

    def _view(self):
        """(x0, x1, y0, y1) as it stands, the fitted parts worked out."""
        x0, x1 = self.xlim or self._full_x()
        y0, y1 = self.ylim or self._auto_y(x0, x1)
        return x0, x1, y0, y1

    def _apply(self, x0, x1, y0, y1):
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y0, max(y1, y0 + 1e-9))

    def _set_view(self, xlim, ylim, animate=True):
        """Go to (xlim, ylim) — None for each: the whole run, the fitted height — sliding there
        unless anim_ms is 0."""
        self._anim.stop()
        start = self._view()
        self.xlim, self.ylim = xlim, ylim
        end = self._view()
        if not animate or not self.anim_ms or not self._curves or np.allclose(start, end):
            self._apply(*end)
            self.draw_idle()
            return
        self._anim_path = (np.array(start), np.array(end), 0)
        self._anim.start()

    def _frame(self):
        a, b, k = self._anim_path
        k += 1
        f = min(1.0, k * self._anim.interval() / self.anim_ms)
        f = 1 - (1 - f) ** 3                                     # ease out
        self._apply(*(a + (b - a) * f))
        self.draw_idle()
        self._anim_path = (a, b, k)
        if f >= 1:
            self._anim.stop()

    def _finish(self):
        """An animation in progress jumps to its end (a new gesture starts from there)."""
        if self._anim.isActive():
            self._anim.stop()
            self._apply(*self._view())

    def _settle(self):
        """Spring back to the data: a view wider than the run becomes the whole run, one past
        its ends slides back inside; the same for a zoomed height and the fitted one."""
        if not self.state:
            return
        x0, x1, y0, y1 = (float(v) for v in (*self.ax.get_xlim(), *self.ax.get_ylim()))
        fa, fb = self._full_x()
        xlim = None
        if x1 - x0 < fb - fa - 1e-9:
            shift = max(fa - x0, 0.0) - max(x1 - fb, 0.0)
            xlim = (x0 + shift, x1 + shift)
        ylim = None
        if self.ylim is not None:
            ya, yb = self._auto_y(*(xlim or (fa, fb)))
            if y1 - y0 < yb - ya - 1e-9:
                shift = max(ya - y0, 0.0) - max(y1 - yb, 0.0)
                ylim = (y0 + shift, y1 + shift)
        self.xlim, self.ylim = (x0, x1), (y0, y1)          # where it is: slide from there
        self._set_view(xlim, ylim)

    def reset_view(self):
        self._set_view(None, None)

    def focus(self, x0, x1):
        """Show x0 to x1 (clamped to the run), the height fitted to it."""
        fa, fb = self._full_x()
        x0, x1 = max(fa, x0), min(fb, x1)
        if x1 > x0:
            self._set_view(None if (x0, x1) == (fa, fb) else (x0, x1), None)

    def centre(self, t):
        """A zoomed view slides to centre t (as far as the data goes)."""
        if self.xlim is None:
            return
        h = (self.xlim[1] - self.xlim[0]) / 2
        fa, fb = self._full_x()
        a = float(np.clip(t - h, fa, fb - 2 * h))
        self._set_view((a, a + 2 * h), self.ylim)

    # ---------------- drawing a span
    def set_mode(self, mode):
        """Arm drawing a "region" or the background "stretch"; None disarms."""
        self.mode, self.anchor = mode, None
        self._clear_temp()
        self.setCursor(self._cross if mode else Qt.ArrowCursor)
        self.draw_idle()

    def _end_mode(self):
        self.set_mode(None)
        self.modeEnded.emit()

    def _clear_temp(self):
        for a in self._temp:
            a.remove()
        self._temp = []

    def _span(self, a, b, color):
        self._clear_temp()
        self._temp = [self.ax.axvspan(min(a, b), max(a, b), color=color, alpha=0.25, zorder=7)]

    # ---------------- the reading line
    def set_cursor(self, t):
        self.cursor_t = t
        self.redraw()

    def _reading(self):
        """The reading line at cursor_t: the time, the point and the count rate there, of the
        selected run (else the first one shown)."""
        if self.cursor_t is None or not self.state:
            return
        runs, opts, results, sel = self.state[:4]
        run = sel if sel is not None and sel.shown else next((r for r in runs if r.shown), None)
        if run is None:
            return
        i = int(np.clip(np.searchsorted(run.x, self.cursor_t), 0, len(run.x) - 1))
        if i and abs(run.x[i - 1] - self.cursor_t) < abs(run.x[i] - self.cursor_t):
            i -= 1
        t = float(run.x[i])
        y = run.trace()
        b = run.background(y)[0]
        net = y[i] - b[i]
        x, v = next(c for r, c in zip([r for r in runs if r.shown], self._curves) if r is run)
        lines = [run.legend()] if sum(r.shown for r in runs) > 1 else []
        lines.append(f"{t:.3f} min · point {i + 1} / {len(run.x)}")
        if opts.y_mode == "pct_max":
            lines.append(f"{v[i]:.1f} % of max ({net:.0f} cps net)")
        elif opts.y_mode == "pct_total":
            lines.append(f"{v[i]:.2f} % of total per min ({net:.0f} cps net)")
        else:
            lines.append(f"{y[i]:.0f} cps: {net:.0f} cps net, {b[i]:.1f} cps background "
                         "excluded")
        if run.excluded()[i]:
            lines.append(f"spike excluded: {run.y[i]:.0f} cps recorded")
        ax = self.ax
        ax.axvline(t, color="#3d6ea5", lw=1.0, zorder=8)
        ax.plot([t], [v[i]], "o", ms=4, color="#3d6ea5", zorder=8, label="_reading")
        x0, x1 = ax.get_xlim()
        right = t > (x0 + x1) / 2
        ax.annotate("\n".join(lines), (t, 0.99),
                    xycoords=blended_transform_factory(ax.transData, ax.transAxes),
                    xytext=(-5 if right else 5, 0), textcoords="offset points",
                    ha="right" if right else "left", va="top", multialignment="left",
                    fontsize=8, color="#203040",
                    zorder=9, bbox={"boxstyle": "round,pad=0.25", "fc": "#ffffff", "ec": "#a0b0c0",
                                    "alpha": 0.85})

    # ---------------- mouse
    def _sel(self):
        return self.state[3] if self.state else None

    def _edges(self):
        """(index, side, t) of every edge the mouse can take: the selected run's regions, and
        its background stretch (index -1) when it has one."""
        sel = self._sel()
        if sel is None or not sel.shown:
            return []
        out = [(i, side, getattr(r, side)) for i, r in enumerate(sel.regions)
               for side in ("start", "end")]
        if sel.bg_mode == "stretch" and sel.bg_stretch:
            a, b = sorted(sel.bg_stretch)
            out += [(-1, "start", a), (-1, "end", b)]
        return out

    def _edge_at(self, px):
        """(region index, side) of the edge within _EDGE_PX of pixel x, the nearest."""
        best = None
        for i, side, t in self._edges():
            d = abs(self.ax.transData.transform((t, 0))[0] - px)
            if d <= _EDGE_PX and (best is None or d < best[0]):
                best = (d, i, side)
        return best[1:] if best else None

    def _region_at(self, t):
        sel = self._sel()
        if sel is None:
            return -1
        return next((i for i, r in enumerate(sel.regions) if r.start <= t <= r.end), -1)

    def _action(self, button):
        """What a drag with that button does: "zoom" or "pan" (Options › Chromatogram)."""
        c = PREFS["chrom"]
        return {1: c["left_drag"], 3: c["right_drag"]}.get(button, "pan")

    def _on_press(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or not self.state:
            return
        if self._settle_later.isActive():
            self._settle_later.stop()
            self._settle()
        self._finish()
        if ev.dblclick and ev.button == 1 and not self.mode:
            self._press = None
            self.cursor_t = None
            self.redraw()
            self.reset_view()
            return
        if self.mode and ev.button == 1:
            self._press = ("draw", ev.xdata, ev.x)
            return
        if ev.button == 1 and not self.mode:
            edge = self._edge_at(ev.x)
            if edge:
                self._edge = edge
                self._press = ("edge", *edge)
                if edge[0] >= 0:
                    self.regionPicked.emit(edge[0])
                return
        if ev.button in (1, 2, 3):
            self._press = (self._action(ev.button), ev.button, ev.x, ev.y, ev.xdata,
                           self.ax.get_xlim(), self.ax.get_ylim())

    def _on_motion(self, ev):
        if self._press is None:
            if ev.inaxes is self.ax and self.state:
                if self.mode:
                    self.setCursor(self._cross)
                    if self.anchor is not None and ev.xdata is not None:
                        self._span(self.anchor, ev.xdata, self._mode_color())
                        self.draw_idle()
                else:
                    self.setCursor(Qt.SizeHorCursor if self._edge_at(ev.x) else Qt.ArrowCursor)
            else:
                self.unsetCursor()
            return
        kind = self._press[0]
        if kind == "pan":
            self._pan(ev)
            return
        if ev.xdata is None:
            return
        if kind == "edge":
            self._clear_temp()
            self._temp = [self.ax.axvline(ev.xdata, color="#e08000", lw=1.5, zorder=7)]
        elif kind == "zoom":
            self._span(self._press[4], ev.xdata, "#3d6ea5")
        else:                                                    # draw
            a = self.anchor if self.anchor is not None else self._press[1]
            self._span(a, ev.xdata, self._mode_color())
            if self.mode == "region":
                self.dragging.emit(min(a, ev.xdata), max(a, ev.xdata))
        self.draw_idle()

    def _mode_color(self):
        return "#909090" if self.mode == "stretch" else "#e08000"

    def _pan(self, ev):
        """The view follows the drag; past the data it moves only _RUBBER as much."""
        _, _, px0, py0, _, (a, b), (c, d) = self._press
        inv = self.ax.transData.inverted()
        (x0, y0), (x1, y1) = inv.transform((px0, py0)), inv.transform((ev.x, ev.y))
        fa, fb = self._full_x()
        lo, hi = a - (x1 - x0), b - (x1 - x0)
        if lo < fa:
            lo, hi = fa - (fa - lo) * _RUBBER, fa - (fa - lo) * _RUBBER + (b - a)
        elif hi > fb:
            lo, hi = fb + (hi - fb) * _RUBBER - (b - a), fb + (hi - fb) * _RUBBER
        self.xlim = (lo, hi)
        if self.ylim is not None:                                # a zoomed height pans too
            self.ylim = (c - (y1 - y0), d - (y1 - y0))
        self._apply(*self._view())
        self.draw_idle()

    def _on_release(self, ev):
        press, self._press = self._press, None
        self._clear_temp()
        if press is None:
            return
        exact = bool(QApplication.keyboardModifiers() & Qt.AltModifier)
        t = ev.xdata
        kind = press[0]
        if kind == "edge":
            if t is not None:
                self.edgeMoved.emit(press[1], press[2], float(t), exact)
            self.draw_idle()
            return
        if kind == "draw":
            moved = t is not None and abs(ev.x - press[2]) >= _CLICK_PX
            if t is None:
                self.draw_idle()
                return
            if not moved and self.anchor is None:                # the first of two clicks
                self.anchor = press[1]
                self._temp = [self.ax.axvline(press[1], color=self._mode_color(), lw=1.2,
                                              zorder=7)]
                self.draw_idle()
                return
            a = self.anchor if self.anchor is not None else press[1]
            mode = self.mode
            self._end_mode()
            if abs(t - a) > 0:
                if mode == "stretch":
                    self.stretchDrawn.emit(min(a, t), max(a, t))
                else:
                    self.regionDrawn.emit(min(a, t), max(a, t), exact)
            return
        button, px0, py0 = press[1], press[2], press[3]
        if abs(ev.x - px0) >= _CLICK_PX or abs(ev.y - py0) >= _CLICK_PX:
            if kind == "pan":
                self._settle()
            elif t is not None:                                  # zoom to the span
                a, b = sorted((press[4], float(t)))
                self._set_view((a, b), None)
            self.draw_idle()
            return
        self._click(button, press[4])

    def _click(self, button, t):
        if button == 3 and self.mode:
            self._end_mode()
            return
        if button != 1 or self.mode:
            self.draw_idle()
            return
        self.cursor_t = float(t)
        k = self._region_at(t)
        if k != self.state[4]:
            self.regionPicked.emit(k)      # the main window redraws, the line with it
        else:
            self.redraw()
        if PREFS["chrom"]["left_click"] == "centre":
            self.centre(float(t))

    def _on_scroll(self, ev):
        if ev.inaxes is not self.ax or ev.xdata is None or not self.state:
            return
        self._finish()
        f = 1 / 1.25 if ev.button == "up" else 1.25
        x0, x1, y0, y1 = self._view()
        if QApplication.keyboardModifiers() & Qt.ControlModifier:   # the height, from its foot
            self.ylim = (y0, y0 + (y1 - y0) * f)
        else:
            t = ev.xdata
            self.xlim = (t - (t - x0) * f, t + (x1 - t) * f)
            if PREFS["chrom"]["wheel_y"] and ev.ydata is not None:
                v = ev.ydata
                self.ylim = (v - (v - y0) * f, v + (y1 - v) * f)
        self._apply(*self._view())
        self.draw_idle()
        if f > 1:
            self._settle_later.start()     # zoomed out past the data: springs back once still

    def keyPressEvent(self, e):
        sel = self._sel()
        if e.key() in (Qt.Key_Left, Qt.Key_Right) and sel is not None and self._edge:
            i, side = self._edge
            if i < len(sel.regions):
                step = sel.dt_s / 60.0 * (1 if e.key() == Qt.Key_Right else -1)
                now = (getattr(sel.regions[i], side) if i >= 0 else
                       sorted(sel.bg_stretch or [0, 0])[side == "end"])
                self.edgeMoved.emit(i, side, now + step, True)
                return
        if e.key() == Qt.Key_Escape:
            if self.mode:
                self._end_mode()
            elif self.cursor_t is not None:
                self.set_cursor(None)
            return
        super().keyPressEvent(e)
