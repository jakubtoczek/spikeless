"""Spikeless main window: one screen, four steps.

The chromatogram in the middle, its results under it (the log in a tab beside them), and the
steps on the right, top to bottom — Runs, Spikes, Background, Regions — each acting on the
selected run (with none selected, they wait for one). Each step shows on the plot what it is
about (its Show ticks); its explanations are in the tooltips and the user guide. Every change
to a run is one undo step (Ctrl+Z / Ctrl+Y), named in the log.
"""

from __future__ import annotations

import copy
import datetime as _dt
import re
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QLocale, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import __version__, io_gina, io_paste, session
from .canvas import ChromCanvas
from .editors import NamesWindow, RegionPanel, RegionsWindow, copy_table
from .figure import FigureWindow
from .options import OptionsWindow, PREFS, load_prefs, method_names, params, save_prefs
from .peaks import find_regions, fit, measure
from .plotting import Y_MODES, PlotOptions
from .report import HELP, ReportWindow, columns, rows as result_rows
from .run import COLORS, FindParams, Region
from .spikes import SpikeParams, remove
from .widgets import Collapsible, ColorButton, guard_fields, link

APP_NAME = "Spikeless"
OPENS = (".txt", session.EXT)               # what Open… and a drop take
GREY = "color:#8d8d8d;"
ACCENT = "#4a9782"                          # the suite's green (BioDist's Results button)
TITLES = {"runs": "Runs", "spikes": "Spikes", "background": "Background", "peaks": "Regions"}


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
        self.view = {"raw": False, "spikes": True, "stretch": True,     # screen only
                     "line_auto": True, "line_stretch": True, "line_drift": True}
        self._undo: list = []
        self._redo: list = []
        self._session_path: Path | None = None
        self._dir = Path.home()          # where file dialogs open: the last file's folder
        self._paste_n = 0
        self._filling = False
        self.options_win = self.report_win = self.figure_win = None
        self.names_win = self.regions_win = self.region_win = None
        self.ticks = {}
        self.body = {}
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
        for item in (("Open…", "A GINA .txt export, or a saved session (.json) — "
                      "Ctrl+O. Columns copied from Excel or Prism: Ctrl+V", self._browse),
                     ("Save…", "The session: runs, spikes, background, regions, figure — "
                      "Ctrl+S, as a .json file", self._save_session),
                     None,
                     ("Figure…", "What the figure's Copy and Export make: its settings and a "
                      "preview", self._figure),
                     ("Report", "Pick its sections and columns, see it, save it", self._report),
                     ("⚙ Options", "The mouse on the plot, what the panels and the results "
                      "show, a new run's settings, export, isotopes, methods, log",
                      self._options)):
            if item is None:
                tb.addSeparator()
                continue
            b = QPushButton(item[0])
            b.setToolTip(item[1])
            b.clicked.connect(lambda _=False, f=item[2]: f())
            if item[0] == "Figure…":
                b.setStyleSheet(f"QPushButton{{background:{ACCENT};color:white;font-weight:600;"
                                "padding:3px 16px;border-radius:3px;}")
            tb.addWidget(b)

        # the plot, and above it what applies to every run, and Copy
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
        c = QCheckBox("Stack")
        c.setToolTip("Runs one above the other, background subtracted (the figure too)")
        c.toggled.connect(lambda on: self._view("stack", on))
        self.ticks["stack"] = c
        bar.addWidget(c)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Y:"))
        self.y_mode = QComboBox()
        for key, text in Y_MODES.items():
            self.y_mode.addItem(text, key)
        self.y_mode.setToolTip("The count rate as measured; or each run, its background "
                               "subtracted, as % of its highest point, or each point's counts "
                               "as % of all the run's net counts — the points add up to 100 % "
                               "(the figure too)")
        self.y_mode.activated.connect(lambda i: self._view("y_mode", self.y_mode.itemData(i)))
        bar.addWidget(self.y_mode)
        bar.addStretch(1)
        bar.addWidget(_tool("⧉ Copy", "The plot as it is on screen, to the clipboard (Ctrl+C). "
                                      "The figure for a paper: Figure…", self._copy_screen))
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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            lambda pos: self._region_menu(self.table, pos))
        self.table.setToolTip("Right-click a region: rename, edit, remove; Del removes the "
                              "selected ones (Ctrl+Z brings them back). Columns: Options › "
                              "Results; hover a header for its meaning.")
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
        sv.setSpacing(6)
        self.step = {}
        self._names_link = link("", "▤", "#4caf50", self.names_window, "Run names: the "
                                "original, the name, the legend's")
        for i, (key, body, extra) in enumerate((("runs", self._runs_step(), self._names_link),
                                                ("spikes", self._spikes_step(), None),
                                                ("background", self._bg_step(), None),
                                                ("peaks", self._peaks_step(), None))):
            if i:
                sv.addWidget(_hline())
            self.step[key] = Collapsible(TITLES[key], body, expanded=True, extra=extra)
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

    def _section(self, key, show=()):
        """A step's widget: its Show ticks (what it draws on the plot: always at hand), then
        its body (only with a run selected). (outer, body layout)."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 0, 6, 4)
        v.setSpacing(4)
        if show:
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            lab = QLabel("Show")
            lab.setStyleSheet(GREY)
            h.addWidget(lab)
            for k, text, tip in show:
                c = QCheckBox(text)
                c.setToolTip(tip)
                c.toggled.connect(lambda on, k=k: self._view(k, on))
                self.ticks[k] = c
                h.addWidget(c)
            h.addStretch(1)
            v.addLayout(h)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)
        v.addWidget(body)
        self.body[key] = body
        return w, bv

    def _runs_step(self):
        w, v = self._section("runs")
        self.run_list = QListWidget()
        self.run_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.run_list.setTextElideMode(Qt.ElideMiddle)
        self.run_list.setToolTip("Tick to show; click to work on it; double-click (or F2) to "
                                 "rename it; drag to reorder (the legend and the report follow); "
                                 "right-click: rename, export, remove; Del removes it (Ctrl+Z "
                                 "brings it back). Click below the runs (or Esc) to select none.")
        self.run_list.setEditTriggers(QAbstractItemView.DoubleClicked
                                      | QAbstractItemView.EditKeyPressed)
        self.run_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.run_list.model().rowsMoved.connect(self._runs_moved)
        self.run_list.itemChanged.connect(self._run_item_changed)
        self.run_list.currentRowChanged.connect(self._run_picked)
        self.run_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.run_list.customContextMenuRequested.connect(self._run_menu)
        self.run_list.viewport().installEventFilter(self)
        _sized(v, self.run_list)
        self.run_form = QWidget()
        self.run_rows = QFormLayout(self.run_form)
        self.run_rows.setContentsMargins(0, 0, 0, 0)
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
        self.fields = {"isotope": self.f_iso, "method": self.f_method, "molecule": self.f_mol,
                       "conditions": self.f_cond, "color": self.f_color}
        for label, key in (("Isotope", "isotope"), ("Method", "method"),
                           ("Molecule", "molecule"), ("Conditions", "conditions"),
                           ("Colour", "color")):
            self.run_rows.addRow(label, self.fields[key])
        v.addWidget(self.run_form)
        self.f_info = QLabel()
        self.f_info.setWordWrap(True)
        self.f_info.setStyleSheet(GREY + "font-size:11px;")
        self.f_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.f_info)
        return w

    def _spikes_step(self):
        w, v = self._section("spikes", (
            ("spikes", "Spikes", "The excluded spikes, from the bridged point to their height; "
                                 "a ring on one put back (their style: Options › Chromatogram)"),
            ("raw", "Trace as recorded", "Before the spikes were excluded; its style: Options "
                                         "› Chromatogram")))
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
        self.sens = QSlider(Qt.Horizontal)
        self.sens.setRange(6, 30)                   # n σ × 2: 3 … 15 σ by 0.5
        self.sens.setToolTip("How far above the points around it a point must be: lower finds "
                             "more spikes, higher fewer (a new run's: Options › Spikes)")
        self.sens.sliderPressed.connect(lambda: self._push("spike threshold"))
        self.sens.valueChanged.connect(self._threshold)
        self.sens_lab = QLabel()
        self.spikes_auto = _auto_button(
            "Spikes found on their own: on load, and as the threshold moves (Options › Spikes)",
            lambda on: self._auto_set("spikes", on))
        v.addLayout(_find_row(
            _button("Find spikes", "Flag the spikes with this rule (the ones put back stay "
                                   "back)", self._find_spikes),
            self.spikes_auto, self.sens, self.sens_lab,
            _gear(more, "The rule's window and widest spike")))
        self.spike_list = QListWidget()
        self.spike_list.setToolTip("A spike: one point far above both its neighbours — a "
                                   "detector artefact, not activity — excluded and bridged by "
                                   "the straight line between them. Click one: the plot shows "
                                   "it. Untick it to keep it. Drag the bar below to resize.")
        self.spike_list.itemChanged.connect(self._spike_ticked)
        self.spike_list.itemClicked.connect(self._spike_focus)
        _sized(v, self.spike_list)
        return w

    def _bg_step(self):
        w, v = self._section("background")
        self.bg_group = QButtonGroup(w)
        self.bg_radio, self.bg_rows = {}, {}
        line_tip = "Its line on the plot (its style: Options › Chromatogram)"
        for mode, text, tip in (
                ("none", "None", "Nothing subtracted: the counts as recorded"),
                ("auto", "Mean outside the regions", "The detector's background: the mean of "
                 "every point no region holds (points 4 σ above it left out). A radio-"
                 "detector's background is flat: its count rate, with Poisson noise"),
                ("stretch", "Mean of a stretch", "The mean of a peak-free stretch: drag its "
                 "edges on the plot, type them, or draw it again"),
                ("drift", "Follows a drift", "For a trace whose background drifts: SNIP or "
                 "arPLS")):
            rb = QRadioButton(text)
            rb.setToolTip(tip)
            self.bg_group.addButton(rb)
            self.bg_radio[mode] = rb
            rb.toggled.connect(lambda on, m=mode: on and self._bg_mode(m))
            parts = [rb]
            if mode == "drift":
                self.bg_method = QComboBox()
                self.bg_method.addItems(["SNIP", "arPLS"])
                self.bg_method.activated.connect(
                    lambda i: self._bg_set("bg_drift", ("snip", "arpls")[i]))
                self.bg_n = QSpinBox()
                self.bg_n.setRange(2, 1000)
                self.bg_n.setToolTip("SNIP: about a peak's half-width, in points")
                self.bg_n.valueChanged.connect(lambda val: self._bg_set("bg_n", val))
                parts += [self.bg_method, self.bg_n]
            if mode == "stretch":
                parts.append(self._view_tick("stretch", "stretch", "The stretch shaded, its "
                                                                   "edges dashed"))
            if mode != "none":                       # last: every row's line tick aligned
                parts.append(self._view_tick(f"line_{mode}", "line", line_tip))
            self.bg_rows[mode] = row = QWidget()
            _row_into(row, parts)
            v.addWidget(row)
            if mode == "stretch":
                self.bg_from, self.bg_to = _minutes(), _minutes()
                for s in (self.bg_from, self.bg_to):
                    s.valueChanged.connect(self._stretch_typed)
                self.bg_draw = QPushButton("Draw")
                self.bg_draw.setCheckable(True)
                self.bg_draw.setToolTip("Then drag across a stretch with no peak, or click its "
                                        "two edges; right-click cancels")
                self.bg_draw.toggled.connect(lambda on: self._arm("stretch", on))
                self.bg_span = QWidget()
                _row_into(self.bg_span, [QLabel("from"), self.bg_from, QLabel("to"),
                                         self.bg_to, QLabel("min"), self.bg_draw], indent=22)
                v.addWidget(self.bg_span)
        return w

    def _peaks_step(self):
        w, v = self._section("peaks")
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
        self.find_sens = QSlider(Qt.Horizontal)
        self.find_sens.setRange(4, 40)               # n σ × 2: 2 … 20 σ by 0.5
        self.find_sens.setToolTip("How far above its surroundings an apex must stand, in σ of "
                                  "the background noise: lower finds more, higher fewer (a new "
                                  "run's: Options › Regions)")
        self.find_sens.sliderPressed.connect(lambda: self._push("region threshold"))
        self.find_sens.valueChanged.connect(self._find_threshold)
        self.find_lab = QLabel()
        self.find_auto = _auto_button(
            "Regions found on their own: on load, and as the threshold moves (Options › "
            "Regions)", lambda on: self._auto_set("find", on))
        v.addLayout(_find_row(
            _button("Find regions", "Regions for the peaks no region holds (the ones found "
                                    "before and left untouched are found again): a moving "
                                    "mean standing the threshold above its surroundings, with "
                                    "more counts than the detection limit", self._find),
            self.find_auto, self.find_sens, self.find_lab,
            _gear(more, "Apexes' spacing, the moving mean, the feet")))
        self.reg_draw = QPushButton("Draw region")
        self.reg_draw.setCheckable(True)
        self.reg_draw.setToolTip("A region: a span integrated as one — a peak, or a peak's "
                                 "shoulder. Then drag across it on the plot, or click its two "
                                 "edges (right-click or Esc cancels); its edges land in the "
                                 "valleys (hold Alt to place them exactly). On the plot, drag "
                                 "an edge to move it, ← → to nudge it a point.")
        self.reg_draw.toggled.connect(lambda on: self._arm("region", on))
        v.addWidget(self.reg_draw)
        t = self.reg_list = QTableWidget(0, 3)
        t.setHorizontalHeaderLabels(["Region", "Rt (min)", "%"])
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(22)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2):
            t.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        t.setShowGrid(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        t.setToolTip("Click one to select it; double-click: the plot shows it; right-click: "
                     "rename, edit, remove; Del removes the selected ones. Drag the bar below "
                     "to resize.")
        t.currentCellChanged.connect(lambda r, *_: self._filling or self._pick_region(r))
        t.cellDoubleClicked.connect(lambda r, _c: self._region_focus(r))
        t.itemChanged.connect(self._renamed)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(lambda pos: self._region_menu(t, pos))
        _sized(v, t)
        return w

    def _view_tick(self, key, text, tip):
        """A tick for what the plot shows (self.view), kept in step by _fill_steps."""
        c = QCheckBox(text)
        c.setToolTip(tip)
        c.toggled.connect(lambda on: self._view(key, on))
        self.ticks[key] = c
        return c

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
        for w in (self.names_win, self.regions_win, self.region_win, self.figure_win,
                  self.report_win):
            if w is not None:
                w.refresh_later()

    def _fill_steps(self):
        self._filling = True
        run, res = self.sel, self.results.get(self.sel.id) if self.sel else None
        for key, c in self.ticks.items():
            c.setChecked(self.view[key] if key in self.view else getattr(self.plot_opts, key))
        self.spikes_auto.setChecked(PREFS["spikes"]["auto"])
        self.find_auto.setChecked(PREFS["find"]["auto"])
        self.y_mode.setCurrentIndex(max(0, self.y_mode.findData(self.plot_opts.y_mode)))
        _sync(self.run_list, [(r.name, r.shown, r.id, None, r.color) for r in self.runs],
              Qt.ItemIsEditable)
        for k, r in enumerate(self.runs):
            self.run_list.item(k).setToolTip(r.name)
        if run is not None:
            if self.run_list.currentRow() != self.runs.index(run):
                self.run_list.setCurrentRow(self.runs.index(run))
        else:
            self.run_list.setCurrentRow(-1)
            self.run_list.clearSelection()
        for key, wdg in self.fields.items():
            self.run_rows.setRowVisible(wdg, PREFS["run_fields"][key])
        self.f_info.setVisible(PREFS["run_fields"]["details"])
        for key in ("spikes", "background", "peaks"):
            self.body[key].setEnabled(run is not None)
        self.run_form.setEnabled(run is not None)
        if run is None:
            for key in ("spikes", "background", "peaks"):
                self.step[key].set_title(f"{TITLES[key]} · select a run")
            self.f_info.setText("")
            self.spike_list.clear()
            self.reg_list.setRowCount(0)
            self._filling = False
            return
        # runs
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
                            ).replace("_", "_​"))   # a long file name wraps, not the panel
        # spikes
        n_ex = int(run.excluded().sum())
        self.step["spikes"].set_title(f"{TITLES['spikes']} · {n_ex} excluded"
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
        # background
        self.step["background"].set_title(f"{TITLES['background']} · {res.background:.1f} cps")
        self.step["background"].setToolTip(f"{res.background:.2f} cps — {res.background_how}")
        self.bg_radio[run.bg_mode].setChecked(True)
        for mode, row in self.bg_rows.items():
            row.setVisible(PREFS["bg"]["offer"][mode] or run.bg_mode == mode)
        self.bg_span.setVisible(self.bg_rows["stretch"].isVisible())
        a, b = sorted(run.bg_stretch or [PREFS["bg"]["stretch_from"], PREFS["bg"]["stretch_to"]])
        self.bg_from.setValue(a)
        self.bg_to.setValue(b)
        self.bg_span.setEnabled(run.bg_mode == "stretch")
        self.bg_method.setCurrentIndex(1 if run.bg_drift == "arpls" else 0)
        self.bg_n.setValue(run.bg_n)
        self.bg_n.setEnabled(run.bg_drift == "snip")
        # regions
        self.step["peaks"].set_title(f"{TITLES['peaks']} · {len(run.regions)}")
        fp = run.find_params
        self.find_sens.setValue(int(round(fp.n_sigma * 2)))
        self.find_lab.setText(f"{fp.n_sigma:.1f} σ")
        self.f_gap.setValue(fp.min_gap_s)
        self.f_smooth.setValue(fp.smooth)
        self.f_foot.setValue(fp.foot_sigma)
        t = self.reg_list
        t.setRowCount(len(run.regions))
        for k, (reg, row) in enumerate(zip(run.regions, res.rows)):
            pct = (f"{row.pct:.1f}" if row.pct is not None else
                   "n.d." if "n.d." in row.flags else "")
            for c, text in enumerate((row.name, f"{row.rt:.2f}", pct)):
                it = t.item(k, c)
                if it is None:
                    it = QTableWidgetItem()
                    t.setItem(k, c, it)
                it.setText(text)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                            | (Qt.ItemIsEditable if c == 0 else Qt.NoItemFlags))
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.item(k, 0).setIcon(_swatch(reg.color or run.color))
        k = self.sel_region
        if k < 0:
            t.clearSelection()
        elif t.currentRow() != k:
            t.setCurrentCell(k, 0)
        self._filling = False

    def _fill_table(self):
        self._filling = True
        t = self.table
        res = self.results.get(self.sel.id) if self.sel else None
        if res is None:
            t.setRowCount(0)
            t.setColumnCount(0)
            self.summary.setText("Select a run (Runs) to see its results." if self.runs
                                 else "")
            self._filling = False
            return
        run = self.sel
        cols = columns("table_cols")
        head, body, extra = result_rows(res, "table_cols")
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

    def _run_of(self, it):
        """The run a list item stands for (by its id: rows move while a run is dragged)."""
        return next((r for r in self.runs if it is not None and r.id == it.data(Qt.UserRole)),
                    None)

    def _runs_moved(self, *_):
        """Runs dragged into a new order: the list's order is the runs'."""
        order = [self._run_of(self.run_list.item(k)) for k in range(self.run_list.count())]
        if self._filling or None in order or order == self.runs:
            return
        self._push("reorder the runs")
        self.runs = order
        self.refresh()

    def _run_item_changed(self, it):
        run = None if self._filling else self._run_of(it)
        if run is None:
            return
        if it.text() != run.name:                        # typed in the list
            self.rename(run, it.text())
        elif (it.checkState() == Qt.Checked) != run.shown:
            run.shown = it.checkState() == Qt.Checked
            self.refresh()

    def _run_picked(self, row):
        if not self._filling:
            self._select(self._run_of(self.run_list.item(row)))

    def _run_menu(self, pos):
        run = self._run_of(self.run_list.itemAt(pos))
        if run is None:
            return
        self._select(run)
        m = QMenu(self)
        m.addAction("Rename", lambda: self.run_list.editItem(
            self.run_list.item(self.runs.index(run))))
        m.addAction("Export the spikeless trace…", lambda: self._export_trace(run))
        m.addAction("Export the trace as recorded…", lambda: self._export_trace(run, True))
        m.addSeparator()
        m.addAction("Remove", lambda: self._remove_run(run))
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

    def set_run(self, run, key, value):
        """One thing about how a run is drawn (Figure › Traces): colour, line, width, fill."""
        if run not in self.runs or getattr(run, key) == value:
            return
        self._push(f"{key} of {run.name}")
        setattr(run, key, value)
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
        if PREFS["spikes"]["auto"]:
            run.detect_spikes()
        self.refresh()

    def _spike_param(self, key, val):
        run = self.sel
        if self._filling or run is None:
            return
        self._push(f"spike {key.replace('_', ' ')}")
        setattr(run.spike_params, key, val | 1 if key == "window" else val)
        if PREFS["spikes"]["auto"]:
            run.detect_spikes()
        self.refresh()

    def _find_spikes(self):
        run = self.sel
        if run is None:
            return
        self._push("find spikes")
        run.detect_spikes()
        self.refresh()
        self.log(f"Find spikes on '{run.name}' ({run.spike_params.n_sigma:g} σ): "
                 f"{int(run.excluded().sum())} excluded.")

    def _auto_set(self, key, on):
        """⟳ (Spikes, Regions): found on their own, or on a click — an option, for every run;
        switched on, it finds at once."""
        if self._filling or PREFS[key]["auto"] == on:
            return
        PREFS[key]["auto"] = on
        save_prefs()
        if self.options_win is not None:
            self.options_win._build()
        if on and self.sel is not None:
            (self._find_spikes if key == "spikes" else self._find)()

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

    def _drawn(self, a, b):
        """A region drawn on the plot, a to b (snapped there): cut back to overlap no other."""
        run = self.sel
        if run is None:
            return
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

    def _edge_moved(self, i, side, t):
        """Edge `side` of region i (-1: the background stretch) dropped at t (snapped there),
        kept off its neighbours; a shared edge moves for both."""
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

    def _region_menu(self, view, pos):
        """Right-click on a region, in the Regions list or the results: rename, edit, remove."""
        run, k = self.sel, view.rowAt(pos.y())
        if run is None or not 0 <= k < len(run.regions):
            return
        if k not in _rows_of(view):
            self._pick_region(k)
        m = QMenu(self)
        m.addAction("Rename", lambda: view.editItem(view.item(k, 0)))
        m.addAction("Edit…", self.region_panel)
        m.addSeparator()
        m.addAction("Remove", lambda: self._delete_regions(_rows_of(view) or [k]))
        m.exec(view.viewport().mapToGlobal(pos))

    def _region_focus(self, k):
        run = self.sel
        if run is not None and 0 <= k < len(run.regions):
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
            net = float(np.trapezoid((y - run.background()[0])[m], run.x[m])) * 60
            self.statusBar().showMessage(f"{a:.2f}–{b:.2f} min: {net:.0f} net counts", 2000)

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
        """A region's name typed in the results or the Regions list (its first column)."""
        run = self.sel
        if self._filling or run is None or it.column() or it.row() >= len(run.regions):
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
        if PREFS["find"]["auto"]:
            self._refind(run)
        self.refresh()

    def _find_param(self, key, val):
        run = self.sel
        if self._filling or run is None or getattr(run.find_params, key) == val:
            return
        self._push(f"find regions: {key.replace('_', ' ')}")
        setattr(run.find_params, key, int(val) | 1 if key == "smooth" else val)
        if PREFS["find"]["auto"]:
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
            if p.lower().endswith(session.EXT):
                self._open_session(p)
            elif p.lower().endswith(".txt"):
                self._load(p)

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", str(self._dir),
            f"GINA export or session (*.txt *{session.EXT});;GINA export (*.txt);;"
            f"Session (*{session.EXT})")
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
            r.spike_params = SpikeParams(**params("spikes"))
            if PREFS["spikes"]["auto"]:
                r.detect_spikes()
            else:                                    # left to Find spikes
                r.spikes, r.kept = np.zeros(len(r.y), bool), []
            r.find_params = FindParams(**params("find"))
            r.bg_mode = bg["mode"] if bg["offer"][bg["mode"]] else "auto"
            r.bg_stretch = [bg["stretch_from"], bg["stretch_to"]]
            r.bg_drift, r.bg_n = bg["drift"], bg["n"]
            if PREFS["find"]["auto"]:
                self._refind(r)
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
                        else "no spike." if PREFS["spikes"]["auto"]
                        else "spikes not looked for (Find spikes).")
                     + (f" {len(r.regions)} region(s) found." if PREFS["find"]["auto"] else ""))
        for w in warnings:
            self.log(f"  ⚠ {w}")

    def _save_session(self):
        if not self.runs:
            self.log("Save: nothing loaded yet.")
            return
        stem = re.sub(r'[\\/:*?"<>|]', "_", self.runs[0].name)
        name = self._session_path or self._dir / f"{stem}{session.EXT}"
        path, _ = QFileDialog.getSaveFileName(self, "Save session", str(name),
                                              f"Spikeless session (*{session.EXT})")
        if not path:
            return
        path = Path(path)
        if not path.name.lower().endswith(session.EXT):   # not with_suffix: names carry dots
            path = path.with_name(path.name + session.EXT)
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
            self._copy_screen()

    def _copy_screen(self):
        """The plot as it is on screen, to the clipboard (the figure has its own Copy)."""
        pm = self.canvas.grab()
        QApplication.clipboard().setPixmap(pm)
        self.log(f"Plot copied as on screen ({pm.width()} × {pm.height()} px).")

    def _copy_results(self):
        if self.sel is None:
            return
        head, body, extra = result_rows(self.results[self.sel.id], "table_cols")
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

    def region_panel(self):
        if self.region_win is None:
            self.region_win = RegionPanel(self)
        self.region_win.open()

    def _figure(self):
        if self.figure_win is None:
            self.figure_win = FigureWindow(self)
        self.figure_win.open()

    def closeEvent(self, e):
        for w in (self.options_win, self.report_win, self.figure_win, self.names_win,
                  self.regions_win, self.region_win):
            if w is not None:      # or the app stays up with them
                w.close()
        super().closeEvent(e)


