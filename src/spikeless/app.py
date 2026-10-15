"""Spikeless main window: one screen, four steps.

The chromatogram in the middle, its results under it (the log in a tab beside them), and the
steps on the right, top to bottom — ① Runs, ② Spikes, ③ Background, ④ Regions — each acting
on the selected run (with none selected, they wait for one). Every change to a run is one undo
step (Ctrl+Z / Ctrl+Y), named in the log.
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import __version__, io_gina, io_paste, session
from .canvas import ChromCanvas
from .editors import NamesWindow, RegionsWindow, copy_table
from .figure import FigureWindow, _Collapsible, _link, copy_figure, export_figure
from .options import PREFS, ColorButton, OptionsWindow, guard_fields, load_prefs, method_names
from .peaks import find_regions, fit, measure, snap
from .plotting import Y_MODES, PlotOptions
from .report import HELP, ReportWindow, columns, rows as result_rows
from .run import COLORS, FindParams, Region
from .spikes import SpikeParams, remove

APP_NAME = "Spikeless"
OPENS = (".txt", session.EXT, ".json")      # what Open… and a drop take
GREY = "color:#8d8d8d;"
TITLES = {"spikes": "② Spikes", "background": "③ Background", "peaks": "④ Regions"}


class MainWindow(QMainWindow):
    def __init__(self):
        # a dot for decimals in every field, whatever Windows' region says: set before the
        # window exists, which every field inherits its locale from
        # ponytail: the C locale for all; a locale option when someone wants a comma back
        QLocale.setDefault(QLocale.c())
        super().__init__()
        self._title = f"{APP_NAME} {__version__} — radio-HPLC: spikes, peaks, report"
        self.setWindowTitle(self._title)
        self.resize(1400, 880)
        self.setAcceptDrops(True)
        icon = _app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        load_prefs()
        self.runs: list = []
        self.sel = None                  # the run the steps act on, or None
        self.sel_region = -1             # its selected region, or -1
        self.results: dict = {}          # run.id -> peaks.Results
        self.plot_opts = PlotOptions()   # the figure (Figure window); saved with the session
        self.view = {"raw": False, "spikes": True, "background": True}   # screen only
        self._undo: list = []
        self._redo: list = []
        self._session_path: Path | None = None
        self._dir = Path.home()          # where file dialogs open: the last file's folder
        self._paste_n = 0
        self._filling = False
        self.options_win = self.report_win = self.figure_win = None
        self.names_win = self.regions_win = None
        self._build()
        for key, slot in ((QKeySequence.Undo, self._undo_step), (QKeySequence.Redo, self._redo_step),
                          (QKeySequence.Copy, self._copy), (QKeySequence.Paste, self._paste),
                          (QKeySequence.Save, self._save_session), (QKeySequence.Open, self._browse)):
            QShortcut(key, self, activated=slot)
        for w, slot in ((self.canvas, lambda: self._delete_regions([self.sel_region])),
                        (self.table, lambda: self._delete_regions(_rows_of(self.table))),
                        (self.reg_list, lambda: self._delete_regions(_rows_of(self.reg_list))),
                        (self.run_list, self._remove_run)):
            QShortcut(QKeySequence.Delete, w, activated=slot, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Escape), self.run_list,
                  activated=lambda: self._select(None), context=Qt.WidgetShortcut)
        self.refresh()
        self.log(f"{APP_NAME} ready. Drop a GINA .txt export or a saved session, use Open…, or "
                 "paste columns (time, count rate) with Ctrl+V.")

    # ================================================================ building
    def _build(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        for item in (("Open…", "A GINA .txt export, or a saved session (.spikeless or .json) — "
                      "Ctrl+O. Columns copied from Excel or Prism: Ctrl+V", self._browse),
                     ("Save…", "The session: runs, spikes, background, regions, figure — "
                      "Ctrl+S; as .spikeless, or .json (the same JSON)", self._save_session),
                     None,
                     ("Figure…", "What Copy and Export make: its settings and a preview",
                      self._figure),
                     ("Report", "Pick its sections and columns, see it, save it", self._report),
                     ("Options", "The mouse on the plot, a new run's settings, export, isotopes, "
                      "methods, log", self._options)):
            if item is None:
                tb.addSeparator()
                continue
            b = QPushButton(item[0])
            b.setToolTip(item[1])
            b.clicked.connect(lambda _=False, f=item[2]: f())
            tb.addWidget(b)

        # the plot, its view ticks and Copy / Export above it
        self.canvas = ChromCanvas()
        self.canvas.regionDrawn.connect(self._drawn)
        self.canvas.edgeMoved.connect(self._edge_moved)
        self.canvas.regionPicked.connect(self._pick_region)
        self.canvas.stretchDrawn.connect(self._stretch)
        self.canvas.dragging.connect(self._dragging)
        self.canvas.modeEnded.connect(self._mode_ended)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.ticks = {}
        for key, text, tip in (
                ("raw", "Trace as recorded", "The selected run (every run, none selected) before "
                 "spikes were excluded; its style: Options › Chromatogram"),
                ("spikes", "Spikes", "The excluded spikes in red; a ring on one put back"),
                ("background", "Background", "The background, dashed"),
                ("stack", "Stack", "Runs one above the other, background subtracted (the "
                                   "figure too)")):
            c = QCheckBox(text)
            c.setToolTip(tip)
            c.toggled.connect(lambda on, k=key: self._view(k, on))
            self.ticks[key] = c
            bar.addWidget(c)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Y:"))
        self.y_mode = QComboBox()
        for key, text in Y_MODES.items():
            self.y_mode.addItem(text, key)
        self.y_mode.setToolTip("Count rate as measured; or each run, its background subtracted, "
                               "as % of its highest point, or as % of all its net counts per "
                               "min — a peak's area on the plot is then its % of total (the "
                               "figure too)")
        self.y_mode.activated.connect(lambda i: self._view("y_mode", self.y_mode.itemData(i)))
        bar.addWidget(self.y_mode)
        bar.addStretch(1)
        for text, tip, slot in (("⧉ Copy", "The figure to the clipboard, at its size in mm "
                                           "(Ctrl+C)", lambda: copy_figure(self)),
                                ("⭳ Export…", "The figure as PNG or SVG, at its size in mm",
                                 lambda: export_figure(self)),
                                ("⚙ Figure…", "What the figure shows, its size, fonts, axes",
                                 self._figure)):
            bar.addWidget(_tool(text, tip, slot))
        tv.addLayout(bar)
        tv.addWidget(self.canvas, 1)

        # results and log
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(GREY)
        self.table = QTableWidget()
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemChanged.connect(self._renamed)
        self.table.currentCellChanged.connect(lambda r, *_: self._pick_row(r))
        self.table.setToolTip("Double-click a region's name to rename it; Del removes the "
                              "selected regions (Ctrl+Z brings them back); Ctrl+C copies the "
                              "table. Columns: Report window. ⤢: every measure, colours, notes.")
        res = QWidget()
        rv = QVBoxLayout(res)
        rv.setContentsMargins(4, 4, 4, 4)
        rh = QHBoxLayout()
        rh.addWidget(self.summary, 1)
        rh.addWidget(_tool("⧉", "Copy the table, to paste into Excel or Word (Ctrl+C)",
                           self._copy_results))
        rh.addWidget(_tool("⤢", "Every measure of each region, its colour, its label on the "
                                "figure, its note", self.regions_window))
        rv.addLayout(rh)
        rv.addWidget(self.table, 1)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lg = QWidget()
        lv = QVBoxLayout(lg)
        lv.setContentsMargins(4, 4, 4, 4)
        lh = QHBoxLayout()
        lh.addStretch(1)
        for text, fn in (("Copy", self._copy_log), ("Export…", self._export_log)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            lh.addWidget(b)
        lv.addLayout(lh)
        lv.addWidget(self.log_view, 1)
        self.tabs = QTabWidget()
        self.tabs.addTab(res, "Results")
        self.tabs.addTab(lg, "Log")
        left = QSplitter(Qt.Vertical)
        left.addWidget(top)
        left.addWidget(self.tabs)
        left.setSizes([580, 250])

        # the steps
        self.steps = QWidget()
        sv = QVBoxLayout(self.steps)
        self.step = {}
        self._names_link = _link("", "▤", "#4caf50", self.names_window, "Run names: the "
                                 "original, the name, the legend's")
        for key, title, body, extra in (("runs", "① Runs", self._runs_step(), self._names_link),
                                        ("spikes", TITLES["spikes"], self._spikes_step(), None),
                                        ("background", TITLES["background"], self._bg_step(),
                                         None),
                                        ("peaks", TITLES["peaks"], self._peaks_step(), None)):
            self.step[key] = _Collapsible(title, body, expanded=True, extra=extra)
            sv.addWidget(self.step[key])
        sv.addStretch(1)
        guard_fields(self.steps)
        self.steps.installEventFilter(self)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(self.steps)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setSizes([1030, 370])
        self.setCentralWidget(split)
        self.statusBar()

    def _runs_step(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 2, 6, 6)
        self.run_list = QListWidget()
        self.run_list.setMaximumHeight(110)
        self.run_list.setToolTip("Tick to show; click to work on it, click it again to rename "
                                 "it; double-click: the plot shows it whole; right-click: "
                                 "rename, export, remove; Del removes it (Ctrl+Z brings it "
                                 "back). Click outside the runs (or Esc) to select none.")
        self.run_list.setEditTriggers(QAbstractItemView.SelectedClicked
                                      | QAbstractItemView.EditKeyPressed)
        self.run_list.itemChanged.connect(self._run_item_changed)
        self.run_list.currentRowChanged.connect(self._run_picked)
        self.run_list.itemDoubleClicked.connect(self._run_focus)
        self.run_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.run_list.customContextMenuRequested.connect(self._run_menu)
        self.run_list.viewport().installEventFilter(self)
        v.addWidget(self.run_list)
        self.run_form = QWidget()
        f = QFormLayout(self.run_form)
        f.setContentsMargins(0, 0, 0, 0)
        self.f_iso = QComboBox()
        self.f_iso.setToolTip("Its half-life and whether it is decay-corrected: Options › "
                              "Isotopes")
        self.f_iso.activated.connect(lambda _: self._meta("isotope", self.f_iso.currentData(),
                                                          undo=True))
        self.f_method = QComboBox()
        self.f_method.setToolTip("Names the regions by retention time, and gives the report its "
                                 "conditions: Options › Methods")
        self.f_method.activated.connect(
            lambda _: self._meta("method", self.f_method.currentData(), undo=True))
        self.f_mol = QLineEdit()
        self.f_mol.editingFinished.connect(lambda: self._meta("molecule", self.f_mol.text()))
        self.f_cond = QPlainTextEdit()
        self.f_cond.setMaximumHeight(52)
        self.f_cond.setPlaceholderText("one per line, e.g. pH: 7")
        self.f_cond.textChanged.connect(
            lambda: self._meta("conditions", self.f_cond.toPlainText(), refresh=False))
        self.f_color = ColorButton(COLORS[0], lambda: self._meta("color", self.f_color.color))
        for label, wdg in (("Isotope", self.f_iso), ("Method", self.f_method),
                           ("Molecule", self.f_mol), ("Conditions", self.f_cond),
                           ("Colour", self.f_color)):
            f.addRow(label, wdg)
        v.addWidget(self.run_form)
        self.f_info = QLabel()
        self.f_info.setWordWrap(True)
        self.f_info.setStyleSheet(GREY)
        self.f_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.f_info)
        return w

    def _spikes_step(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 2, 6, 6)
        g = QLabel("A spike is one point far above the points on both sides of it — an "
                   "electronic artefact of the detector, not activity. Each is excluded and "
                   "bridged by a straight line between its neighbours (the same as leaving the "
                   "point out). Click one to see it; untick it to keep it.")
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        self.spike_list = QListWidget()
        self.spike_list.setMaximumHeight(120)
        self.spike_list.itemChanged.connect(self._spike_ticked)
        self.spike_list.itemClicked.connect(self._spike_focus)
        v.addWidget(self.spike_list)
        h = QHBoxLayout()
        h.addWidget(QLabel("Threshold"))
        self.sens = QSlider(Qt.Horizontal)
        self.sens.setRange(6, 30)                   # n σ × 2: 3 … 15 σ by 0.5
        self.sens.setToolTip("How far above the points around it a point must be: lower finds "
                             "more spikes, higher fewer (a new run's: Options › Spikes)")
        self.sens.sliderPressed.connect(lambda: self._push("spike threshold"))
        self.sens.valueChanged.connect(self._threshold)
        self.sens_lab = QLabel()
        h.addWidget(self.sens, 1)
        h.addWidget(self.sens_lab)
        v.addLayout(h)
        more = QWidget()
        fm = QFormLayout(more)
        self.f_window = QSpinBox()
        self.f_window.setRange(3, 101)
        self.f_window.setSingleStep(2)
        self.f_window.setToolTip("Points in the moving median a point is compared with (odd)")
        self.f_width = QSpinBox()
        self.f_width.setRange(1, 10)
        self.f_width.setToolTip("Widest run of points that can be a spike; wider is signal")
        for wdg, key in ((self.f_window, "window"), (self.f_width, "max_width")):
            wdg.valueChanged.connect(lambda val, k=key: self._spike_param(k, val))
        fm.addRow("Window (points)", self.f_window)
        fm.addRow("Max width (points)", self.f_width)
        v.addWidget(_Collapsible("More", more, expanded=False))
        return w

    def _bg_step(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 2, 6, 6)
        self.bg_value = QLabel()
        self.bg_value.setWordWrap(True)
        v.addWidget(self.bg_value)
        self.bg_group = QButtonGroup(w)
        self.bg_radio = {}
        for mode, text, tip in (
                ("auto", "Mean outside the regions", "The detector's background: the mean of "
                 "every point no region holds (points 4 σ above it left out)"),
                ("stretch", "Mean of a stretch", "The mean of a peak-free stretch, shaded on "
                 "the plot: drag its edges, type them, or draw it again"),
                ("drift", "Follows a drift", "For a trace whose background drifts: SNIP or "
                 "arPLS (offered when ticked in Options › Background)")):
            rb = QRadioButton(text)
            rb.setToolTip(tip)
            self.bg_group.addButton(rb)
            self.bg_radio[mode] = rb
            rb.toggled.connect(lambda on, m=mode: on and self._bg_mode(m))
            if mode == "stretch":
                self.bg_draw = QPushButton("Draw stretch")
                self.bg_draw.setCheckable(True)
                self.bg_draw.setToolTip("Then drag across a stretch with no peak, or click its "
                                        "two edges; right-click cancels")
                self.bg_draw.toggled.connect(lambda on: self._arm("stretch", on))
                v.addWidget(_row(rb, self.bg_draw))
                self.bg_from, self.bg_to = _minutes(), _minutes()
                for s in (self.bg_from, self.bg_to):
                    s.valueChanged.connect(self._stretch_typed)
                self.bg_span = _row(QLabel("      from"), self.bg_from, QLabel("to"), self.bg_to)
                v.addWidget(self.bg_span)
            elif mode == "drift":
                self.bg_method = QComboBox()
                self.bg_method.addItems(["SNIP", "arPLS"])
                self.bg_method.activated.connect(
                    lambda i: self._bg_set("bg_drift", ("snip", "arpls")[i]))
                self.bg_n = QSpinBox()
                self.bg_n.setRange(2, 1000)
                self.bg_n.setToolTip("SNIP: about a peak's half-width, in points")
                self.bg_n.valueChanged.connect(lambda val: self._bg_set("bg_n", val))
                self.drift_row = _row(rb, self.bg_method, self.bg_n)
                v.addWidget(self.drift_row)
            else:
                v.addWidget(rb)
        g = QLabel("A radio-detector's background is flat: its count rate, with Poisson noise. "
                   "A new run's: Options › Background.")
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        return w

    def _peaks_step(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 2, 6, 6)
        g = QLabel("A region is a span integrated as one: a peak, or a peak's shoulder. Find "
                   "regions proposes them; Draw region places one — drag across it on the plot, "
                   "or click its two edges (right-click cancels); its edges land in the valleys "
                   "(hold Alt to place them exactly). Drag an edge to move it, ← → to nudge it "
                   "a point; Del removes the selected regions.")
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        h = QHBoxLayout()
        b = QPushButton("Find regions")
        b.setToolTip("Regions for the peaks no region holds (the ones found before and left "
                     "untouched are found again): a moving mean standing the threshold above "
                     "its surroundings, with more counts than the detection limit")
        b.clicked.connect(self._find)
        h.addWidget(b)
        self.find_sens = QSlider(Qt.Horizontal)
        self.find_sens.setRange(4, 40)               # n σ × 2: 2 … 20 σ by 0.5
        self.find_sens.setToolTip("How far above its surroundings an apex must stand, in σ of "
                                  "the background noise: lower finds more, higher fewer — the "
                                  "regions follow (a new run's: Options › Regions)")
        self.find_sens.sliderPressed.connect(lambda: self._push("region threshold"))
        self.find_sens.valueChanged.connect(self._find_threshold)
        self.find_lab = QLabel()
        h.addWidget(self.find_sens, 1)
        h.addWidget(self.find_lab)
        v.addLayout(h)
        more = QWidget()
        fm = QFormLayout(more)
        self.f_gap = QDoubleSpinBox()
        self.f_gap.setRange(0, 600)
        self.f_gap.setSuffix(" s apart")
        self.f_smooth = QSpinBox()
        self.f_smooth.setRange(1, 51)
        self.f_smooth.setSingleStep(2)
        self.f_smooth.setSuffix(" points")
        self.f_foot = QDoubleSpinBox()
        self.f_foot.setRange(0.5, 20)
        self.f_foot.setSingleStep(0.5)
        self.f_foot.setSuffix(" σ")
        for wdg, key, label, tip in (
                (self.f_gap, "min_gap_s", "Apexes at least", "Two apexes closer than this are "
                 "one peak"),
                (self.f_smooth, "smooth", "Moving mean of", "The mean the apexes are looked "
                 "for on: one noisy point is not a peak"),
                (self.f_foot, "foot_sigma", "Feet at", "A region reaches out to where the mean "
                 "falls back within this of the background")):
            wdg.setToolTip(tip)
            wdg.valueChanged.connect(lambda val, k=key: self._find_param(k, val))
            fm.addRow(label, wdg)
        v.addWidget(_Collapsible("More", more, expanded=False))
        self.reg_draw = QPushButton("Draw region")
        self.reg_draw.setCheckable(True)
        self.reg_draw.setToolTip("Then drag across the region on the plot, or click its two "
                                 "edges; right-click or Esc cancels")
        self.reg_draw.toggled.connect(lambda on: self._arm("region", on))
        v.addWidget(self.reg_draw)
        self.reg_list = QListWidget()
        self.reg_list.setMaximumHeight(130)
        self.reg_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.reg_list.setToolTip("Click one to select it; double-click: the plot shows it; Del "
                                 "removes the selected ones")
        self.reg_list.currentRowChanged.connect(
            lambda r: self._filling or self._pick_region(r))
        self.reg_list.itemDoubleClicked.connect(self._region_focus)
        v.addWidget(self.reg_list)
        self.reg_box = QGroupBox("Selected region")
        f = QFormLayout(self.reg_box)
        self.r_name = QLineEdit()
        self.r_name.editingFinished.connect(lambda: self._reg_set("name", self.r_name.text().strip()))
        self.r_under = QComboBox()
        self.r_under.addItems(["the background", "a straight line between its ends"])
        self.r_under.setToolTip("What its net counts are above: the run's background, or — for "
                                "a peak on another's tail — a line from its start to its end")
        self.r_under.activated.connect(
            lambda i: self._reg_set("under", ("background", "line")[i]))
        self.r_note = QLineEdit()
        self.r_note.setPlaceholderText("why it was drawn or moved, if it matters")
        self.r_note.editingFinished.connect(lambda: self._reg_set("note", self.r_note.text()))
        self.r_color = ColorButton("#808080", lambda: self._reg_set("color", self.r_color.color))
        self.r_label = QCheckBox("Labelled on the figure")
        self.r_label.toggled.connect(lambda on: self._reg_set("label", on))
        for label, wdg in (("Name", self.r_name), ("Under it", self.r_under),
                           ("Note", self.r_note), ("Colour", self.r_color)):
            f.addRow(label, wdg)
        f.addRow(self.r_label)
        v.addWidget(self.reg_box)
        return w

    # ================================================================ state
    def refresh(self, table=True):
        """After any change: results recomputed, every view redrawn (the results table kept
        as it is, selection and all, when only a region was picked in it)."""
        self.results = {r.id: measure(r, PREFS["methods"]) for r in self.runs}
        if self.sel not in self.runs:
            self.sel = None
        if self.sel is None or not 0 <= self.sel_region < len(self.sel.regions):
            self.sel_region = -1
        self.canvas.show(self.runs, self.plot_opts, self.results, self.sel, self.sel_region,
                         self.view)
        self._fill_steps()
        if table:
            self._fill_table()
        for w in (self.names_win, self.regions_win):
            if w is not None:
                w.refresh_later()
        if self.figure_win is not None:
            self.figure_win.refresh()
        if self.report_win is not None:
            self.report_win.refresh_later()

    def _fill_steps(self):
        self._filling = True
        run, res = self.sel, self.results.get(self.sel.id) if self.sel else None
        for key, c in self.ticks.items():
            c.setChecked(self.view[key] if key in self.view else getattr(self.plot_opts, key))
        self.y_mode.setCurrentIndex(max(0, self.y_mode.findData(self.plot_opts.y_mode)))
        _sync(self.run_list, [(r.name, r.shown, None, r.color, None) for r in self.runs],
              Qt.ItemIsEditable)
        if run is not None:
            if self.run_list.currentRow() != self.runs.index(run):
                self.run_list.setCurrentRow(self.runs.index(run))
        else:
            self.run_list.setCurrentRow(-1)
            self.run_list.clearSelection()
        for key in ("spikes", "background", "peaks"):
            self.step[key]._content.setEnabled(run is not None)
        self.run_form.setEnabled(run is not None)
        if run is None:
            for key, title in TITLES.items():
                self.step[key].set_title(f"{title} — select a run")
            self.f_info.setText("Select a run above (or open one)." if self.runs else "")
            self.spike_list.clear()
            self.reg_list.clear()
            self.bg_value.setText("")
            self.reg_box.setEnabled(False)
            self._filling = False
            return
        # ① runs
        _fill_iso(self.f_iso, run.isotope)
        self.f_method.clear()
        self.f_method.addItem("—", "")
        for m in method_names() + ([run.method] if run.method and run.method not in
                                   method_names() else []):
            self.f_method.addItem(m, m)
        self.f_method.setCurrentIndex(max(0, self.f_method.findData(run.method)))
        self.f_mol.setText(run.molecule)
        if self.f_cond.toPlainText() != run.conditions:
            self.f_cond.setPlainText(run.conditions)
        self.f_color.set_color(run.color)
        decay = (f"decay-corrected to the run start ({run.isotope})" if run.decayed()
                 else "not decay-corrected")
        self.f_info.setText(((f"Originally {run.source} · " if run.source != run.name else "")
                            + f"{run.file or '—'} · {run.run_datetime or 'no run date'} · "
                            f"{len(run.y)} points, one every {run.dt_s:g} s, "
                            f"{run.x[-1]:.2f} min · {decay}"
                            + (f" · SHA-256 {run.sha256[:12]}…" if run.sha256 else "")
                            ).replace("_", "_\u200b"))   # a long file name wraps, not the panel
        # ② spikes
        n_ex = int(run.excluded().sum())
        self.step["spikes"].set_title(f"{TITLES['spikes']} — {n_ex} excluded"
                                      + (f", {len(run.kept)} kept" if run.kept else ""))
        bridged = remove(run.y, run.excluded())
        where = [(r.start, r.end, row.name) for r, row in zip(run.regions, res.rows)]
        entries = []
        for i in run.spike_list():
            t = float(run.x[i])
            reg = next((n for a, b, n in where if a <= t <= b), "")
            entries.append((f"{t:6.2f} min   {run.y[i]:.0f} → {bridged[i]:.0f} cps"
                            + (f"   in {reg}" if reg else ""), i not in run.kept, i, None, None))
        _sync(self.spike_list, entries)
        p = run.spike_params
        self.sens.setValue(int(round(p.n_sigma * 2)))
        self.sens_lab.setText(f"{p.n_sigma:.1f} σ")
        self.f_window.setValue(p.window)
        self.f_width.setValue(p.max_width)
        # ③ background
        self.step["background"].set_title(f"{TITLES['background']} — {res.background:.1f} cps")
        self.bg_radio[run.bg_mode].setChecked(True)
        self.drift_row.setVisible(PREFS["bg"]["offer_drift"] or run.bg_mode == "drift")
        a, b = sorted(run.bg_stretch or [PREFS["bg"]["stretch_from"], PREFS["bg"]["stretch_to"]])
        self.bg_from.setValue(a)
        self.bg_to.setValue(b)
        self.bg_span.setEnabled(run.bg_mode == "stretch")
        self.bg_method.setCurrentIndex(1 if run.bg_drift == "arpls" else 0)
        self.bg_n.setValue(run.bg_n)
        self.bg_n.setEnabled(run.bg_drift == "snip")
        self.bg_value.setText(f"<b>{res.background:.2f} cps</b> — {res.background_how}")
        # ④ regions
        self.step["peaks"].set_title(f"{TITLES['peaks']} — {len(run.regions)}")
        fp = run.find_params
        self.find_sens.setValue(int(round(fp.n_sigma * 2)))
        self.find_lab.setText(f"{fp.n_sigma:.1f} σ")
        self.f_gap.setValue(fp.min_gap_s)
        self.f_smooth.setValue(fp.smooth)
        self.f_foot.setValue(fp.foot_sigma)
        _sync(self.reg_list, [
            (f"{row.name}   {row.rt:.2f} min" + (f"   {row.pct:.1f} %" if row.pct is not None
                                                  else "   n.d." if "n.d." in row.flags else ""),
             None, k, None, reg.color or run.color)
            for k, (reg, row) in enumerate(zip(run.regions, res.rows))])
        k = self.sel_region
        if k < 0:
            self.reg_list.clearSelection()
        elif self.reg_list.currentRow() != k:
            self.reg_list.setCurrentRow(k)
        self.reg_box.setEnabled(k >= 0)
        if k >= 0:
            r, row = run.regions[k], res.rows[k]
            self.reg_box.setTitle(f"Selected region — {row.start:.2f}–{row.end:.2f} min")
            self.r_name.setText(r.name)
            self.r_name.setPlaceholderText(row.name)
            self.r_under.setCurrentIndex(1 if r.under == "line" else 0)
            self.r_note.setText(r.note)
            self.r_color.set_color(r.color or run.color)
            self.r_label.setChecked(r.label)
        else:
            self.reg_box.setTitle("Selected region — click one")
            for wdg in (self.r_name, self.r_note):
                wdg.setText("")
        self._filling = False

    def _fill_table(self):
        self._filling = True
        t = self.table
        res = self.results.get(self.sel.id) if self.sel else None
        if res is None:
            t.setRowCount(0)
            t.setColumnCount(0)
            self.summary.setText("Select a run (① Runs) to see its results." if self.runs
                                 else "")
            self._filling = False
            return
        run = self.sel
        cols = columns()
        head, body, extra = result_rows(res)
        t.setColumnCount(len(head))
        t.setHorizontalHeaderLabels(head)
        for c, (key, _, _) in enumerate(cols):
            t.horizontalHeaderItem(c).setToolTip(HELP.get(key, ""))
        t.setRowCount(len(body) + len(extra))
        italic = QFont()
        italic.setItalic(True)
        for r, vals in enumerate(body + extra):
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                edit = r < len(body) and cols[c][0] == "name"
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                            | (Qt.ItemIsEditable if edit else Qt.NoItemFlags))
                if cols[c][0] not in ("name", "flags"):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if r >= len(body):
                    it.setFont(italic)
                elif "n.d." in res.rows[r].flags:
                    it.setForeground(QColor("#808080"))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):         # a little air: the numbers, not the frame
            t.setColumnWidth(c, t.columnWidth(c) + 12)
        if 0 <= self.sel_region < len(body):
            t.selectRow(self.sel_region)
        else:
            t.clearSelection()
        n_ex = int(run.excluded().sum())
        self.summary.setText(
            f"<b>{run.name}</b> · background {res.background:.1f} cps ({res.background_how}) · "
            f"{res.total:.0f} net counts in the run · % of total = of all of them (Ph. Eur.) · "
            f"{n_ex} spike(s) excluded · "
            + (f"decay-corrected ({run.isotope})" if run.decayed() else "not decay-corrected")
            + ("" if res.active else " · <b>no activity above background: no %</b>"))
        self._filling = False

    # ================================================================ undo / redo
    def _push(self, label):
        """Snapshot the runs before a change, so Ctrl+Z can restore it. label: what the log
        will say was undone, in the user's words."""
        idx = self.runs.index(self.sel) if self.sel in self.runs else None
        self._undo.append((copy.deepcopy(self.runs), idx, label))
        del self._undo[:-25]       # ponytail: 25 deep; deeper isn't worth the RAM
        self._redo.clear()

    def _undo_step(self):
        self._step(self._undo, self._redo, "undo", "Undone")

    def _redo_step(self):
        self._step(self._redo, self._undo, "redo", "Redone")

    def _step(self, src, dst, what, done):
        if not src:
            self.log(f"Nothing to {what}.")
            return
        runs, idx, label = src.pop()
        dst.append((self.runs, self.runs.index(self.sel) if self.sel in self.runs else None,
                    label))
        self.runs = runs
        self.sel = runs[idx] if idx is not None and idx < len(runs) else None
        self.sel_region = -1
        self.refresh()
        self.log(f"{done}: {label}.")

    # ================================================================ runs
    def _select(self, run):
        """Work on run (None: on none — the steps wait for one)."""
        if self.canvas.mode:
            self.canvas.set_mode(None)
            self._mode_ended()
        if run is not self.sel:
            self.sel, self.sel_region = run, -1
            self.refresh()

    def eventFilter(self, obj, ev):                     # noqa: N802 - Qt's name
        """A click outside the runs — below them in the list, or on the steps' panel away
        from a step that acts on the run — selects none."""
        if ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            pos = ev.position().toPoint()
            if obj is self.run_list.viewport():
                if self.run_list.itemAt(pos) is None:
                    self._select(None)
            elif obj is self.steps and not self._keeps_run(self.steps.childAt(pos)):
                self._select(None)
        return False

    def _keeps_run(self, w):
        keep = (self.run_form, self.step["spikes"], self.step["background"],
                self.step["peaks"], self.step["runs"]._btn, self._names_link)
        while w is not None:
            if any(w is k for k in keep):
                return True
            w = w.parentWidget()
        return False

    def _run_item_changed(self, it):
        if self._filling:
            return
        run = self.runs[self.run_list.row(it)]
        if it.text() != run.name:                        # typed in the list
            self.rename(run, it.text())
        elif (it.checkState() == Qt.Checked) != run.shown:
            run.shown = it.checkState() == Qt.Checked
            self.refresh()

    def _run_picked(self, row):
        if not self._filling:
            self._select(self.runs[row] if 0 <= row < len(self.runs) else None)

    def _run_focus(self, it):
        run = self.runs[self.run_list.row(it)]
        self.canvas.focus(float(run.x[0]), float(run.x[-1]))

    def _run_menu(self, pos):
        it = self.run_list.itemAt(pos)
        if it is None:
            return
        run = self.runs[self.run_list.row(it)]
        self._select(run)
        m = QMenu(self)
        m.addAction("Rename", lambda: self.run_list.editItem(
            self.run_list.item(self.runs.index(run))))
        m.addAction("Export the spikeless trace…", lambda: self._export_trace(run))
        m.addAction("Export the trace as recorded…", lambda: self._export_trace(run, True))
        m.addSeparator()
        m.addAction("Remove   Del", lambda: self._remove_run(run))
        m.exec(self.run_list.viewport().mapToGlobal(pos))

    def rename(self, run, text):
        """The run's name (an alias: its original stays, Run names ▤); empty: the original."""
        new = text.strip() or run.source
        if new == run.name:
            self.refresh()
            return
        self._push(f"rename {run.name} to {new}")
        run.name = new
        self.refresh()

    def relabel(self, run, text):
        """What the figure's legend calls the run; empty, or its name: its name."""
        new = text.strip()
        new = "" if new == run.name else new
        if new == run.label:
            return
        self._push(f"legend of {run.name}")
        run.label = new
        self.refresh()

    def _meta(self, key, value, undo=False, refresh=True):
        run = self.sel
        if self._filling or run is None or getattr(run, key) == value:
            return
        if undo:
            self._push(f"{key} of {run.name}")
        setattr(run, key, value)
        if refresh:
            self.refresh()
        elif self.report_win is not None:
            self.report_win.refresh_later()

    def _remove_run(self, run=None):
        run = run or self.sel
        if run is None:
            return
        self._push(f"remove {run.name}")
        i = self.runs.index(run)
        del self.runs[i]
        if run is self.sel:
            self.sel = self.runs[min(i, len(self.runs) - 1)] if self.runs else None
        self.refresh()
        self.log(f"Removed '{run.name}' (Ctrl+Z brings it back).")

    def _export_trace(self, run, recorded=False):
        what = "recorded" if recorded else "spikeless"
        name = re.sub(r'[\\/:*?"<>|]', "_", run.name) + f"_{what}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export the trace as recorded" if recorded else "Export the spikeless trace",
            str(self._dir / name), "Text, GINA-style (*.txt)")
        if path:
            if not path.lower().endswith(".txt"):
                path += ".txt"
            io_gina.save(run, path, recorded=recorded)
            self.log(f"Trace of '{run.name}' ({'as recorded' if recorded else 'spikes excluded'}"
                     f") exported to {path}")

    def names_window(self):
        if self.names_win is None:
            self.names_win = NamesWindow(self)
        self.names_win.open()

    # ================================================================ spikes
    def _threshold(self, v):
        run = self.sel
        if self._filling or run is None:
            return
        if not self.sens.isSliderDown():            # keys / a click on the groove
            self._push("spike threshold")
        run.spike_params.n_sigma = v / 2
        run.detect_spikes()
        self.refresh()

    def _spike_param(self, key, val):
        run = self.sel
        if self._filling or run is None:
            return
        self._push(f"spike {key.replace('_', ' ')}")
        setattr(run.spike_params, key, val | 1 if key == "window" else val)
        run.detect_spikes()
        self.refresh()

    def _spike_ticked(self, it):
        run = self.sel
        if self._filling or run is None:
            return
        i = it.data(Qt.UserRole)
        keep = it.checkState() != Qt.Checked
        self._push(f"{'keep' if keep else 'exclude'} the spike at {run.x[i]:.2f} min")
        run.kept = sorted(set(run.kept) | {i}) if keep else [k for k in run.kept if k != i]
        self.refresh()

    def _spike_focus(self, it):
        """The plot zooms on the spike, its reading line on it."""
        run = self.sel
        if run is None:
            return
        t = float(run.x[it.data(Qt.UserRole)])
        h = max(0.5, 30 * run.dt_s / 60)
        self.canvas.set_cursor(t)
        self.canvas.focus(t - h, t + h)

    # ================================================================ background
    def _bg_mode(self, mode):
        run = self.sel
        if self._filling or run is None or run.bg_mode == mode:
            return
        self._push("background")
        run.bg_mode = mode
        if mode == "stretch" and not run.bg_stretch:
            run.bg_stretch = [PREFS["bg"]["stretch_from"], PREFS["bg"]["stretch_to"]]
        self.refresh()

    def _bg_set(self, key, val):
        run = self.sel
        if self._filling or run is None or getattr(run, key) == val:
            return
        self._push("background")
        setattr(run, key, val)
        run.bg_mode = "drift"
        self.refresh()

    def _stretch(self, a, b):
        run = self.sel
        if run is None:
            return
        self._push("background stretch")
        run.bg_mode, run.bg_stretch = "stretch", [a, b]
        self.refresh()
        self.log(f"Background of '{run.name}': mean of {a:.2f}–{b:.2f} min, "
                 f"{self.results[run.id].background:.2f} cps.")

    def _stretch_typed(self, *_):
        run = self.sel
        if self._filling or run is None:
            return
        a, b = self.bg_from.value(), self.bg_to.value()
        if b - a >= 2 * run.dt_s / 60 and [a, b] != run.bg_stretch:
            self._stretch(a, b)

    # ================================================================ drawing on the plot
    def _arm(self, mode, on):
        """Draw region / Draw stretch pushed in (the next drag or two clicks on the plot draw
        it) or out."""
        if self._filling:
            return
        other = self.bg_draw if mode == "region" else self.reg_draw
        if on:
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
            self.canvas.set_mode(mode)
            self.canvas.setFocus()
            self.statusBar().showMessage(
                f"Drag across the {'region' if mode == 'region' else 'stretch'} on the plot, or "
                "click its two edges; right-click or Esc cancels.", 8000)
        elif self.canvas.mode == mode:
            self.canvas.set_mode(None)

    def _mode_ended(self):
        for b in (self.reg_draw, self.bg_draw):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self.statusBar().clearMessage()

    # ================================================================ regions
    def _row_text(self, run, k):
        row = self.results[run.id].rows[k]
        return (f"{row.name}, {row.start:.2f}–{row.end:.2f} min, {row.net:.0f} ± {row.unc:.0f} "
                f"counts" + (f", {row.pct:.1f} % of total" if row.pct is not None else "")
                + (f" ({', '.join(row.flags)})" if row.flags else ""))

    def _drawn(self, a, b, exact):
        run = self.sel
        if run is None:
            return
        if not exact:
            y = run.trace()
            a, b = snap(run.x, y, a), snap(run.x, y, b)
        ab = fit(run.regions, a, b, run.dt_s / 60)
        if ab is None:
            self.log("That span lies inside a region, or is too short: drag a region's edges "
                     "to change it.")
            return
        self._push("draw a region")
        new = Region(*ab, how="drawn")
        run.regions = sorted(run.regions + [new], key=lambda r: r.start)
        self.sel_region = run.regions.index(new)
        self.refresh()
        self.log(f"Region drawn on '{run.name}': {self._row_text(run, self.sel_region)}.")

    def _edge_moved(self, i, side, t, exact):
        run = self.sel
        if run is None or i >= len(run.regions):
            return
        if i < 0:                                        # the background stretch: as placed
            if not run.bg_stretch:
                return
            a, b = sorted(run.bg_stretch)
            a, b = (t, b) if side == "start" else (a, t)
            if b - a >= 2 * run.dt_s / 60:
                self._stretch(a, b)
            else:
                self.refresh()
            return
        r, dtm = run.regions[i], run.dt_s / 60
        if not exact:
            t = snap(run.x, run.trace(), t)
        old = getattr(r, side)
        opp = "end" if side == "start" else "start"
        # an edge shared with the neighbour moves for both
        other = next((o for o in run.regions if o is not r
                      and abs(getattr(o, opp) - old) < 1e-9), None)
        if side == "start":
            lo = other.start + 2 * dtm if other else max(
                [o.end for o in run.regions if o is not r and o.end <= old + 1e-9]
                + [float(run.x[0])])
            hi = r.end - 2 * dtm
        else:
            lo = r.start + 2 * dtm
            hi = other.end - 2 * dtm if other else min(
                [o.start for o in run.regions if o is not r and o.start >= old - 1e-9]
                + [float(run.x[-1])])
        t = float(np.clip(t, lo, hi))
        if abs(t - old) < 1e-9:
            self.refresh()
            return
        self._push("move a region's edge")
        for reg, s in ((r, side), (other, opp)):
            if reg is not None:
                setattr(reg, s, t)
                if reg.how == "auto":
                    reg.how = "moved"
        self.sel_region = i
        self.refresh()
        self.log(f"Edge moved: {self._row_text(run, i)}.")

    def _pick_region(self, i, table=True):
        """Region i of the selected run selected (-1: none). Picked in the table, the table is
        left as it is (its selection may be several rows)."""
        if self.sel is not None and i != self.sel_region:
            self.sel_region = i if i < len(self.sel.regions) else -1
            self.refresh(table=table)

    def _pick_row(self, r):
        if not self._filling and self.sel is not None:
            self._pick_region(r if r < len(self.sel.regions) else -1, table=False)

    def _region_focus(self, it):
        run = self.sel
        k = it.data(Qt.UserRole)
        if run is not None and k is not None and k < len(run.regions):
            r = run.regions[k]
            w = max(r.end - r.start, 0.2)
            self.canvas.focus(r.start - w, r.end + w)

    def _dragging(self, a, b):
        run = self.sel
        if run is None:
            return
        y = run.trace()
        m = (run.x >= a) & (run.x <= b)
        if m.sum() >= 2:
            net = float(np.trapezoid((y - run.background(y)[0])[m], run.x[m])) * 60
            self.statusBar().showMessage(f"{a:.2f}–{b:.2f} min: {net:.0f} net counts", 2000)

    def _reg_set(self, key, val):
        if self.sel_region >= 0:
            self.set_region(self.sel_region, key, val)

    def set_region(self, k, key, val):
        """One thing about region k of the selected run (name, under, note, colour, label)."""
        run = self.sel
        if self._filling or run is None or not 0 <= k < len(run.regions) \
                or getattr(run.regions[k], key) == val:
            return
        self._push(f"region {key}")
        setattr(run.regions[k], key, val)
        self.sel_region = k
        self.refresh()

    def _renamed(self, it):
        run = self.sel
        if self._filling or run is None or it.row() >= len(run.regions):
            return
        name = it.text().strip()
        auto = self.results[run.id].rows[it.row()].name
        self.set_region(it.row(), "name", "" if name == auto and not run.regions[it.row()].name
                        else name)

    def _delete_regions(self, ks):
        run = self.sel
        ks = sorted({k for k in ks if run is not None and 0 <= k < len(run.regions)})
        if not ks:
            return
        rows = self.results[run.id].rows
        self._push("remove " + ", ".join(rows[k].name for k in ks))
        run.regions = [r for k, r in enumerate(run.regions) if k not in ks]
        self.sel_region = -1
        self.refresh()

    def _refind(self, run):
        """Find again: the regions found and left untouched give way to what the run's
        settings find now; the others stay. The new ones, returned."""
        run.regions = [r for r in run.regions if not r.untouched()]
        new = find_regions(run)
        run.regions = sorted(run.regions + new, key=lambda r: r.start)
        self.sel_region = -1
        return new

    def _find(self):
        run = self.sel
        if run is None:
            return
        self._push("find regions")
        new = self._refind(run)
        self.refresh()
        self.log(f"Find regions on '{run.name}' ({run.find_params.n_sigma:g} σ): " + (
            f"{len(new)} region(s)." if new else
            "nothing above the detection limit that no region already holds."))

    def _find_threshold(self, v):
        run = self.sel
        if self._filling or run is None:
            return
        if not self.find_sens.isSliderDown():
            self._push("region threshold")
        run.find_params.n_sigma = v / 2
        self._refind(run)
        self.refresh()

    def _find_param(self, key, val):
        run = self.sel
        if self._filling or run is None or getattr(run.find_params, key) == val:
            return
        self._push(f"find regions: {key.replace('_', ' ')}")
        setattr(run.find_params, key, int(val) | 1 if key == "smooth" else val)
        self._refind(run)
        self.refresh()

    def regions_window(self):
        if self.regions_win is None:
            self.regions_win = RegionsWindow(self)
        self.regions_win.open()

    # ================================================================ view
    def _view(self, key, on):
        if self._filling:
            return
        if key in self.view:
            self.view[key] = on
        else:
            setattr(self.plot_opts, key, on)
        self.refresh()

    # ================================================================ files
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(OPENS)
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._load_paths([u.toLocalFile() for u in e.mimeData().urls()])

    def _load_paths(self, paths):
        """Open what was dropped or picked: GINA exports, or one session file."""
        for p in paths:
            if p.lower().endswith((session.EXT, ".json")):
                self._open_session(p)
            elif p.lower().endswith(".txt"):
                self._load(p)

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", str(self._dir),
            f"GINA export or session (*.txt *{session.EXT} *.json);;GINA export (*.txt);;"
            f"Session (*{session.EXT} *.json)")
        self._load_paths(paths)

    def _load(self, path):
        self._dir = Path(path).parent
        try:
            run, warnings = io_gina.load(path)
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR loading {Path(path).name}: {exc}")
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self._adopt([run], warnings)

    def _paste(self):
        """Ctrl+V on the window: pasted columns (time, count rate…), or a GINA export, as
        runs."""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit)):
            fw.paste()   # a text field has focus — that paste is not ours
            return
        self._paste_n += 1
        try:
            runs, warnings = io_paste.load_text(QApplication.clipboard().text(),
                                                f"Clipboard {self._paste_n}")
        except Exception as exc:  # noqa: BLE001
            self._paste_n -= 1
            self.log(f"ERROR pasting from clipboard: {exc}")
            QMessageBox.warning(self, "Paste failed", str(exc))
            return
        self._adopt(runs, warnings)

    def _adopt(self, runs, warnings):
        """Freshly read runs into the session (one undo step), with a new run's settings
        (Options › Spikes, Background, Regions): selected, logged, drawn."""
        self._push(f"load {runs[0].name}" + (f" and {len(runs) - 1} more" if len(runs) > 1
                                             else ""))
        bg = PREFS["bg"]
        for r in runs:
            r.color = COLORS[len(self.runs) % len(COLORS)]
            r.spike_params = SpikeParams(**PREFS["spikes"])
            r.detect_spikes()
            r.find_params = FindParams(**PREFS["find"])
            r.bg_mode = "auto" if bg["mode"] == "drift" and not bg["offer_drift"] else bg["mode"]
            r.bg_stretch = [bg["stretch_from"], bg["stretch_to"]]
            r.bg_drift, r.bg_n = bg["drift"], bg["n"]
            self.runs.append(r)
        self.sel, self.sel_region = runs[0], -1
        self.canvas.xlim = self.canvas.ylim = None
        self.refresh()
        for r in runs:
            sp = r.spike_list()
            self.log(f"Loaded '{r.name}' ({len(r.y)} points, one every {r.dt_s:g} s, "
                     f"{r.x[-1]:.2f} min) from {r.file}: "
                     + (f"{len(sp)} spike(s) excluded, at "
                        + ", ".join(f"{r.x[i]:.2f}" for i in sp) + " min." if sp
                        else "no spike."))
        for w in warnings:
            self.log(f"  ⚠ {w}")

    def _save_session(self):
        if not self.runs:
            self.log("Save: nothing loaded yet.")
            return
        stem = re.sub(r'[\\/:*?"<>|]', "_", self.runs[0].name)
        name = self._session_path or self._dir / f"{stem}{session.EXT}"
        path, flt = QFileDialog.getSaveFileName(
            self, "Save session", str(name),
            f"Spikeless session (*{session.EXT});;JSON — the same session (*.json)")
        if not path:
            return
        path = Path(path)
        ext = ".json" if path.name.lower().endswith(".json") or "json" in flt.lower() \
            else session.EXT
        if not path.name.lower().endswith(ext):   # not with_suffix: names carry dots
            path = path.with_name(path.name + ext)
        try:
            path.write_text(session.dumps(self.runs, self.plot_opts), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._session_at(path)
        self.log(f"Session saved to {path}")

    def _open_session(self, path):
        try:
            runs, plot = session.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.log(f"ERROR opening {Path(path).name}: {exc}")
            QMessageBox.warning(self, "Open failed", str(exc))
            return
        if self.runs and QMessageBox.question(
                self, "Open session", f"Replace the {len(self.runs)} run(s) open now? "
                "Ctrl+Z brings them back.") != QMessageBox.Yes:
            return
        self._push(f"open {Path(path).name}")
        self.runs, self.plot_opts = runs, plot
        self.sel, self.sel_region = (runs[0] if runs else None), -1
        self.canvas.xlim = self.canvas.ylim = None
        self._session_at(Path(path))
        if self.figure_win is not None:
            self.figure_win.load()
        self.refresh()
        self.log(f"Opened session {path}: {len(runs)} run(s), "
                 f"{sum(len(r.regions) for r in runs)} region(s).")

    def _session_at(self, path):
        self._session_path, self._dir = path, path.parent
        self.setWindowTitle(f"{path.name} — {self._title}")

    # ================================================================ clipboard, log
    def _copy(self):
        """Ctrl+C: the selected text, the results table if it has focus, else the figure."""
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit)):
            fw.copy()
        elif fw is self.table:
            self._copy_results()
        else:
            copy_figure(self)

    def _copy_results(self):
        if self.sel is None:
            return
        head, body, extra = result_rows(self.results[self.sel.id])
        copy_table([head] + body + extra)
        self.log(f"Results of '{self.sel.name}' copied ({len(body)} region(s)).")

    def log(self, msg):
        self.log_view.appendPlainText(f"[{_dt.datetime.now():%H:%M:%S}] {msg}")
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log_text(self):
        text = self.log_view.toPlainText()
        if not PREFS["log_timestamps"]:
            text = re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", text, flags=re.MULTILINE)
        return text

    def _copy_log(self):
        QApplication.clipboard().setText(self._log_text())
        self.log("Log copied to clipboard.")

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export log",
                                              str(self._dir / "spikeless_log.txt"),
                                              "Text (*.txt)")
        if path:
            Path(path).write_text(self._log_text(), encoding="utf-8")
            self.log(f"Log exported to {path}")

    # ================================================================ other windows
    def apply_prefs(self):
        """The options changed (Options window): results and every view follow."""
        if self.report_win is not None:
            self.report_win.sync()
        self.refresh()

    def _options(self, topic=None):
        if self.options_win is None:
            self.options_win = OptionsWindow(self)
        self.options_win.open(topic)

    def _report(self):
        if self.report_win is None:
            self.report_win = ReportWindow(self)
        self.report_win.open()

    def _figure(self):
        if self.figure_win is None:
            self.figure_win = FigureWindow(self)
        self.figure_win.open()

    def closeEvent(self, e):
        for w in (self.options_win, self.report_win, self.figure_win, self.names_win,
                  self.regions_win):
            if w is not None:      # or the app stays up with them
                w.close()
        super().closeEvent(e)


