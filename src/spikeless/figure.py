"""Spikeless - the figure: what Copy and Export make, set and previewed in a window of its own.

Settings on the left — a preset, what it shows, its size in mm, margins, legend, the axes —
the figure on the right exactly as it will be written (zoom with the wheel, double-click to
fit; the checkerboard is transparency). The settings are the session's (saved with it).
"""

from __future__ import annotations

import io

from PySide6.QtCore import QByteArray, QMimeData, Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .options import PREFS, ColorButton, guard_fields
from .plotting import LABELS, PlotOptions, auto_extents, build_figure
from .plotview import Background, ZoomableFigureView

_LEGEND_LOCS = ["upper right", "upper left", "lower right", "lower left", "center right", "best"]
_LINESTYLES = ["solid", "dotted", "dashed", "dashdot"]


def _preset(o: PlotOptions, w, h, font, lw):
    o.plot_w_mm, o.plot_h_mm, o.total_w_mm, o.total_h_mm = w, h, None, None
    o.line_width_pt = lw
    o.legend_font_size = o.label_size = font
    for ax in (o.x, o.y):
        ax.tick_font_size, ax.title_font_size = font, font + 1
        ax.lw_pt = ax.tick_lw_pt = lw * 0.67


PRESETS = {"Article — 80 × 40 mm, 7 pt": (80, 40, 7.0, 0.75),
           "Half page — 120 × 60 mm, 8 pt": (120, 60, 8.0, 0.9),
           "Slide — 160 × 90 mm, 14 pt": (160, 90, 14.0, 1.5)}


# ---------------- making it
def figure(main, opts: PlotOptions | None = None):
    return build_figure(main.runs, opts or main.plot_opts, main.results)


def render(fig, dpi) -> QImage:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    canvas = FigureCanvasAgg(fig)
    old = fig.get_dpi()
    fig.set_dpi(dpi)
    canvas.draw()
    w, h = canvas.get_width_height()
    img = QImage(bytes(canvas.buffer_rgba()), w, h, QImage.Format_RGBA8888).copy()
    fig.set_dpi(old)
    dpm = int(round(dpi / 0.0254))   # embed the resolution: it pastes at its size in mm
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)
    return img


def copy_figure(main):
    if not main.runs:
        return
    fig = figure(main)
    cb = QApplication.clipboard()
    size = f"{fig.get_figwidth() * 25.4:.0f} × {fig.get_figheight() * 25.4:.0f} mm"
    if PREFS["clip_format"] == "svg":
        buf = io.BytesIO()
        fig.savefig(buf, format="svg", facecolor=fig.get_facecolor(), edgecolor="none")
        md = QMimeData()
        md.setData("image/svg+xml", QByteArray(buf.getvalue()))
        md.setText(buf.getvalue().decode("utf-8", "replace"))
        cb.setMimeData(md)
        main.log(f"Figure copied, {size} (SVG).")
    else:
        img = render(fig, PREFS["clip_dpi"])
        cb.setImage(img)
        main.log(f"Figure copied, {size} ({img.width()} × {img.height()} px, "
                 f"{PREFS['clip_dpi']} dpi).")


def export_figure(main, parent=None):
    if not main.runs:
        return
    stem = main.runs[0].name if len(main.runs) == 1 else "chromatograms"
    path, flt = QFileDialog.getSaveFileName(parent or main, "Export figure",
                                            str(main._dir / f"{stem}.png"),
                                            "PNG image (*.png);;SVG vector (*.svg)")
    if not path:
        return
    is_png = path.lower().endswith(".png") or (not path.lower().endswith(".svg") and "png" in flt.lower())
    if not path.lower().endswith((".png", ".svg")):
        path += ".png" if is_png else ".svg"
    fig = figure(main)
    dpi = PREFS["png_dpi"]
    kw = {"facecolor": fig.get_facecolor(), "edgecolor": "none"}
    if is_png:
        kw["pil_kwargs"] = {"dpi": (dpi, dpi)}
    fig.savefig(path, dpi=dpi, **kw)
    main.log(f"Figure exported to {path} ({fig.get_figwidth() * 25.4:.0f} × "
             f"{fig.get_figheight() * 25.4:.0f} mm" + (f", {dpi} dpi)" if is_png else ")"))