# ---------------- small helpers
def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#3a3a3a;")
    return f


def _row_into(w, widgets, indent=0):
    """widgets side by side in w, the first one taking the room."""
    h = QHBoxLayout(w)
    h.setContentsMargins(indent, 0, 0, 0)
    for k, wdg in enumerate(widgets):
        h.addWidget(wdg, 1 if k == 0 and not indent else 0)
    if indent:
        h.addStretch(1)


def _button(text, tip, slot):
    b = QPushButton(text)
    b.setToolTip(tip)
    b.clicked.connect(lambda _=False: slot())
    return b


def _auto_button(tip, on_toggle):
    """⟳: the step runs on its own (green when on)."""
    b = QToolButton()
    b.setText("⟳")
    b.setCheckable(True)
    b.setToolTip(tip)
    b.setStyleSheet("QToolButton { font-size: 15px; padding: 0 3px; color: #8d8d8d; }"
                    "QToolButton:checked { color: #4caf50; }")
    b.toggled.connect(on_toggle)
    return b


def _gear(content, tip):
    """⚙: content (a form) in a popup under it."""
    b = QToolButton()
    b.setText("⚙")
    b.setToolTip(tip)
    b.setPopupMode(QToolButton.InstantPopup)
    b.setStyleSheet("QToolButton::menu-indicator { image: none; }")
    m = QMenu(b)
    act = QWidgetAction(m)
    act.setDefaultWidget(content)
    m.addAction(act)
    b.setMenu(m)
    guard_fields(content)
    return b


