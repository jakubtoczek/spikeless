"""Spikeless - the figure: what Copy and Export make, set and previewed in a window of its own.

Settings on the left, each section folded until opened — a preset, the size in mm, the font,
the traces, the regions, the legend (inside or outside the plot: outside, the figure grows for
it), the backgrounds, each axis (its title, range, major and minor ticks, grid) — the figure on
the right exactly as it will be written (zoom with the wheel, double-click to fit; the
checkerboard is transparency). The settings are the session's (saved with it).
"""

from __future__ import annotations

import io

from PySide6.QtCore import QByteArray, QMimeData, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .options import PREFS
from .plotting import DASHES, LEGEND, PlotOptions, build_figure, legend_text
from .plotview import Background, ZoomableFigureView
from .run import COLORS
from .widgets import Collapsible, ColorButton, guard_fields, link, pick_color

_LINESTYLES = ["solid", "dotted", "dashed", "dashdot"]
_DIRS = {"out": "Out", "in": "In", "inout": "Across"}


def apply_size(o: PlotOptions, total_w, w, h, font, lw, labels):
    """total_w: the whole figure's width (a journal's column, or a share of it), the plot area
    what is left; None: the plot area w × h. labels: the regions' labels, pt."""
    o.plot_w_mm, o.plot_h_mm, o.total_w_mm, o.total_h_mm = w, h, total_w, None
    o.line_width_pt = lw
    o.legend_font_size, o.label_size, o.title_size = font, labels, font + 1
    for ax in (o.x, o.y):
        ax.tick_font_size, ax.title_font_size = font, font + 1
        ax.lw_pt = ax.tick_lw_pt = round(lw * 2 / 3, 2)


def apply_style(main, bw):
    """Every run's colour, line and fill, and the regions' shading: in colour — each run its
    own, solid — or in black and white, as Flowless — each run black, its own dashes, the
    shading grey. The runs shown first, in their order."""
    runs = [r for r in main.runs if r.shown] + [r for r in main.runs if not r.shown]
    for i, r in enumerate(runs):
        r.color = "#000000" if bw else COLORS[i % len(COLORS)]
        r.dash = list(DASHES)[i % len(DASHES)] if bw else "solid"
        r.width, r.fill = None, 0.0
        for g in r.regions:
            g.color = None
    main.plot_opts.region_alpha = 0.2 if bw else 0.3


# Journals' columns: single 80–90 mm (Springer 84, ACS 82.5, Elsevier 90), double 170–190 mm
# (Springer 174, ACS 178, Elsevier 190). 80 mm fits any single column, and two side by side
# fit any double one with a gap; 55 mm, three; 170 mm, any double column.
# ponytail: one panel per figure; a multi-panel figure is for later
# The first is the default (PlotOptions' own).
SIZES = {"Panel — 1 column, or ½ of a 2-column figure: 80 mm wide, 7 pt":
           (80, 65, 40, 7.0, 0.75, 6.0),
           "Panel — ⅓ of a 2-column figure: 55 mm wide, 7 pt": (55, 41, 32, 7.0, 0.6, 6.0),
           "Figure — the full 2-column width: 170 mm wide, 7 pt":
           (170, 155, 60, 7.0, 0.75, 7.0),
           "Slide — plot 160 × 90 mm, 14 pt": (None, 160, 90, 14.0, 1.5, 14.0)}
STYLES = {"Colour — each run its colour, solid lines": False,
          "Black and white — each run its dashes, grey shading": True}