# ---------------- the window
class FigureWindow(QMainWindow):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Spikeless — figure")
        self.resize(1100, 720)
        self.preview = ZoomableFigureView()
        self.preview.set_background(Background(**PREFS["background"]))
        self.side = QScrollArea(widgetResizable=True)
        self.side.setFixedWidth(360)
        foot = QHBoxLayout()
        for text, tip, fn in (("Copy", "The figure to the clipboard, at its size in mm (Ctrl+C)",
                               lambda: copy_figure(main)),
                              ("Export…", "PNG or SVG, at its size in mm",
                               lambda: export_figure(main, self))):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            foot.addWidget(b)
        self.size_note = QLabel()
        self.size_note.setStyleSheet("color:#8d8d8d;")
        foot.addWidget(self.size_note, 1)
        QShortcut(QKeySequence.Copy, self, lambda: copy_figure(main))
        root = QWidget()
        v = QVBoxLayout(root)
        h = QHBoxLayout()
        h.addWidget(self.side)
        h.addWidget(self.preview, 1)
        v.addLayout(h, 1)
        v.addLayout(foot)
        self.setCentralWidget(root)
        self._fig = None
        self._loading = False
        self.load()

    def open(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh(self):
        """The preview, after any change to the data or the settings (if shown)."""
        if not self.isVisible():
            return
        self.preview.set_background(Background(**PREFS["background"]))
        if not self.main.runs:
            self._fig = None
            self.preview.clear()
            self.size_note.setText("Nothing loaded.")
            return
        self._fig = figure(self.main)
        self.preview.set_figure(self._fig, keep_view=True)
        self.size_note.setText(f"{self._fig.get_figwidth() * 25.4:.0f} × "
                               f"{self._fig.get_figheight() * 25.4:.0f} mm · PNG "
                               f"{PREFS['png_dpi']} dpi, copy {PREFS['clip_dpi']} dpi "
                               "(Options › Figure)")
        self._fill_auto_fields()

    # ---------------- the settings panel
    def load(self):
        """(Re)build the settings from main.plot_opts: at start, after a preset, and when a
        session brings its own."""
        self.d = {}
        self._loading = True
        o = self.main.plot_opts
        host = QWidget()
        outer = QVBoxLayout(host)

        pre = QComboBox()
        pre.addItem("Preset…")
        pre.addItems(list(PRESETS))
        pre.activated.connect(self._preset)
        outer.addWidget(pre)

        sh = QWidget()
        fs = _cform(sh)
        for key, label in (("show_regions", "Regions (shaded)"), ("show_background",
                           "Background line"), ("show_spikes", "Excluded spikes"),
                           ("show_raw", "Trace as recorded (grey)"), ("legend",
                           "Legend (2 runs or more)")):
            c = QCheckBox(label)
            c.setChecked(getattr(o, key))
            c.toggled.connect(lambda on, k=key: self._set(k, on))
            fs.addRow(c)
        lab = QComboBox()
        lab.addItems(list(LABELS.values()))
        lab.setCurrentIndex(list(LABELS).index(o.region_labels))
        lab.activated.connect(lambda i: self._set("region_labels", list(LABELS)[i]))
        fs.addRow("Region labels", lab)
        self.d["label_size"] = _spin(4, 24, o.label_size, 0.5)
        fs.addRow("Label size (pt)", self.d["label_size"])
        self.d["lw"] = _spin(0.1, 5, o.line_width_pt, 0.1)
        fs.addRow("Line width (pt)", self.d["lw"])
        self.d["alpha"] = _spin(0, 1, o.region_alpha, 0.05)
        fs.addRow("Region opacity", self.d["alpha"])

        pa = QWidget()
        f1 = _cform(pa)
        self.d["w_mm"] = _spin(10, 400, o.plot_w_mm, 1)
        self.d["h_mm"] = _spin(10, 400, o.plot_h_mm, 1)
        self.d["bg"] = ColorButton(o.bg_color, self._apply)
        self.d["bg_a"] = _spin(0, 1, o.bg_alpha, 0.05)
        f1.addRow("Width (mm)", self.d["w_mm"])
        f1.addRow("Height (mm)", self.d["h_mm"])
        f1.addRow("Background", self.d["bg"])
        f1.addRow("Background alpha", self.d["bg_a"])

        mg = QWidget()
        f2 = _cform(mg)
        # total figure size = plot area + label margins; Auto shows the computed value
        tw = _spin(20, 800, o.total_w_mm if o.total_w_mm else o.plot_w_mm, 1)
        tw_auto = QCheckBox("Auto")
        tw_auto.setChecked(o.total_w_mm is None)
        tw.setEnabled(o.total_w_mm is not None)
        th = _spin(20, 800, o.total_h_mm if o.total_h_mm else o.plot_h_mm, 1)
        th_auto = QCheckBox("Auto")
        th_auto.setChecked(o.total_h_mm is None)
        th.setEnabled(o.total_h_mm is not None)
        self.d["tot_w"], self.d["tot_w_auto"] = tw, tw_auto
        self.d["tot_h"], self.d["tot_h_auto"] = th, th_auto
        # a fixed total owns the plot area: grey its field out and report what it works out to
        for auto, spin in ((tw_auto, self.d["w_mm"]), (th_auto, self.d["h_mm"])):
            spin.setEnabled(auto.isChecked())
            auto.toggled.connect(spin.setEnabled)
        tw_auto.toggled.connect(tw.setDisabled)
        th_auto.toggled.connect(th.setDisabled)
        for w in (tw_auto, th_auto):
            w.toggled.connect(self._apply)
        f2.addRow("Total width (mm)", _pair(tw_auto, tw))
        f2.addRow("Total height (mm)", _pair(th_auto, th))
        self.d["out"] = ColorButton(o.outside_color, self._apply)
        self.d["out_a"] = _spin(0, 1, o.outside_alpha, 0.05)
        f2.addRow("Background", self.d["out"])
        f2.addRow("Background alpha", self.d["out_a"])

        lg = QWidget()
        f3 = _cform(lg)
        self.d["leg_loc"] = QComboBox()
        self.d["leg_loc"].addItems(_LEGEND_LOCS)
        self.d["leg_loc"].setCurrentText(o.legend_loc)
        self.d["leg_font"] = QLineEdit(o.legend_font_family)
        self.d["leg_size"] = _spin(4, 24, o.legend_font_size, 0.5)
        f3.addRow("Position", self.d["leg_loc"])
        f3.addRow("Font", self.d["leg_font"])
        f3.addRow("Size", self.d["leg_size"])
        self.d["leg_loc"].currentIndexChanged.connect(self._apply)
        self.d["leg_font"].editingFinished.connect(self._apply)

        for k in ("w_mm", "h_mm", "bg_a", "out_a", "tot_w", "tot_h", "leg_size", "label_size",
                  "lw", "alpha"):
            self.d[k].valueChanged.connect(self._apply)

        outer.addWidget(_Collapsible("Shows", sh, expanded=True))
        outer.addWidget(_Collapsible("Plot area", pa, expanded=True))
        outer.addWidget(_Collapsible("Margins", mg, expanded=False))
        outer.addWidget(_Collapsible("Legend", lg, expanded=False))
        outer.addWidget(_Collapsible("Y axis", self._axis_group("y", o.y), expanded=False))
        outer.addWidget(_Collapsible("X axis", self._axis_group("x", o.x), expanded=False))
        outer.addStretch(1)
        guard_fields(host)
        old = self.side.takeWidget()
        self.side.setWidget(host)
        if old is not None:
            old.deleteLater()
        self._loading = False

    def _set(self, key, value):
        setattr(self.main.plot_opts, key, value)
        self.main.refresh()

    def _preset(self, i):
        if i == 0:
            return
        _preset(self.main.plot_opts, *PRESETS[list(PRESETS)[i - 1]])
        self.load()
        self.main.refresh()

    def _axis_group(self, pfx, ax):
        g = QWidget()
        f = _cform(g)
        t = QLineEdit(ax.title)
        self.d[f"{pfx}_title"] = t
        f.addRow("Axis title", t)
        t.editingFinished.connect(self._apply)
        self._auto_field(f, "Min", pfx, "min", ax.vmin, -1e9, 1e9, 1)
        self._auto_field(f, "Max", pfx, "max", ax.vmax, -1e9, 1e9, 1)
        self._auto_field(f, "Major interval", pfx, "maj", ax.major, 0, 1e9, 0.25)
        self._auto_field(f, "Ticks from", pfx, "gstart", ax.grad_start, -1e9, 1e9, 1)
        self._auto_field(f, "Ticks to", pfx, "gend", ax.grad_end, -1e9, 1e9, 1)
        minor = QCheckBox()
        minor.setChecked(ax.minor_on)
        self.d[f"{pfx}_minor"] = minor
        f.addRow("Minor ticks", minor)
        minor.toggled.connect(self._apply)
        for key, lbl, lo, hi, step in [("lw", "Axis thickness (pt)", 0.1, 3, 0.1),
                                       ("majlen", "Major tick length (mm)", 0, 20, 0.5),
                                       ("minlen", "Minor tick length (mm)", 0, 20, 0.5),
                                       ("tick", "Tick font size", 4, 24, 0.5),
                                       ("tf", "Title font size", 4, 24, 0.5)]:
            val = {"lw": ax.lw_pt, "majlen": ax.major_len_mm, "minlen": ax.minor_len_mm,
                   "tick": ax.tick_font_size, "tf": ax.title_font_size}[key]
            s = _spin(lo, hi, val, step)
            self.d[f"{pfx}_{key}"] = s
            f.addRow(lbl, s)
            s.valueChanged.connect(self._apply)
        tlw = _spin(0.1, 3, ax.tick_lw_pt, 0.1)
        tlw_auto = QCheckBox("Auto (= axis)")
        tlw_auto.setChecked(ax.tick_lw_auto)
        tlw.setEnabled(not ax.tick_lw_auto)
        self.d[f"{pfx}_ticklw"] = tlw
        self.d[f"{pfx}_ticklw_auto"] = tlw_auto
        tlw_auto.toggled.connect(tlw.setDisabled)
        tlw_auto.toggled.connect(self._apply)
        tlw.valueChanged.connect(self._apply)
        f.addRow("Tick thickness (pt)", _pair(tlw_auto, tlw))
        f.addRow(_Collapsible("Advanced", self._axis_advanced(pfx, ax), expanded=False))
        return g

    def _axis_advanced(self, pfx, ax):
        g = QWidget()
        f = _cform(g)
        f.setContentsMargins(0, 0, 0, 0)
        tp = _spin(0, 20, ax.title_pad_mm, 0.1)
        lp = _spin(0, 20, ax.tick_label_pad_mm, 0.1)
        self.d[f"{pfx}_titlepad"] = tp
        self.d[f"{pfx}_lblpad"] = lp
        f.addRow("Title ↔ labels (mm)", tp)
        f.addRow("Labels ↔ axis (mm)", lp)
        grid = QCheckBox()
        grid.setChecked(ax.grid_on)
        gstyle = QComboBox()
        gstyle.addItems(_LINESTYLES)
        gstyle.setCurrentText(ax.grid_style)
        gcolor = ColorButton(ax.grid_color, self._apply)
        gwidth = _spin(0.1, 3, ax.grid_width, 0.1)
        self.d[f"{pfx}_grid"] = grid
        self.d[f"{pfx}_gridstyle"] = gstyle
        self.d[f"{pfx}_gridcolor"] = gcolor
        self.d[f"{pfx}_gridwidth"] = gwidth
        f.addRow("Grid", grid)
        f.addRow("Grid style", gstyle)
        f.addRow("Grid colour", gcolor)
        f.addRow("Grid width (pt)", gwidth)
        for wdg in (tp, lp, gwidth):
            wdg.valueChanged.connect(self._apply)
        grid.toggled.connect(self._apply)
        gstyle.currentIndexChanged.connect(self._apply)
        return g

    def _auto_field(self, form, label, pfx, name, value, lo, hi, step):
        chk = QCheckBox("Auto")
        chk.setChecked(value is None)
        spin = _spin(lo, hi, value if value is not None else 0.0, step)
        spin.setEnabled(value is not None)
        self.d[f"{pfx}_{name}"] = spin
        self.d[f"{pfx}_{name}_auto"] = chk
        chk.toggled.connect(spin.setDisabled)
        chk.toggled.connect(self._apply)
        spin.valueChanged.connect(self._apply)
        form.addRow(label, _pair(chk, spin))

    def _apply(self, *_):
        if self._loading or not self.d:
            return
        o, d = self.main.plot_opts, self.d
        o.plot_w_mm, o.plot_h_mm = d["w_mm"].value(), d["h_mm"].value()
        o.total_w_mm = None if d["tot_w_auto"].isChecked() else d["tot_w"].value()
        o.total_h_mm = None if d["tot_h_auto"].isChecked() else d["tot_h"].value()
        o.bg_color, o.bg_alpha = d["bg"].color, d["bg_a"].value()
        o.outside_color, o.outside_alpha = d["out"].color, d["out_a"].value()
        o.legend_loc = d["leg_loc"].currentText()
        o.legend_font_family = d["leg_font"].text() or "sans-serif"
        o.legend_font_size = d["leg_size"].value()
        o.label_size, o.line_width_pt = d["label_size"].value(), d["lw"].value()
        o.region_alpha = d["alpha"].value()
        for ax, pfx in ((o.x, "x"), (o.y, "y")):
            ax.title = d[f"{pfx}_title"].text()
            ax.vmin = None if d[f"{pfx}_min_auto"].isChecked() else d[f"{pfx}_min"].value()
            ax.vmax = None if d[f"{pfx}_max_auto"].isChecked() else d[f"{pfx}_max"].value()
            ax.major = None if d[f"{pfx}_maj_auto"].isChecked() else d[f"{pfx}_maj"].value()
            ax.grad_start = None if d[f"{pfx}_gstart_auto"].isChecked() else d[f"{pfx}_gstart"].value()
            ax.grad_end = None if d[f"{pfx}_gend_auto"].isChecked() else d[f"{pfx}_gend"].value()
            ax.minor_on = d[f"{pfx}_minor"].isChecked()
            ax.lw_pt = d[f"{pfx}_lw"].value()
            ax.major_len_mm = d[f"{pfx}_majlen"].value()
            ax.minor_len_mm = d[f"{pfx}_minlen"].value()
            ax.tick_lw_auto = d[f"{pfx}_ticklw_auto"].isChecked()
            ax.tick_lw_pt = d[f"{pfx}_ticklw"].value()
            ax.tick_font_size = d[f"{pfx}_tick"].value()
            ax.title_font_size = d[f"{pfx}_tf"].value()
            ax.title_pad_mm = d[f"{pfx}_titlepad"].value()
            ax.tick_label_pad_mm = d[f"{pfx}_lblpad"].value()
            ax.grid_on = d[f"{pfx}_grid"].isChecked()
            ax.grid_style = d[f"{pfx}_gridstyle"].currentText()
            ax.grid_color = d[f"{pfx}_gridcolor"].color
            ax.grid_width = d[f"{pfx}_gridwidth"].value()
        self.main.refresh()

    def _fill_auto_fields(self):
        """Ticked Auto fields show, greyed, the value Auto uses; a fixed total size shows the
        plot area it leaves."""
        if not self.main.runs or not self.d or self._fig is None:
            return
        ex = auto_extents(self.main.runs, self.main.plot_opts)
        self._loading = True
        for k, v in (("x_min", ex["xmin"]), ("x_max", ex["xmax"]), ("x_maj", ex["xmajor"]),
                     ("x_gstart", ex["xmin"]), ("x_gend", ex["xmax"]),
                     ("y_min", ex["ymin"]), ("y_max", ex["ymax"]), ("y_maj", ex["ymajor"]),
                     ("y_gstart", ex["ymin"]), ("y_gend", ex["ymax"])):
            if self.d[f"{k}_auto"].isChecked():
                self.d[k].setValue(v)
        if self.d["tot_w_auto"].isChecked():
            self.d["tot_w"].setValue(self._fig.get_figwidth() * 25.4)
        if self.d["tot_h_auto"].isChecked():
            self.d["tot_h"].setValue(self._fig.get_figheight() * 25.4)
        pw, ph = self._fig.plot_area_mm
        if not self.d["tot_w_auto"].isChecked():
            self.d["w_mm"].setValue(pw)
        if not self.d["tot_h_auto"].isChecked():
            self.d["h_mm"].setValue(ph)
        self._loading = False


# ---------------- small widgets (also used by app.py)
class _Collapsible(QWidget):
    def __init__(self, title, content, expanded=True):
        super().__init__()
        from PySide6.QtWidgets import QToolButton
        self._btn = QToolButton()
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._btn.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self._btn.toggled.connect(self._on_toggled)
        self._content = content
        self._content.setVisible(expanded)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._btn)
        lay.addWidget(self._content)

    def set_title(self, text):
        self._btn.setText(text)

    def _on_toggled(self, on):
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


def _cform(w):
    f = QFormLayout(w)
    f.setVerticalSpacing(4)
    f.setContentsMargins(6, 4, 6, 4)
    return f


def _spin(lo, hi, val, step):
    from PySide6.QtWidgets import QDoubleSpinBox
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(2 if step < 1 else 0)
    s.setValue(val)
    return s


def _pair(left, right):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(left)
    h.addWidget(right, 1)
    return w