# ---------------- small helpers
def _row(*widgets):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for k, wdg in enumerate(widgets):
        h.addWidget(wdg, 1 if k == 0 else 0)
    return w


def _tool(text, tip, slot):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.clicked.connect(lambda _=False: slot())
    return b


def _minutes():
    s = QDoubleSpinBox()
    s.setRange(0, 1000)
    s.setDecimals(2)
    s.setSingleStep(0.05)
    s.setSuffix(" min")
    return s


def _swatch(color):
    pm = QPixmap(10, 10)
    pm.fill(QColor(color))
    return QIcon(pm)


def _sync(lst, entries, flags=Qt.NoItemFlags):
    """A list widget's items from entries (text, ticked or None, data, text colour, swatch
    colour) — in place when their number is the same, so the item a click or double-click is
    on stays the same item."""
    if lst.count() != len(entries):
        lst.clear()
        for _ in entries:
            lst.addItem(QListWidgetItem())
    for k, (text, tick, data, fg, sw) in enumerate(entries):
        it = lst.item(k)
        it.setFlags(it.flags() | flags | (Qt.ItemIsUserCheckable if tick is not None
                                          else Qt.NoItemFlags))
        it.setText(text)
        if tick is not None:
            it.setCheckState(Qt.Checked if tick else Qt.Unchecked)
        it.setData(Qt.UserRole, data)
        if fg:
            it.setForeground(QColor(fg).lighter(160))
        if sw:
            it.setIcon(_swatch(sw))


def _rows_of(view):
    """The rows selected in a table or a list."""
    return [i.row() for i in view.selectedIndexes()]


def _fill_iso(c: QComboBox, current: str):
    """The isotope list (Options › Isotopes), and the current one even if the table no longer
    has it, so opening a run never drops it."""
    c.clear()
    c.addItem("—", "")
    for name, hours, corr in PREFS["isotopes"]:
        c.addItem(f"{name}   ({hours:g} h{', decay-corrected' if corr else ''})", name)
    if current and c.findData(current) < 0:
        c.addItem(current, current)
    c.setCurrentIndex(max(0, c.findData(current)))


def _app_icon():
    """The window/taskbar icon, if the bundled .ico is present (drawn by misc/make_icon.py)."""
    p = Path(__file__).with_name("assets") / "spikeless.ico"
    return QIcon(str(p)) if p.exists() else None