def _find_row(*widgets):
    """[Find…] [⟳] [threshold ────] [n σ] [⚙]"""
    h = QHBoxLayout()
    for wdg in widgets:
        h.addWidget(wdg, 1 if isinstance(wdg, QSlider) else 0)
    return h


class _Grip(QWidget):
    """A bar under a list: drag it to make the list taller or shorter."""

    def __init__(self, target):
        super().__init__()
        self.target = target
        self.setFixedHeight(7)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag to resize")
        self._from = None

    def paintEvent(self, e):                            # noqa: N802 - Qt's name
        p = QPainter(self)
        p.setPen(QColor("#6a6a6a"))
        c = self.width() // 2
        for dx in (-8, -4, 0, 4, 8):
            p.drawPoint(c + dx, 3)

    def mousePressEvent(self, e):                       # noqa: N802
        self._from = (e.globalPosition().y(), self.target.height())

    def mouseMoveEvent(self, e):                        # noqa: N802
        if self._from:
            y, h = self._from
            self.target.setFixedHeight(max(40, int(h + e.globalPosition().y() - y)))

    def mouseReleaseEvent(self, e):                     # noqa: N802
        self._from = None


def _sized(layout, view, rows=5):
    """view into layout, as tall as `rows` rows, with a bar under it to drag it taller."""
    if isinstance(view, QTableWidget):
        h = view.horizontalHeader().sizeHint().height() + view.verticalHeader().defaultSectionSize() * rows
    else:
        h = max(view.fontMetrics().height() + 6, 20) * rows
    view.setFixedHeight(h + 2 * view.frameWidth() + 2)
    layout.addWidget(view)
    layout.addWidget(_Grip(view))


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
    s.setButtonSymbols(QDoubleSpinBox.NoButtons)    # compact: type it, or the wheel, ↑ ↓
    s.setFixedWidth(52)
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