def _fonts():
    """What matplotlib can write: the generic families, then every installed font."""
    from matplotlib import font_manager
    return ["sans-serif", "serif"] + sorted(set(font_manager.get_font_names()))


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
        self.side.setFixedWidth(420)
        self.side.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        self._sections = []
        self._open = set()               # the sections unfolded, kept when the panel is rebuilt
        self._run_ids = None             # the runs the Traces table has rows for
        # the preview (a figure, then an SVG of it: 80 ms and more) once a burst of changes ends
        self._later = QTimer(self, singleShot=True, interval=120, timeout=self.refresh)
        self.load()

    def open(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh_later(self):
        if self.isVisible():
            self._later.start()

    def refresh(self):
        """The preview, after any change to the data or the settings (if shown)."""
        if not self.isVisible():
            return
        self._later.stop()
        self._fill_runs()
        n = sum(r.shown for r in self.main.runs)
        leg = self.d["legend"]                       # no legend for one run: unticked, greyed
        leg.blockSignals(True)
        leg.setChecked(self.main.plot_opts.legend and n >= 2)
        leg.setEnabled(n >= 2)
        leg.blockSignals(False)
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
        if self._sections:
            self._open = {s._btn.text() for s in self._sections if s._btn.isChecked()}
        self._sections = []
        self.d = {}
        self._loading = True
        o = self.main.plot_opts
        host = QWidget()
        outer = QVBoxLayout(host)

        presets = QHBoxLayout()
        for name, items, slot, tip in (
                ("Size…", SIZES, self._size, "Sizes for a journal: 80 mm fits any single "
                 "column, and two side by side any double column; 55 mm, three side by side "
                 "(the first: a new figure's)"),
                ("Style…", STYLES, self._style, "Every run's colour, line and fill, and the "
                 "regions' shading (Ctrl+Z gives them back)")):
            c = QComboBox()
            c.addItem(name)
            c.addItems(list(items))
            c.setToolTip(tip)
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(8)            # side by side in the panel; the list is wide
            c.view().setMinimumWidth(c.view().sizeHintForColumn(0) + 24)
            c.activated.connect(slot)
            presets.addWidget(c, 1)
        outer.addLayout(presets)

        # size
        sz, f = _section()
        self.d["w_mm"] = _spin(10, 400, o.plot_w_mm, 1)
        self.d["h_mm"] = _spin(10, 400, o.plot_h_mm, 1)
        f.addRow("Plot area width (mm)", self.d["w_mm"])
        f.addRow("Plot area height (mm)", self.d["h_mm"])
        for key, val, plot in (("tot_w", o.total_w_mm, "w_mm"), ("tot_h", o.total_h_mm, "h_mm")):
            spin = _spin(20, 800, val or getattr(o, f"plot_{plot[0]}_mm"), 1)
            auto = QCheckBox("Auto")
            auto.setToolTip("The plot area plus the room its labels (and a legend outside) "
                            "take; fixed, the plot area is what is left")
            auto.setChecked(val is None)
            spin.setEnabled(val is not None)
            self.d[plot].setEnabled(val is None)       # a fixed total owns the plot area
            auto.toggled.connect(spin.setDisabled)
            auto.toggled.connect(self.d[plot].setEnabled)
            auto.toggled.connect(self._apply)
            self.d[key], self.d[f"{key}_auto"] = spin, auto
            f.addRow("Whole figure " + ("width" if key == "tot_w" else "height") + " (mm)",
                     _pair(auto, spin))

        # text
        tx, f = _section()
        font = QComboBox()
        font.setEditable(True)
        font.addItems(_fonts())
        font.setCurrentText(o.font)
        font.setToolTip("Every text of the figure: its axes, labels and legend")
        font.activated.connect(self._apply)
        font.lineEdit().editingFinished.connect(self._apply)
        self.d["font"] = font
        f.addRow("Font", font)
        self.d["title"] = QLineEdit(o.title)
        self.d["title"].setPlaceholderText("none")
        self.d["title"].setToolTip("Above the plot (a panel's name); the figure grows for it")
        self.d["title"].editingFinished.connect(self._apply)
        f.addRow("Title", self.d["title"])
        self.d["title_size"] = _spin(4, 30, o.title_size, 0.5)
        f.addRow("Title size (pt)", self.d["title_size"])

        # traces
        tr, f = _section()
        self.d["lw"] = _spin(0.1, 5, o.line_width_pt, 0.1)
        f.addRow("Line width (pt)", self.d["lw"])
        self.runs_t = _runs_table(self._run_clicked)
        f.addRow(self.runs_t)
        self._run_ids = None
        for key, label in (("show_background", "Background line"),
                           ("show_spikes", "Excluded spikes"),
                           ("show_raw", "Trace as recorded (its style: Options › Chromatogram)")):
            f.addRow(self._tick(key, label, o))

        # regions
        rg, f = _section()
        f.addRow(self._tick("show_regions", "Shaded", o))
        labels = self._tick("label_name", "Name", o), self._tick("label_pct", "% of total", o),             self._tick("label_rt", "Rt", o)
        labels[0].setToolTip("A region's own name (typed, or its method's); not \"peak N\"")
        f.addRow("Labels", _row(*labels))
        self.d["label_size"] = _spin(4, 24, o.label_size, 0.5)
        f.addRow("Label size (pt)", self.d["label_size"])
        self.d["alpha"] = _spin(0, 1, o.region_alpha, 0.05)
        f.addRow("Opacity", self.d["alpha"])
        f.addRow("Each region", link("edit", "⤢", "#7fb2e5", self.main.regions_window,
                                      "Its colour, its label on or off, its note"))

        # legend
        lg, f = _section()
        self.d["legend"] = self._tick("legend", "Shown", o)
        self.d["legend"].setToolTip("The runs' names; greyed with one run on the figure")
        f.addRow(self.d["legend"])
        self.d["leg_loc"] = QComboBox()
        for key in LEGEND:
            self.d["leg_loc"].addItem(legend_text(key), key)
        self.d["leg_loc"].setCurrentIndex(max(0, self.d["leg_loc"].findData(o.legend_loc)))
        self.d["leg_loc"].setToolTip("Outside the plot, the figure grows to hold it (or, its "
                                     "whole size fixed, the plot area shrinks)")
        self.d["leg_loc"].currentIndexChanged.connect(self._apply)
        self.d["leg_dx"] = _spin(-200, 200, o.legend_dx_mm, 0.5)
        self.d["leg_dy"] = _spin(-200, 200, o.legend_dy_mm, 0.5)
        self.d["leg_size"] = _spin(4, 24, o.legend_font_size, 0.5)
        f.addRow("Position", self.d["leg_loc"])
        f.addRow("Then right (mm)", self.d["leg_dx"])
        f.addRow("Then up (mm)", self.d["leg_dy"])
        f.addRow("Size (pt)", self.d["leg_size"])
        f.addRow("Labels", link("edit", "▤", "#4caf50", self.main.names_window,
                                "What the legend calls each run (Run names)"))

        # backgrounds
        bg, f = _section()
        self.d["bg"] = ColorButton(o.bg_color, self._apply)
        self.d["bg_a"] = _spin(0, 1, o.bg_alpha, 0.05)
        self.d["out"] = ColorButton(o.outside_color, self._apply)
        self.d["out_a"] = _spin(0, 1, o.outside_alpha, 0.05)
        f.addRow("Plot area", self.d["bg"])
        f.addRow("   opacity", self.d["bg_a"])
        f.addRow("Around it", self.d["out"])
        f.addRow("   opacity", self.d["out_a"])

        for k in ("w_mm", "h_mm", "bg_a", "out_a", "tot_w", "tot_h", "leg_size", "label_size",
                  "lw", "alpha", "leg_dx", "leg_dy", "title_size"):
            self.d[k].valueChanged.connect(self._apply)

        for title, body in (("Size", sz), ("Text", tx), ("Traces", tr), ("Regions", rg),
                            ("Legend", lg), ("Backgrounds", bg),
                            ("X axis", self._axis_group("x", o.x)),
                            ("Y axis", self._axis_group("y", o.y))):
            s = Collapsible(title, body, expanded=title in self._open)
            self._sections.append(s)
            outer.addWidget(s)
        outer.addStretch(1)
        guard_fields(host)
        old = self.side.takeWidget()
        self.side.setWidget(host)
        if old is not None:
            old.deleteLater()
        self._loading = False

    def _tick(self, key, label, o):
        c = QCheckBox(label)
        c.setChecked(getattr(o, key))
        c.toggled.connect(lambda on: self._set(key, on))
        return c

    def _set(self, key, value):
        setattr(self.main.plot_opts, key, value)
        self.main.refresh()

    def _size(self, i):
        if i:
            apply_size(self.main.plot_opts, *SIZES[list(SIZES)[i - 1]])
            self.load()
            self.main.refresh()

    def _style(self, i):
        if i and self.main.runs:
            self.main._push("figure style")
            apply_style(self.main, list(STYLES.values())[i - 1])
            self.load()
            self.main.refresh()

    # ---------------- each run's line (Traces)
    def _fill_runs(self):
        """The Traces table: a row per run — its colour, name, line, width, fill. Rebuilt
        when the runs change; its fields act on the run in their row at the time."""
        runs, t = self.main.runs, self.runs_t
        set_run = self.main.set_run

        def on(k, key, conv):
            return lambda v: k < len(self.main.runs) and set_run(self.main.runs[k], key, conv(v))

        if [r.id for r in runs] != self._run_ids:
            self._run_ids = [r.id for r in runs]
            t.setRowCount(len(runs))
            for k in range(len(runs)):
                line = QComboBox()
                line.addItems(list(DASHES))
                line.activated.connect(on(k, "dash", lambda i: list(DASHES)[i]))
                width = _spin(0, 5, 0, 0.1)
                width.setSpecialValueText("Auto")
                width.valueChanged.connect(on(k, "width", lambda v: v or None))
                fill = _spin(0, 1, 0, 0.05)
                fill.setSpecialValueText("None")
                fill.valueChanged.connect(on(k, "fill", float))
                for c, wdg, px in ((2, line, 104), (3, width, 60), (4, fill, 60)):
                    wdg.setFixedWidth(px)           # the table fits the panel
                    t.setCellWidget(k, c, wdg)
            guard_fields(t)
            t.setFixedHeight(t.horizontalHeader().sizeHint().height()
                             + 24 * max(1, min(len(runs), 8)) + 4)
        for k, r in enumerate(runs):
            pm = QPixmap(12, 12)
            pm.fill(QColor(r.color))
            sw = QTableWidgetItem(QIcon(pm), "")
            sw.setFlags(Qt.ItemIsEnabled)
            t.setItem(k, 0, sw)
            name = QTableWidgetItem(r.legend())
            name.setFlags(Qt.ItemIsEnabled)
            if not r.shown:
                name.setForeground(QColor("#8d8d8d"))
            t.setItem(k, 1, name)
            for c, value in ((2, list(DASHES).index(r.dash) if r.dash in DASHES else 0),
                             (3, r.width or 0.0), (4, r.fill)):
                wdg = t.cellWidget(k, c)
                wdg.blockSignals(True)
                (wdg.setCurrentIndex if c == 2 else wdg.setValue)(value)
                wdg.blockSignals(False)

    def _run_clicked(self, row, col):
        if col == 0 and row < len(self.main.runs):
            run = self.main.runs[row]
            c = pick_color(self, run.color)
            if c:
                self.main.set_run(run, "color", c)

    def _axis_group(self, p, ax):
        g, f = _section()
        _head(f, "Title")
        t = QLineEdit(ax.title)
        t.editingFinished.connect(self._apply)
        self.d[f"{p}_title"] = t
        f.addRow("Text", t)
        self._num(f, p, "tf", "Size (pt)", ax.title_font_size, 4, 24, 0.5)
        self._num(f, p, "titlepad", "Gap to the labels (mm)", ax.title_pad_mm, 0, 20, 0.1)
        _head(f, "Range")
        self._auto_field(f, "From", p, "min", ax.vmin, -1e9, 1e9, 1)
        self._auto_field(f, "To", p, "max", ax.vmax, -1e9, 1e9, 1)
        self._num(f, p, "lw", "Axis line (pt)", ax.lw_pt, 0.1, 3, 0.1)
        _head(f, "Major ticks")
        self._auto_field(f, "Every", p, "maj", ax.major, 0, 1e9, 0.25)
        self._auto_field(f, "First", p, "gstart", ax.grad_start, -1e9, 1e9, 1)
        self._auto_field(f, "Last", p, "gend", ax.grad_end, -1e9, 1e9, 1)
        d = QComboBox()
        for key, text in _DIRS.items():
            d.addItem(text, key)
        d.setCurrentIndex(max(0, d.findData(ax.tick_dir)))
        d.currentIndexChanged.connect(self._apply)
        self.d[f"{p}_dir"] = d
        f.addRow("Direction (both)", d)
        self._num(f, p, "majlen", "Length (mm)", ax.major_len_mm, 0, 20, 0.5)
        tlw = _spin(0.1, 3, ax.tick_lw_pt, 0.1)
        tlw_auto = QCheckBox("Auto (= axis)")
        tlw_auto.setChecked(ax.tick_lw_auto)
        tlw.setEnabled(not ax.tick_lw_auto)
        tlw_auto.toggled.connect(tlw.setDisabled)
        tlw_auto.toggled.connect(self._apply)
        tlw.valueChanged.connect(self._apply)
        self.d[f"{p}_ticklw"], self.d[f"{p}_ticklw_auto"] = tlw, tlw_auto
        f.addRow("Thickness (pt)", _pair(tlw_auto, tlw))
        self._num(f, p, "tick", "Labels size (pt)", ax.tick_font_size, 4, 24, 0.5)
        if p == "y":
            small = QCheckBox("6 pt for counts ≥ 100, 80 mm wide or less")
            small.setToolTip("Counts of 3 digits or more take a narrow figure's width: on a "
                             "figure 80 mm wide or less, their labels are 6 pt at most")
            small.setChecked(ax.small_counts)
            small.toggled.connect(self._apply)
            self.d["y_small"] = small
            f.addRow("", small)
        self._num(f, p, "lblpad", "Labels gap (mm)", ax.tick_label_pad_mm, 0, 20, 0.1)
        _head(f, "Minor ticks")
        minor = QCheckBox("Shown")
        minor.setChecked(bool(ax.minor_on))
        minor.setEnabled(ax.minor_on is not None)
        minor.toggled.connect(self._apply)
        minor_auto = QCheckBox("Auto")
        minor_auto.setToolTip("On the time axis when they mark whole minutes, 4 between two "
                              "majors (majors every 5 or 10 min); off on the other")
        minor_auto.setChecked(ax.minor_on is None)
        minor_auto.toggled.connect(minor.setDisabled)
        minor_auto.toggled.connect(self._apply)
        self.d[f"{p}_minor"], self.d[f"{p}_minor_auto"] = minor, minor_auto
        f.addRow(_pair(minor_auto, minor))
        mn = _spin(0, 20, ax.minor_n or 0, 1)
        mn.setSpecialValueText("Auto")
        mn.setToolTip("Minor intervals per major one (Auto: 5; 4 for a major of 2 or 20; 3 for "
                      "15; 6 for 30 or 60)")
        mn.valueChanged.connect(self._apply)
        self.d[f"{p}_minorn"] = mn
        f.addRow("Per major interval", mn)
        self._num(f, p, "minlen", "Length (mm)", ax.minor_len_mm, 0, 20, 0.5)
        self._auto_field(f, "Thickness (pt)", p, "minlw", ax.minor_lw_pt, 0.05, 3, 0.05,
                         "Auto (= major)")
        _head(f, "Grid")
        for tag, title, on, style, color, width in (
                ("grid", "At the major ticks", ax.grid_on, ax.grid_style, ax.grid_color,
                 ax.grid_width),
                ("mgrid", "At the minor ticks", ax.minor_grid_on, ax.minor_grid_style,
                 ax.minor_grid_color, ax.minor_grid_width)):
            grid = QCheckBox(title)
            grid.setChecked(on)
            grid.toggled.connect(self._apply)
            gstyle = QComboBox()
            gstyle.addItems(_LINESTYLES)
            gstyle.setCurrentText(style)
            gstyle.currentIndexChanged.connect(self._apply)
            gcolor = ColorButton(color, self._apply)
            gwidth = _spin(0.1, 3, width, 0.1)
            gwidth.valueChanged.connect(self._apply)
            self.d[f"{p}_{tag}"] = grid
            self.d[f"{p}_{tag}style"] = gstyle
            self.d[f"{p}_{tag}color"] = gcolor
            self.d[f"{p}_{tag}width"] = gwidth
            f.addRow(grid)
            f.addRow("   line", gstyle)
            f.addRow("   colour", gcolor)
            f.addRow("   width (pt)", gwidth)
        return g

    def _num(self, form, p, name, label, value, lo, hi, step):
        s = _spin(lo, hi, value, step)
        s.valueChanged.connect(self._apply)
        self.d[f"{p}_{name}"] = s
        form.addRow(label, s)

    def _auto_field(self, form, label, pfx, name, value, lo, hi, step, auto="Auto"):
        chk = QCheckBox(auto)
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

        def val(k):                          # None when its Auto is ticked
            return None if d[f"{k}_auto"].isChecked() else d[k].value()

        o.plot_w_mm, o.plot_h_mm = d["w_mm"].value(), d["h_mm"].value()
        o.total_w_mm, o.total_h_mm = val("tot_w"), val("tot_h")
        o.font = d["font"].currentText().strip() or "sans-serif"
        o.title, o.title_size = d["title"].text(), d["title_size"].value()
        o.bg_color, o.bg_alpha = d["bg"].color, d["bg_a"].value()
        o.outside_color, o.outside_alpha = d["out"].color, d["out_a"].value()
        o.legend_loc = d["leg_loc"].currentData()
        o.legend_dx_mm, o.legend_dy_mm = d["leg_dx"].value(), d["leg_dy"].value()
        o.legend_font_size = d["leg_size"].value()
        o.label_size, o.line_width_pt = d["label_size"].value(), d["lw"].value()
        o.region_alpha = d["alpha"].value()
        for ax, p in ((o.x, "x"), (o.y, "y")):
            ax.title = d[f"{p}_title"].text()
            ax.title_font_size = d[f"{p}_tf"].value()
            ax.title_pad_mm = d[f"{p}_titlepad"].value()
            ax.vmin, ax.vmax = val(f"{p}_min"), val(f"{p}_max")
            ax.lw_pt = d[f"{p}_lw"].value()
            ax.major = val(f"{p}_maj")
            ax.grad_start, ax.grad_end = val(f"{p}_gstart"), val(f"{p}_gend")
            ax.tick_dir = d[f"{p}_dir"].currentData()
            ax.major_len_mm = d[f"{p}_majlen"].value()
            ax.tick_lw_auto = d[f"{p}_ticklw_auto"].isChecked()
            ax.tick_lw_pt = d[f"{p}_ticklw"].value()
            ax.tick_font_size = d[f"{p}_tick"].value()
            ax.tick_label_pad_mm = d[f"{p}_lblpad"].value()
            ax.minor_on = (None if d[f"{p}_minor_auto"].isChecked()
                           else d[f"{p}_minor"].isChecked())
            ax.minor_n = int(d[f"{p}_minorn"].value()) or None
            ax.minor_len_mm = d[f"{p}_minlen"].value()
            ax.minor_lw_pt = val(f"{p}_minlw")
            ax.grid_on = d[f"{p}_grid"].isChecked()
            ax.grid_style = d[f"{p}_gridstyle"].currentText()
            ax.grid_color = d[f"{p}_gridcolor"].color
            ax.grid_width = d[f"{p}_gridwidth"].value()
            ax.minor_grid_on = d[f"{p}_mgrid"].isChecked()
            ax.minor_grid_style = d[f"{p}_mgridstyle"].currentText()
            ax.minor_grid_color = d[f"{p}_mgridcolor"].color
            ax.minor_grid_width = d[f"{p}_mgridwidth"].value()
        o.y.small_counts = d["y_small"].isChecked()
        self.main.refresh()

    def _fill_auto_fields(self):
        """Ticked Auto fields show, greyed, the value Auto uses; a fixed total size shows the
        plot area it leaves."""
        if not self.main.runs or not self.d or self._fig is None:
            return
        o = self.main.plot_opts
        ex = self._fig.auto
        self._loading = True
        for p in ("x", "y"):
            if self.d[f"{p}_minor_auto"].isChecked():
                self.d[f"{p}_minor"].setChecked(ex[f"{p}minor"])
        for k, v in (("x_min", ex["xmin"]), ("x_max", ex["xmax"]), ("x_maj", ex["xmajor"]),
                     ("x_gstart", ex["xmin"]), ("x_gend", ex["xmax"]),
                     ("y_min", ex["ymin"]), ("y_max", ex["ymax"]), ("y_maj", ex["ymajor"]),
                     ("y_gstart", ex["ymin"]), ("y_gend", ex["ymax"]),
                     ("x_minlw", o.x.lw_pt if o.x.tick_lw_auto else o.x.tick_lw_pt),
                     ("y_minlw", o.y.lw_pt if o.y.tick_lw_auto else o.y.tick_lw_pt),
                     ("tot_w", self._fig.get_figwidth() * 25.4),
                     ("tot_h", self._fig.get_figheight() * 25.4)):
            if self.d[f"{k}_auto"].isChecked():
                self.d[k].setValue(v)
        pw, ph = self._fig.plot_area_mm
        if not self.d["tot_w_auto"].isChecked():
            self.d["w_mm"].setValue(pw)
        if not self.d["tot_h_auto"].isChecked():
            self.d["h_mm"].setValue(ph)
        self._loading = False


def _section():
    w = QWidget()
    return w, _cform(w)


def _head(form, text):
    """A sub-heading inside a section."""
    lab = QLabel(f"<b>{text}</b>")
    lab.setStyleSheet("color:#b8c8d8; margin-top:6px;")
    form.addRow(lab)


# ---------------- small widgets
def _runs_table(on_click):
    t = QTableWidget(0, 5)
    t.setHorizontalHeaderLabels(["", "Run", "Line", "Width (pt)", "Fill"])
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(24)
    t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    for c in (0, 2, 3, 4):
        t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
    t.setShowGrid(False)
    t.setSelectionMode(QTableWidget.NoSelection)
    t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)   # the panel's width, not its own
    t.setToolTip("Each run: click its swatch for its colour; its line; its width (Auto: the "
                 "line width above); a fill under its trace, its opacity (None: no fill). "
                 "Grey: not shown. On screen too.")
    t.cellClicked.connect(on_click)
    return t


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


def _row(*widgets):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for wdg in widgets:
        h.addWidget(wdg)
    h.addStretch(1)
    return w


def _pair(left, right):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(left)
    h.addWidget(right, 1)
    return w
