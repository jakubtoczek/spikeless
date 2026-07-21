"""Spikeless main window (PySide6 + matplotlib)."""

from __future__ import annotations

import copy
import datetime as _dt
import io
import json
from dataclasses import dataclass, field
from html import escape as _esc
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QTextBrowser,
    QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import io_gina
from .adjust import (BASELINE_LABELS, ISOTOPES, AdjustParams, decay_factor, estimate_baseline,
                     lookup_half_life_s)
from .dataset import Condition, Curve, Dataset, new_curve_from, new_id
from .peaks import PeakParams, analyze_peaks, detect_peaks
from .plotting import BORDER_STYLES, ExportBorder, PlotOptions, auto_extents, build_figure
from .plotview import Background, ZoomableFigureView
from .spikes import SpikeParams, detect, remove
from .viz import BaselineViz, PeakViz, SpikeViz

APP_NAME = "Spikeless"

_UNIT_S = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
_LEGEND_LOCS = ["upper right", "upper left", "lower right", "lower left", "center right", "best"]
_INTERP_METHODS = [("linear", "Linear (n-1 → n+1)"), ("pchip", "PCHIP monotone cubic")]
_LINESTYLES = ["solid", "dotted", "dashed", "dashdot"]
_MARKERS = ["v", "^", "o", "s", "D", "x", "+", "*"]
_ANNOT = [("none", "None"), ("rt", "Rt"), ("auc", "%"), ("both", "Rt + %")]


def _parse_run_dt(s):
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return _dt.datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


# Processing features (key, button label, run-slot name, gear-slot name) in PIPELINE order.
# Spikes first (electronic artefact, unrelated to activity → must precede decay); then decay
# (activity correction) before baseline & peaks so AUC/% reflect the corrected signal.
PROC_FEATURES = [
    ("spikes", "Detect spikes", "_detect_spikes", "_edit_spike_params"),
    ("decay", "Apply decay", "_apply_decay", "_edit_decay_options"),
    ("baseline", "Detect baseline", "_detect_baseline", "_edit_baseline_params"),
    ("peaks", "Detect peaks", "_detect_peaks", "_edit_peak_params"),
]
# Post-detection "default display actions" per feature, shown in each button's collapsible
# (hidden by default). (step_key, checkbox label, default_on). Order = execution order.
# Spikes tells a little story (show spikes → pause → swap to spikeless, hide the original);
# baseline/peaks/decay just reveal their new artifact without touching anything else.
PROC_STEPS = {
    "spikes": [
        ("show_spikes", "display spikes", True),
        ("delay", "delay 0.5 s", True),
        ("show_result", "display spikeless curve", True),
        ("hide_original", "hide original curve & spikes", True),
    ],
    "decay": [("show_result", "display decay curve", True)],
    "baseline": [("show_result", "display baseline", True)],
    "peaks": [("show_result", "display peaks", True)],
}

# Dockable menu windows (key, attribute name) — used for the "open by default" option.
DOCK_KEYS = [("data", "data_dock"), ("processing", "processing_dock"),
             ("log", "log_dock"), ("report", "report_dock"), ("plot_options", "display_dock")]

# Peak-table columns (key, header, value(i, pk)) — the same spec drives the report table, the
# clipboard copy and the CSV export, so what's shown is exactly what's copied/exported.
PEAK_COLUMNS = [
    ("num", "#", lambda i, pk: str(i)),
    ("name", "Peak", lambda i, pk: pk.name or f"peak {i}"),
    ("rt", "Rt (min)", lambda i, pk: f"{pk.rt:.2f}"),
    ("x_start", "x start", lambda i, pk: f"{pk.x_start:.2f}"),
    ("x_end", "x end", lambda i, pk: f"{pk.x_end:.2f}"),
    ("width", "width", lambda i, pk: f"{pk.length:.2f}"),
    ("y_max", "y max", lambda i, pk: f"{pk.y_max:.0f}"),
    ("auc", "AUC", lambda i, pk: f"{pk.auc:.1f}"),
    ("pct", "%", lambda i, pk: f"{pk.pct:.1f}"),
    ("skew", "skew", lambda i, pk: f"{pk.skew:.2f}"),
]
_DEFAULT_PEAK_COLS = {"num": True, "name": False, "rt": True, "x_start": False, "x_end": False,
                      "width": False, "y_max": False, "auc": True, "pct": True, "skew": False}


@dataclass
class AppOptions:
    background: Background = field(default_factory=Background)
    lock_docks: bool = True
    export_border: ExportBorder = field(default_factory=ExportBorder)
    scale_max: int = 5   # top of the resolution slider (× plot size)
    # which Processing buttons are shown (Apply decay hidden by default)
    proc_visible: dict = field(default_factory=lambda: {
        "spikes": True, "baseline": True, "peaks": True, "decay": False})
    # which menu windows open by default (Plot options starts hidden)
    docks_open: dict = field(default_factory=lambda: {
        "data": True, "processing": True, "log": True, "report": True, "plot_options": False})


@dataclass
class ExportOptions:
    png_dpi: int = 600
    clip_dpi: int = 600          # clipboard copies at 600 dpi too (was 150)
    clip_format: str = "png"
    log_timestamps: bool = True  # include [HH:MM:SS] stamps when exporting/copying the log
    report_table_html: bool = True  # copy peak tables as rich HTML (else plain TSV)
    report_cols: dict = field(default_factory=lambda: dict(_DEFAULT_PEAK_COLS))  # which peak columns show


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — radio-HPLC plotting, spike removal & analysis")
        self.resize(1200, 800)
        self.setAcceptDrops(True)
        icon = _app_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        self.datasets: list[Dataset] = []
        self.plot_opts = PlotOptions()
        self.spike_params = SpikeParams()
        self.interp_method = "linear"
        self.baseline_method = "min"
        self.baseline_n = 20
        self.peak_params = PeakParams()
        # per-feature default display actions (session state; edited via each button's collapsible)
        self.proc_steps = {k: {s: d for s, _l, d in steps} for k, steps in PROC_STEPS.items()}
        self.app_opts = AppOptions()
        self.export_opts = ExportOptions()
        self._settings = QSettings(APP_NAME, APP_NAME)
        self._load_settings()
        self.view_scale = 1.0        # resolution slider (× plot size, on-screen)
        self.scale_export = False    # also apply the slider to exports/clipboard
        self._fig = None
        self.d: dict = {}
        self._loading_disp = False
        self._plot_opts_shown_once = False
        self._undo_stack: list = []
        self._pen = _pen_icon()

        self._build_ui()
        QShortcut(QKeySequence.Undo, self, activated=self._undo)   # Ctrl+Z
        self._apply_lock()
        self._apply_default_docks()
        self._update_enabled()
        self._position_overlay()
        self.log(f"{APP_NAME} ready. Drag a GINA .txt file here or use Browse.")
        self._update_report()

    # ---------------- persisted preferences ----------------
    def _load_settings(self):
        """Restore the few user 'defaults' (Options dialog) from QSettings. Best-effort:
        a corrupt store must never stop the app starting."""
        s = self._settings
        try:
            self.app_opts.lock_docks = s.value("lock_docks", True, type=bool)
            self.app_opts.scale_max = int(s.value("scale_max", 5))
            pv = s.value("proc_visible", "")
            if pv:
                self.app_opts.proc_visible.update(json.loads(pv))
            do = s.value("docks_open", "")
            if do:
                self.app_opts.docks_open.update(json.loads(do))
            self.export_opts.png_dpi = int(s.value("png_dpi", 600))
            self.export_opts.clip_dpi = int(s.value("clip_dpi", 600))
            self.export_opts.clip_format = s.value("clip_format", "png")
            self.export_opts.log_timestamps = s.value("log_timestamps", True, type=bool)
            self.export_opts.report_table_html = s.value("report_table_html", True, type=bool)
            rc = s.value("report_cols", "")
            if rc:
                self.export_opts.report_cols.update(json.loads(rc))
            self.plot_opts.crop_fills = s.value("crop_fills", False, type=bool)
        except Exception as exc:  # noqa: BLE001
            print(f"settings load skipped: {exc}")

    def _save_settings(self):
        s = self._settings
        ao, eo = self.app_opts, self.export_opts
        s.setValue("lock_docks", ao.lock_docks)
        s.setValue("scale_max", ao.scale_max)
        s.setValue("proc_visible", json.dumps(ao.proc_visible))
        s.setValue("docks_open", json.dumps(ao.docks_open))
        s.setValue("png_dpi", eo.png_dpi)
        s.setValue("clip_dpi", eo.clip_dpi)
        s.setValue("clip_format", eo.clip_format)
        s.setValue("log_timestamps", eo.log_timestamps)
        s.setValue("report_table_html", eo.report_table_html)
        s.setValue("report_cols", json.dumps(eo.report_cols))
        s.setValue("crop_fills", self.plot_opts.crop_fills)

    def _apply_default_docks(self):
        for key, attr in DOCK_KEYS:
            dock = getattr(self, attr)
            if key == "plot_options":
                continue  # plot options stays hidden until data is loaded (see _update_enabled)
            dock.setVisible(self.app_opts.docks_open.get(key, True))

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    # ---------------- UI construction ----------------
    def _build_ui(self):
        self.plot_view = ZoomableFigureView()
        self.plot_view.set_background(self.app_opts.background)
        self.plot_view.filesDropped.connect(self._load_paths)
        self.plot_view.resized.connect(self._position_overlay)
        self.setCentralWidget(self.plot_view)

        # Overlays live on the VIEWPORT (not the frame) so scrollbars can't shove them
        # into the neighbouring dock when data loads.
        vp = self.plot_view.viewport()

        # top-right cluster: Copy, Export, gear — mirrors the Log/Report title-bar tools
        self.plot_tools = QWidget(vp)
        self.plot_tools.setObjectName("plotTools")
        self.plot_tools.setStyleSheet(
            "QWidget#plotTools{background:#3c3f41;border:1px solid #555;border-radius:3px;}"
            "QToolButton{color:#e0e0e0;border:none;padding:3px 7px;}"
            "QToolButton:hover{background:#4a4d4f;} QToolButton:disabled{color:#777;}")
        ht = QHBoxLayout(self.plot_tools)
        ht.setContentsMargins(2, 1, 2, 1)
        ht.setSpacing(0)
        self.plot_copy_btn = _tool("⧉ Copy", "Copy plot to clipboard", self._copy_plot)
        self.plot_export_btn = _tool("⭳ Export", "Export plot to PNG/SVG", self._export_plot)
        gear = _tool("⚙", "Plot copy / export options", self._edit_plot_export_options)
        for b in (self.plot_copy_btn, self.plot_export_btn, gear):
            ht.addWidget(b)
        self.plot_tools.adjustSize()
        vp.installEventFilter(self)   # keep overlays inset when scrollbars resize the viewport

        # resolution slider (× plot size on screen; optionally applied to export)
        self.scale_bar = QWidget(vp)
        self.scale_bar.setStyleSheet(
            "QWidget{background:#2b2b2b;color:#e0e0e0;border:1px solid #555;border-radius:3px;}")
        hb = QHBoxLayout(self.scale_bar)
        hb.setContentsMargins(6, 2, 6, 2)
        hb.setSpacing(4)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setMinimum(10)
        self.scale_slider.setMaximum(self.app_opts.scale_max * 10)
        self.scale_slider.setValue(10)
        self.scale_slider.setFixedWidth(90)
        self.scale_slider.valueChanged.connect(self._on_scale)
        self.scale_label = QLabel("1.0×")
        self.scale_export_chk = QCheckBox("export")
        self.scale_export_chk.toggled.connect(self._on_scale_export)
        hb.addWidget(QLabel("res"))
        hb.addWidget(self.scale_slider)
        hb.addWidget(self.scale_label)
        hb.addWidget(self.scale_export_chk)
        self.scale_bar.adjustSize()

        self.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.BottomDockWidgetArea)

        self._build_data_dock()
        self._build_processing_dock()
        self._build_display_dock()
        self._build_log_dock()
        self._build_report_dock()
        self.display_dock.hide()
        self._build_toolbar()

        self.splitDockWidget(self.log_dock, self.report_dock, Qt.Horizontal)
        self.resizeDocks([self.log_dock, self.report_dock], [150, 150], Qt.Vertical)
        self.resizeDocks([self.data_dock, self.processing_dock], [380, 110], Qt.Vertical)
        self.resizeDocks([self.display_dock], [300], Qt.Horizontal)
        self._refresh_plot()

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        tb.addWidget(browse)
        tb.addSeparator()
        for dock in (self.display_dock, self.data_dock, self.processing_dock,
                     self.log_dock, self.report_dock):
            tb.addWidget(self._dock_button(dock))
        tb.addSeparator()
        opt = QPushButton("Options")   # copy/export now live per-window (title bars + plot overlay)
        opt.clicked.connect(self._edit_app_options)
        tb.addWidget(opt)

    def _dock_button(self, dock):
        btn = QToolButton()
        act = dock.toggleViewAction()
        act.setText(dock.windowTitle())
        btn.setDefaultAction(act)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        return btn

    def _build_data_dock(self):
        self.data_dock = QDockWidget("Data", self)
        w = QWidget()
        lay = QVBoxLayout(w)
        self.data_tree = _DataTree()
        self.data_tree.setColumnCount(2)
        self.data_tree.setHeaderHidden(True)
        self.data_tree.header().setStretchLastSection(False)
        self.data_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.data_tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.data_tree.setColumnWidth(1, 26)
        self.data_tree.setDragDropMode(QAbstractItemView.InternalMove)  # drag to reorder (z-order)
        self.data_tree.setDropIndicatorShown(True)
        self.data_tree.currentItemChanged.connect(lambda *_: self._on_tree_select())
        self.data_tree.itemChanged.connect(self._on_tree_item_changed)
        self.data_tree.reordered.connect(self._reorder)
        lay.addWidget(self.data_tree)
        row = QHBoxLayout()
        self.btn_info = QPushButton("Info")
        self.btn_info.clicked.connect(self._edit_info)
        self.btn_adjust = QPushButton("Adjust")
        self.btn_adjust.clicked.connect(self._edit_adjust)
        self.btn_disp = QPushButton("Display…")
        self.btn_disp.clicked.connect(self._edit_node_display)
        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.clicked.connect(self._duplicate_curve)
        self.btn_export = QPushButton("Export…")
        self.btn_export.setToolTip("Export the selection (curve → GINA X; peaks → CSV)")
        self.btn_export.clicked.connect(self._export_selected)
        for b in (self.btn_info, self.btn_adjust, self.btn_disp, self.btn_dup, self.btn_export):
            row.addWidget(b)
        lay.addLayout(row)
        self.data_dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, self.data_dock)

    def _build_processing_dock(self):
        self.processing_dock = QDockWidget("Processing", self)
        self._proc_body = QWidget()
        self._proc_lay = QVBoxLayout(self._proc_body)
        self.processing_dock.setWidget(self._proc_body)
        self.addDockWidget(Qt.RightDockWidgetArea, self.processing_dock)
        self._populate_processing()

    def _populate_processing(self):
        """(Re)build the Processing buttons, showing only the features enabled in Options.
        Each button carries a collapsible list of default display actions (hidden by default)."""
        _clear_layout(self._proc_lay)
        for key, label, run_name, gear_name in PROC_FEATURES:
            if not self.app_opts.proc_visible.get(key, True):
                continue
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            r = QHBoxLayout()
            r.setContentsMargins(0, 0, 0, 0)
            toggle = QToolButton()
            toggle.setText("▸")
            toggle.setAutoRaise(True)
            toggle.setToolTip("Default display actions when this runs")
            b = QPushButton(label)
            b.clicked.connect(getattr(self, run_name))
            r.addWidget(toggle)
            r.addWidget(b, 1)
            r.addWidget(_gear(getattr(self, gear_name)))
            col.addLayout(r)
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(20, 0, 0, 3)
            bl.setSpacing(0)
            for skey, slabel, dflt in PROC_STEPS.get(key, []):
                cb = QCheckBox(slabel)
                cb.setChecked(self.proc_steps[key].get(skey, dflt))
                cb.toggled.connect(lambda on, k=key, s=skey: self.proc_steps[k].__setitem__(s, on))
                bl.addWidget(cb)
            body.setVisible(False)
            toggle.clicked.connect(lambda _=False, bd=body, tg=toggle:
                                   (bd.setVisible(not bd.isVisible()),
                                    tg.setText("▾" if bd.isVisible() else "▸")))
            col.addWidget(body)
            self._proc_lay.addWidget(box)
        self._proc_lay.addStretch(1)

    def _build_log_dock(self):
        self.log_dock = QDockWidget("Log", self)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setTitleBarWidget(_DockTitleBar(self.log_dock, [
            ("copy", "Copy", "Copy the log to the clipboard", self._copy_log),
            ("export", "Export", "Export the log to a .txt file", self._export_log),
            ("gear", "⚙", "Log copy / export options", self._edit_log_export_options),
        ]))
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

    def _build_report_dock(self):
        self.report_dock = QDockWidget("Report", self)
        self._report_text = ""          # plain-text mirror (for Copy/Export, no UI icons)
        self.report_view = QTextBrowser()
        self.report_view.setOpenLinks(False)   # the per-table ⧉ anchors are handled by us
        self.report_view.anchorClicked.connect(self._on_report_anchor)
        self.report_dock.setWidget(self.report_view)
        self.report_dock.setTitleBarWidget(_DockTitleBar(self.report_dock, [
            ("copy", "Copy", "Copy the whole report", self._copy_report),
            ("export", "Export", "Export the report to a .txt file", self._export_report),
            ("gear", "⚙", "Report copy / export options", self._edit_report_export_options),
        ]))
        self.addDockWidget(Qt.BottomDockWidgetArea, self.report_dock)

    def _on_report_anchor(self, url):
        parts = url.toString().split(":")
        if len(parts) == 3 and parts[0] == "copytable":
            self._copy_peak_table(int(parts[1]), int(parts[2]))

    def _visible_peak_columns(self):
        return [(k, h, f) for k, h, f in PEAK_COLUMNS if self.export_opts.report_cols.get(k, False)]

    def _peak_rows(self, cv):
        """Header + value rows for cv's peaks, using only the columns enabled in report options."""
        cols = self._visible_peak_columns()
        head = tuple(h for _k, h, _f in cols)
        rows = [tuple(f(i, pk) for _k, _h, f in cols) for i, pk in enumerate(cv.peaks, 1)]
        return head, rows

    def _copy_peak_table(self, ds_id, curve_id):
        ds = self._ds(ds_id)
        cv = ds.find_curve(curve_id) if ds else None
        if cv is None or not cv.peaks:
            self.log("Copy table: no peaks.")
            return
        head, body = self._peak_rows(cv)
        rows = [head] + body
        md = QMimeData()
        md.setText("\n".join("\t".join(r) for r in rows))
        if self.export_opts.report_table_html:
            md.setHtml("<table border=1 cellspacing=0 cellpadding=3>"
                       + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
                       + "</table>")
        QApplication.clipboard().setMimeData(md)
        self.log(f"Copied '{cv.name}' peak table ({len(cv.peaks)} rows).")

    def _copy_log(self):
        QApplication.clipboard().setText(self._log_text())
        self.log("Log copied to clipboard.")

    def _copy_report(self):
        QApplication.clipboard().setText(self._report_text)
        self.log("Report copied to clipboard.")

    def _log_text(self):
        text = self.log_view.toPlainText()
        if not self.export_opts.log_timestamps:
            import re
            text = re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", text, flags=re.MULTILINE)
        return text

    # ---------------- Display options dock ----------------
    def _build_display_dock(self):
        self.display_dock = QDockWidget("Plot options", self)
        host = QWidget()
        outer = QVBoxLayout(host)
        o = self.plot_opts

        pa = QWidget()
        f1 = _cform(pa)
        self.d["w_mm"] = _spin(10, 400, o.plot_w_mm, 1)
        self.d["h_mm"] = _spin(10, 400, o.plot_h_mm, 1)
        self.d["bg"] = _ColorButton(o.bg_color, self._apply_display)
        self.d["bg_a"] = _spin(0, 1, o.bg_alpha, 0.05)
        f1.addRow("Width (mm)", self.d["w_mm"])
        f1.addRow("Height (mm)", self.d["h_mm"])
        f1.addRow("Background", self.d["bg"])
        f1.addRow("Background alpha", self.d["bg_a"])

        mg = QWidget()
        f2 = _cform(mg)
        # total figure size = plot area + these label margins; Auto shows the computed value
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
        tw_auto.toggled.connect(tw.setDisabled)
        tw_auto.toggled.connect(self._apply_display)
        th_auto.toggled.connect(th.setDisabled)
        th_auto.toggled.connect(self._apply_display)
        tw.valueChanged.connect(self._apply_display)
        th.valueChanged.connect(self._apply_display)
        f2.addRow("Total width (mm)", _pair(tw_auto, tw))
        f2.addRow("Total height (mm)", _pair(th_auto, th))
        self.d["out"] = _ColorButton(o.outside_color, self._apply_display)
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
        f3.addRow("Legend position", self.d["leg_loc"])
        f3.addRow("Legend font", self.d["leg_font"])
        f3.addRow("Legend size", self.d["leg_size"])
        self.d["leg_loc"].currentIndexChanged.connect(self._apply_display)
        self.d["leg_font"].editingFinished.connect(self._apply_display)
        self.d["leg_size"].valueChanged.connect(self._apply_display)

        for k in ("w_mm", "h_mm", "bg_a", "out_a"):
            self.d[k].valueChanged.connect(self._apply_display)

        outer.addWidget(_Collapsible("Plot area", pa, expanded=True))
        outer.addWidget(_Collapsible("Margins", mg, expanded=False))
        outer.addWidget(_Collapsible("Legend", lg, expanded=False))
        outer.addWidget(_Collapsible("Y axis", self._axis_group("y", o.y), expanded=False))
        outer.addWidget(_Collapsible("X axis", self._axis_group("x", o.x), expanded=False))
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        self.display_dock.setWidget(scroll)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.display_dock)

    def _axis_group(self, pfx, ax):
        g = QWidget()
        f = _cform(g)
        t = QLineEdit(ax.title)
        self.d[f"{pfx}_title"] = t
        f.addRow("Axis title", t)
        t.editingFinished.connect(self._apply_display)
        self._auto_field(f, "Min", pfx, "min", ax.vmin, -1e9, 1e9, 1)
        self._auto_field(f, "Max", pfx, "max", ax.vmax, -1e9, 1e9, 1)
        self._auto_field(f, "Major interval", pfx, "maj", ax.major, 0, 1e9, 0.25)
        self._auto_field(f, "Graduation start", pfx, "gstart", ax.grad_start, -1e9, 1e9, 1)
        self._auto_field(f, "Graduation end", pfx, "gend", ax.grad_end, -1e9, 1e9, 1)
        minor = QCheckBox()
        minor.setChecked(ax.minor_on)
        self.d[f"{pfx}_minor"] = minor
        f.addRow("Minor ticks", minor)
        minor.toggled.connect(self._apply_display)
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
            s.valueChanged.connect(self._apply_display)
        tlw = _spin(0.1, 3, ax.tick_lw_pt, 0.1)
        tlw_auto = QCheckBox("Auto (= axis)")
        tlw_auto.setChecked(ax.tick_lw_auto)
        tlw.setEnabled(not ax.tick_lw_auto)
        self.d[f"{pfx}_ticklw"] = tlw
        self.d[f"{pfx}_ticklw_auto"] = tlw_auto
        tlw_auto.toggled.connect(tlw.setDisabled)
        tlw_auto.toggled.connect(self._apply_display)
        tlw.valueChanged.connect(self._apply_display)
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
        gcolor = _ColorButton(ax.grid_color, self._apply_display)
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
            wdg.valueChanged.connect(self._apply_display)
        grid.toggled.connect(self._apply_display)
        gstyle.currentIndexChanged.connect(self._apply_display)
        return g

    def _auto_field(self, form, label, pfx, name, value, lo, hi, step):
        chk = QCheckBox("Auto")
        chk.setChecked(value is None)
        spin = _spin(lo, hi, value if value is not None else 0.0, step)
        spin.setEnabled(value is not None)
        self.d[f"{pfx}_{name}"] = spin
        self.d[f"{pfx}_{name}_auto"] = chk
        chk.toggled.connect(spin.setDisabled)
        chk.toggled.connect(self._apply_display)
        spin.valueChanged.connect(self._apply_display)
        form.addRow(label, _pair(chk, spin))

    def _apply_display(self, *_):
        if self._loading_disp or not self.d:
            return
        o, d = self.plot_opts, self.d
        o.plot_w_mm, o.plot_h_mm = d["w_mm"].value(), d["h_mm"].value()
        o.total_w_mm = None if d["tot_w_auto"].isChecked() else d["tot_w"].value()
        o.total_h_mm = None if d["tot_h_auto"].isChecked() else d["tot_h"].value()
        o.bg_color, o.bg_alpha = d["bg"].color, d["bg_a"].value()
        o.outside_color, o.outside_alpha = d["out"].color, d["out_a"].value()
        o.legend_loc = d["leg_loc"].currentText()
        o.legend_font_family = d["leg_font"].text() or "sans-serif"
        o.legend_font_size = d["leg_size"].value()
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
        self._refresh_plot()

    def _fill_auto_fields(self):
        if not self.datasets or not self.d:
            return
        ex = auto_extents(self.datasets, self.plot_opts)
        self._loading_disp = True
        for k, v in (("x_min", ex["xmin"]), ("x_max", ex["xmax"]), ("x_maj", ex["xmajor"]),
                     ("x_gstart", ex["xmin"]), ("x_gend", ex["xmax"]),
                     ("y_min", ex["ymin"]), ("y_max", ex["ymax"]), ("y_maj", ex["ymajor"]),
                     ("y_gstart", ex["ymin"]), ("y_gend", ex["ymax"])):
            if self.d[f"{k}_auto"].isChecked():
                self.d[k].setValue(v)
        if self._fig is not None:   # show the computed total size while Auto is ticked
            if self.d["tot_w_auto"].isChecked():
                self.d["tot_w"].setValue(self._fig.get_figwidth() * 25.4)
            if self.d["tot_h_auto"].isChecked():
                self.d["tot_h"].setValue(self._fig.get_figheight() * 25.4)
        self._loading_disp = False

    # ---------------- Data tree ----------------
    def _ds_label(self, ds):
        return ds.meta.name

    def _add_cross(self, item, data):
        b = QPushButton("✖")
        b.setFixedSize(20, 18)
        b.setStyleSheet("QPushButton{color:#ff5555;border:none;font-weight:bold;}")
        b.clicked.connect(lambda _=False, dd=data: self._remove_node(dd))
        self.data_tree.setItemWidget(item, 1, b)

    def _mk(self, parent, text, data, *, checkable=False, checked=True, editable=False,
            cross=True, draggable=False):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, data)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if checkable:
            flags |= Qt.ItemIsUserCheckable
        if editable:
            flags |= Qt.ItemIsEditable
        if draggable:
            flags |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        it.setFlags(flags)
        if editable:
            it.setIcon(0, self._pen)
        if checkable:
            it.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        (parent.addChild(it) if isinstance(parent, QTreeWidgetItem)
         else self.data_tree.addTopLevelItem(it))
        if cross:
            self._add_cross(it, data)
        return it

    def _build_curve_item(self, parent_item, ds, curve, is_root):
        cit = self._mk(parent_item, curve.name, ("curve", ds.id, curve.id),
                       checkable=True, checked=curve.shown, editable=True, cross=not is_root,
                       draggable=True)
        if curve.has_spikes:
            sit = self._mk(cit, "spikes", ("spikes", ds.id, curve.id),
                           checkable=True, checked=curve.spikes_group_shown)
            idxs = curve.spike_indices()
            shown = curve.spike_shown
            for i, si in enumerate(idxs):
                sh = True if shown is None else bool(shown[i])
                self._mk(sit, f"spike @ {curve.x[si]:.2f} min  y={curve.y[si]:.0f}",
                         ("spike", ds.id, curve.id, i), checkable=True, checked=sh)
            sit.setExpanded(True)
        if curve.baseline is not None:
            self._mk(cit, "baseline", ("baseline", ds.id, curve.id),
                     checkable=True, checked=curve.baseline_shown)
        if curve.peaks:
            pit = self._mk(cit, "peaks", ("peaks", ds.id, curve.id),
                           checkable=True, checked=curve.peaks_group_shown)
            for i, pk in enumerate(curve.peaks):
                lbl = pk.name or (f"peak {i + 1}: Rt {pk.rt:.2f}  y {pk.y_max:.0f}  "
                                  f"AUC {pk.auc:.0f}  {pk.pct:.0f}%")
                self._mk(pit, lbl, ("peak", ds.id, curve.id, i),
                         checkable=True, checked=pk.shown, editable=True)
            pit.setExpanded(True)
        for child in curve.children:
            self._build_curve_item(cit, ds, child, is_root=False)
        cit.setExpanded(True)

    def _rebuild_tree(self):
        target = self._selected()
        self.data_tree.blockSignals(True)
        self.data_tree.clear()
        for ds in self.datasets:
            any_shown = any(c.shown for c in ds.curves())
            dit = self._mk(None, self._ds_label(ds), ("dataset", ds.id),
                           checkable=True, checked=any_shown, editable=True, draggable=True)
            self._build_curve_item(dit, ds, ds.root, is_root=True)
            dit.setExpanded(True)
        self.data_tree.blockSignals(False)
        self._select_id(target)
        self._on_tree_select()

    def _select_id(self, target):
        if target is None:
            return
        stack = [self.data_tree.topLevelItem(i) for i in range(self.data_tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if item.data(0, Qt.UserRole) == target:
                self.data_tree.setCurrentItem(item)
                return
            stack.extend(item.child(c) for c in range(item.childCount()))

    def _selected(self):
        item = self.data_tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def _ds(self, ds_id):
        return next((d for d in self.datasets if d.id == ds_id), None)

    def _sel_curve(self):
        data = self._selected()
        if not data:
            return None, None
        ds = self._ds(data[1])
        if ds is None:
            return None, None
        if data[0] == "dataset":
            return ds, ds.root
        return ds, ds.find_curve(data[2])

    def _on_tree_item_changed(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        self.data_tree.blockSignals(True)
        if bool(item.flags() & Qt.ItemIsUserCheckable):
            state = item.checkState(0)
            self._set_shown(data, state == Qt.Checked)
            self._cascade(item, state)  # unticking a parent unticks its children
        if bool(item.flags() & Qt.ItemIsEditable):
            self._set_name(data, item.text(0))
        self.data_tree.blockSignals(False)
        self._refresh_plot()

    def _cascade(self, item, state):
        for i in range(item.childCount()):
            ch = item.child(i)
            if bool(ch.flags() & Qt.ItemIsUserCheckable):
                ch.setCheckState(0, state)
                d = ch.data(0, Qt.UserRole)
                if d:
                    self._set_shown(d, state == Qt.Checked)
            self._cascade(ch, state)

    def _set_shown(self, data, shown):
        ds = self._ds(data[1])
        if ds is None:
            return
        kind = data[0]
        if kind == "curve":
            ds.find_curve(data[2]).shown = shown
        elif kind == "spikes":
            ds.find_curve(data[2]).spikes_group_shown = shown
        elif kind == "baseline":
            ds.find_curve(data[2]).baseline_shown = shown
        elif kind == "peaks":
            ds.find_curve(data[2]).peaks_group_shown = shown
        elif kind == "spike":
            c = ds.find_curve(data[2])
            n = len(c.spike_indices())
            if c.spike_shown is None:
                import numpy as np
                c.spike_shown = np.ones(n, bool)
            c.spike_shown[data[3]] = shown
        elif kind == "peak":
            ds.find_curve(data[2]).peaks[data[3]].shown = shown

    def _set_name(self, data, text):
        ds = self._ds(data[1])
        if ds is None:
            return
        if data[0] == "dataset":
            ds.meta.name = text
        elif data[0] == "curve":
            c = ds.find_curve(data[2])
            c.name = text
            c.legend_label = text
        elif data[0] == "peak":
            ds.find_curve(data[2]).peaks[data[3]].name = text

    def _remove_node(self, data):
        ds = self._ds(data[1])
        if ds is None:
            return
        self._push_undo()
        kind = data[0]
        if kind == "dataset":
            self.datasets.remove(ds)
        elif kind == "curve":
            parent = ds.parent_of(data[2])
            if parent is not None:
                parent.children = [c for c in parent.children if c.id != data[2]]
            else:
                self.datasets.remove(ds)  # removing the root removes the dataset
        elif kind in ("spikes", "baseline", "peaks"):
            c = ds.find_curve(data[2])
            if kind == "spikes":
                c.spike_mask = None
                c.spike_shown = None
            elif kind == "baseline":
                c.baseline = None
                c.style.fill = False
            else:
                c.peaks = None
        elif kind == "spike":
            c = ds.find_curve(data[2])
            idxs = c.spike_indices()
            c.spike_mask[idxs[data[3]]] = False
            c.spike_shown = None
        elif kind == "peak":
            c = ds.find_curve(data[2])
            del c.peaks[data[3]]
            analyze_peaks(c.x, c.y, c.peaks, c.baseline, c.peak_local_baseline)
        self.log(f"Removed {kind}.")
        self._rebuild_tree()
        self._update_enabled()
        self._refresh_plot()
        self._update_report()

    def _reorder(self, src, tgt, below):
        if not src:
            return
        if src[0] == "dataset" and (tgt is None or tgt[0] == "dataset"):
            self._push_undo()
            self._reorder_list(self.datasets, src[1], tgt[1] if tgt else None, below, lambda d: d.id)
        elif src[0] == "curve" and tgt and tgt[0] == "curve" and src[1] == tgt[1]:
            ds = self._ds(src[1])
            if ds is None:
                return
            ps, pt = ds.parent_of(src[2]), ds.parent_of(tgt[2])
            if ps is None or ps is not pt:  # only reorder curves that share a parent
                self.log("To reorder curves, drop onto a sibling curve (same parent).")
                return
            self._push_undo()
            self._reorder_list(ps.children, src[2], tgt[2], below, lambda c: c.id)
        else:
            self.log("Reorder: drop a dataset onto another dataset, or a curve onto a sibling curve.")
            return
        self._rebuild_tree()
        self._select_id(src)
        self._refresh_plot()
        self.log("Reordered (draw order).")

    @staticmethod
    def _reorder_list(lst, src_id, tgt_id, below, key):
        src = next((o for o in lst if key(o) == src_id), None)
        if src is None:
            return
        lst.remove(src)
        if tgt_id is None:   # dropped past the end
            lst.append(src)
            return
        idx = next((i for i, o in enumerate(lst) if key(o) == tgt_id), None)
        if idx is None:
            lst.append(src)
        else:
            lst.insert(idx + 1 if below else idx, src)

    def _on_tree_select(self):
        data = self._selected()
        kind = data[0] if data else None
        self.btn_info.setEnabled(kind is not None)        # info for whatever element is selected
        self.btn_adjust.setEnabled(kind == "curve")       # normalization is per-curve
        self.btn_disp.setEnabled(kind not in (None, "dataset"))
        self.btn_dup.setEnabled(kind == "curve")
        self.btn_export.setEnabled(kind in ("curve", "dataset", "peaks", "peak"))

    # ---------------- undo ----------------
    def _push_undo(self):
        """Snapshot the whole dataset tree before a mutating op so Ctrl+Z can restore it."""
        self._undo_stack.append(copy.deepcopy(self.datasets))
        del self._undo_stack[:-25]   # ponytail: cap depth at 25, deep undo isn't worth the RAM

    def _undo(self):
        if not self._undo_stack:
            self.log("Nothing to undo.")
            return
        self.datasets = self._undo_stack.pop()
        self._rebuild_tree()
        self._update_enabled()
        self._refresh_plot()
        self._update_report()
        self.log("Undo.")

    # ---------------- helpers ----------------
    def log(self, msg):
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")
        sb = self.log_view.verticalScrollBar()   # auto-scroll to the newest line
        sb.setValue(sb.maximum())

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Resize and hasattr(self, "plot_view")
                and obj is self.plot_view.viewport()):
            self._position_overlay()
        return super().eventFilter(obj, event)

    def _position_overlay(self):
        if not hasattr(self, "plot_tools"):
            return
        vp = self.plot_view.viewport()
        m = 8
        self.plot_tools.move(max(m, vp.width() - self.plot_tools.width() - m), m)
        self.plot_tools.raise_()
        if hasattr(self, "scale_bar"):
            self.scale_bar.move(m, max(m, vp.height() - self.scale_bar.height() - m))
            self.scale_bar.raise_()

    def _on_scale(self, v):
        self.view_scale = v / 10.0
        self.scale_label.setText(f"{self.view_scale:.1f}×")
        self._refresh_plot()

    def _on_scale_export(self, on):
        self.scale_export = on

    def _opts_scaled(self, factor):
        o = copy.deepcopy(self.plot_opts)
        o.plot_w_mm *= factor
        o.plot_h_mm *= factor
        return o

    def _export_fig(self):
        factor = self.view_scale if self.scale_export else 1.0
        return build_figure(self.datasets, self._opts_scaled(factor), border=self.app_opts.export_border)

    def _refresh_plot(self):
        if not self.datasets:
            self._fig = None
            self.plot_view.clear()
            return
        self._fig = build_figure(self.datasets, self._opts_scaled(self.view_scale),
                                 border=self.app_opts.export_border)
        self.plot_view.set_figure(self._fig, keep_view=True)
        self._fill_auto_fields()

    def _update_enabled(self):
        has = bool(self.datasets)
        self.display_dock.toggleViewAction().setEnabled(has)
        self.plot_copy_btn.setEnabled(has)
        self.plot_export_btn.setEnabled(has)
        if has:
            if self.app_opts.docks_open.get("plot_options") and not self._plot_opts_shown_once:
                self.display_dock.show()      # honour "open Plot options by default" once data arrives
                self._plot_opts_shown_once = True
        else:
            self.display_dock.hide()
            self._plot_opts_shown_once = False
        self._on_tree_select()

    def _apply_lock(self):
        base = QDockWidget.DockWidgetClosable
        feats = base if self.app_opts.lock_docks else (
            base | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        for dock in (self.data_dock, self.processing_dock, self.display_dock,
                     self.log_dock, self.report_dock):
            dock.setFeatures(feats)

    def _update_report(self):
        ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"{APP_NAME} report — {ts}", ""]
        html = ["<div style='font-family:Segoe UI,sans-serif;font-size:9pt;'>",
                f"<p style='color:#9aa;'>{APP_NAME} report — {ts}</p>"]
        for ds in self.datasets:
            lines.append(f"# {ds.meta.name}")
            html.append(f"<p style='font-weight:600;margin:6px 0 0 0;'># {_esc(ds.meta.name)}</p>")
            meta_items = [("file", ds.meta.original_filename)]
            if ds.run_datetime:
                meta_items.append(("run", ds.run_datetime))
            if ds.meta.molecule:
                meta_items.append(("molecule", ds.meta.molecule))
            if ds.meta.radioisotope:
                meta_items.append(("radioisotope", ds.meta.radioisotope))
            meta_items += [("condition", c.text()) for c in ds.conditions]
            for label, value in meta_items:
                lines.append(f"  {label}: {value}")
                html.append(f"<div style='margin-left:1em;color:#bbb;'>{label}: {_esc(str(value))}</div>")
            for cv in ds.curves():
                marks = []
                if cv.has_spikes:
                    marks.append(f"{len(cv.spike_indices())} spikes")
                if cv.baseline is not None:
                    marks.append("baseline")
                if cv.peaks:
                    marks.append(f"{len(cv.peaks)} peaks")
                suffix = f" — {', '.join(marks)}" if marks else ""
                lines.append(f"  curve '{cv.name}' [{cv.kind}]{suffix}")
                html.append(f"<div style='margin-left:1em;margin-top:4px;'>curve "
                            f"'<b>{_esc(cv.name)}</b>' [{_esc(cv.kind)}]{_esc(suffix)}</div>")
                if cv.peaks:
                    head, body = self._peak_rows(cv)
                    if head:
                        lines.append("      " + "  ".join(f"{h:>9}" for h in head))
                        for r in body:
                            lines.append("      " + "  ".join(f"{c:>9}" for c in r))
                    html.append(self._peak_table_html(ds, cv))
            lines.append("")
        html.append("</div>")
        self._report_text = "\n".join(lines)
        sb = self.report_view.verticalScrollBar()   # preserve place across the wholesale rebuild
        pos = sb.value()
        self.report_view.setHtml("".join(html))
        sb.setValue(min(pos, sb.maximum()))

    def _peak_table_html(self, ds, cv):
        head, body = self._peak_rows(cv)
        if not head:
            return ""   # all columns hidden
        rows = ["<tr>" + "".join(f"<th>{_esc(h)}</th>" for h in head) + "</tr>"]
        rows += ["<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in body]
        anchor = (f"<a href='copytable:{ds.id}:{cv.id}' title='Copy this table' "
                  f"style='text-decoration:none;font-size:11pt;'>⧉</a>")
        return (f"<div style='margin-left:2em;margin-top:2px;'>{anchor} "
                f"<span style='color:#9aa;'>copy table</span>"
                f"<table border='1' cellspacing='0' cellpadding='3' style='margin-top:2px;'>"
                + "".join(rows) + "</table></div>")

    # ---------------- loading ----------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".txt")
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._load_paths([u.toLocalFile() for u in e.mimeData().urls()
                          if u.toLocalFile().lower().endswith(".txt")])

    def _load_paths(self, paths):
        for p in paths:
            self._load(p)

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open GINA export", "", "Text (*.txt)")
        self._load_paths(paths)

    def _load(self, path):
        try:
            ds, warnings = io_gina.load(path)
        except Exception as exc:  # noqa: BLE001
            self.log(f"ERROR loading {Path(path).name}: {exc}")
            QMessageBox.warning(self, "Load failed", str(exc))
            return
        self._push_undo()
        self.datasets.append(ds)
        self._rebuild_tree()
        self._select_id(("curve", ds.id, ds.root.id))
        self.log(f"Loaded '{ds.meta.name}' ({len(ds.root.y)} points, dt={ds.dt_s:g}s, "
                 f"{ds.root.x[-1]:.2f} min) from {ds.meta.original_filename}")
        for w in warnings:
            self.log(f"  ⚠ {w}")
        self._update_enabled()
        self._refresh_plot()
        self._update_report()

    # ---------------- processing (acts on the selected curve) ----------------
    def _need_curve(self):
        ds, curve = self._sel_curve()
        if curve is None:
            self.log("Select a curve first.")
        return ds, curve

    def _detect_spikes(self):
        ds, curve = self._need_curve()
        if curve is None:
            return
        self._push_undo()
        mask = detect(curve.y, self.spike_params)
        n = int(mask.sum())
        steps = self.proc_steps["spikes"]
        if not n:
            curve.spike_mask = None
            self.log(f"No spikes on '{curve.name}'.")
            self._rebuild_tree()
            self._refresh_plot()
            self._update_report()
            return
        import numpy as np
        curve.spike_mask = mask
        curve.spike_shown = np.ones(n, bool)
        curve.spikes_group_shown = steps["show_spikes"]
        cleaned = remove(curve.y, mask, method=self.interp_method)
        child = next((c for c in curve.children if c.kind == "spikeless"), None)
        if child is None:
            child = new_curve_from(curve, cleaned, "spikeless", "spikeless", "#00a000")
            curve.children.append(child)
        else:
            child.y = cleaned
        child.shown = False   # phase 1: reveal the spikes on the original before swapping
        self.log(f"Detected {n} spike(s) on '{curve.name}' → spikeless child ({self.interp_method}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

        def phase2():   # phase 2: bring in the spikeless curve and (optionally) hide the original
            child.shown = steps["show_result"]
            if steps["hide_original"]:
                curve.shown = False
                curve.spikes_group_shown = False
            self._rebuild_tree()
            self._refresh_plot()
        if steps["delay"]:
            QTimer.singleShot(500, phase2)
        else:
            phase2()

    def _detect_baseline(self):
        ds, curve = self._need_curve()
        if curve is None:
            return
        self._push_undo()
        curve.baseline = estimate_baseline(curve.y, self.baseline_method, self.baseline_n)
        curve.baseline_shown = self.proc_steps["baseline"]["show_result"]
        self.log(f"Baseline on '{curve.name}' ({self.baseline_method}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _detect_peaks(self):
        data = self._selected()
        ds, curve = self._need_curve()
        if curve is None:
            return
        # On a curve → fresh peaks group; on an existing peak/peaks group → reprocess (re-detect
        # with the current options). Both replace this curve's single peaks group.
        reprocess = bool(data) and data[0] in ("peak", "peaks")
        self._push_undo()
        sig = curve.y
        if curve.spike_mask is not None:   # don't let spikes become peaks or truncate neighbours
            sig = remove(curve.y, curve.spike_mask, method=self.interp_method)
        pks = detect_peaks(sig, curve.baseline, self.peak_params)
        curve.peak_local_baseline = self.peak_params.local_baseline
        analyze_peaks(curve.x, sig, pks, curve.baseline, curve.peak_local_baseline)
        curve.peaks = pks
        curve.peaks_group_shown = self.proc_steps["peaks"]["show_result"]
        self.log(f"{'Reprocessed' if reprocess else 'Detected'} {len(pks)} peak(s) on '{curve.name}' "
                 f"(baseline: {'local drift' if curve.peak_local_baseline else 'curve baseline'}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _apply_decay(self):
        ds, curve = self._need_curve()
        if curve is None:
            return
        hl = ds.half_life_s or lookup_half_life_s(ds.meta.radioisotope)
        if not hl:  # missing info → open the decay options popup, then retry
            self._edit_decay_options(ds)
            hl = ds.half_life_s or lookup_half_life_s(ds.meta.radioisotope)
            if not hl:
                self.log("Apply decay: no half-life set.")
                return
        factor = decay_factor(curve.x, hl, ds.decay_ref_offset_s)
        base_kind = "spikeless+decay" if "spikeless" in curve.kind else "decay"
        name = f"{curve.name} +decay"
        self._push_undo()
        child = new_curve_from(curve, curve.y * factor, name, base_kind, "#b000b0")
        child.shown = self.proc_steps["decay"]["show_result"]
        curve.children.append(child)
        self.log(f"Applied decay to '{curve.name}' → '{name}' (ref {ds.decay_ref_label}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _edit_decay_options(self, ds=None):
        if ds is None or isinstance(ds, bool):   # gear's clicked(bool) must not be taken as a dataset
            ds, _ = self._sel_curve()
        if ds is None:
            self.log("Decay options: select a dataset/curve first.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Apply decay — options")
        form = QFormLayout(dlg)
        iso = QComboBox()
        iso.addItem("—", "")
        for name, hours in ISOTOPES:
            iso.addItem(f"{name}   ({hours:g} h)", name)
        iso.setCurrentIndex(max(0, iso.findData(ds.meta.radioisotope)))
        hl_val = QDoubleSpinBox()
        hl_val.setRange(0, 1e9)
        hl_val.setDecimals(4)
        hl_unit = QComboBox()
        hl_unit.addItems(list(_UNIT_S))
        _set_halflife(hl_val, hl_unit, ds.half_life_s or lookup_half_life_s(ds.meta.radioisotope))
        iso.currentIndexChanged.connect(
            lambda: _set_halflife(hl_val, hl_unit, lookup_half_life_s(iso.currentData())))
        rb_start = QRadioButton("Run start (from header)")
        rb_off = QRadioButton("Offset from start")
        grp = QButtonGroup(dlg)
        grp.addButton(rb_start)
        grp.addButton(rb_off)
        off = QDoubleSpinBox()
        off.setRange(-1e7, 1e7)
        off.setSuffix(" min")
        if abs(ds.decay_ref_offset_s) < 1e-9:
            rb_start.setChecked(True)
        else:
            rb_off.setChecked(True)
            off.setValue(ds.decay_ref_offset_s / 60.0)
        form.addRow("Radioisotope", iso)
        form.addRow("Half-life (override)", _pair(hl_val, hl_unit))
        form.addRow("Decay-correct to", rb_start)
        form.addRow("", _pair(rb_off, off))
        if not _run_dialog(dlg, form):
            return
        ds.meta.radioisotope = iso.currentData()
        manual = hl_val.value() * _UNIT_S[hl_unit.currentText()]
        ds.half_life_s = manual if manual > 0 else lookup_half_life_s(ds.meta.radioisotope)
        if rb_off.isChecked():
            ds.decay_ref_offset_s = off.value() * 60.0
            ds.decay_ref_label = f"{off.value():g} min from start"
        else:
            ds.decay_ref_offset_s, ds.decay_ref_label = 0.0, "run start"
        self.log(f"Decay options: isotope={ds.meta.radioisotope or '—'}, "
                 f"half-life={'set' if ds.half_life_s else 'unknown'}, ref={ds.decay_ref_label}.")

    def _duplicate_curve(self):
        ds, curve = self._sel_curve()
        if curve is None or (self._selected() or [None])[0] != "curve":
            return
        self._push_undo()
        dup = copy.deepcopy(curve)
        for c in dup.walk():
            c.id = new_id()
        dup.name = curve.name + " copy"
        dup.legend_label = dup.name
        target = ds.parent_of(curve.id) or ds.root
        target.children.append(dup)
        self.log(f"Duplicated '{curve.name}' → '{dup.name}'.")
        self._rebuild_tree()
        self._select_id(("curve", ds.id, dup.id))
        self._refresh_plot()
        self._update_report()

    # ---------------- clipboard / exports ----------------
    def _render_qimage(self, fig, dpi):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        canvas = FigureCanvasAgg(fig)
        old = fig.get_dpi()
        fig.set_dpi(dpi)
        canvas.draw()
        w, h = canvas.get_width_height()
        img = QImage(bytes(canvas.buffer_rgba()), w, h, QImage.Format_RGBA8888).copy()
        fig.set_dpi(old)
        dpm = int(round(dpi / 0.0254))  # embed resolution so PowerPoint pastes at physical size
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
        return img

    def _copy_plot(self):
        if not self.datasets:
            return
        fig = self._export_fig()
        cb = QApplication.clipboard()
        if self.export_opts.clip_format == "svg":
            buf = io.BytesIO()
            fig.savefig(buf, format="svg", facecolor=fig.get_facecolor(), edgecolor="none")
            md = QMimeData()
            md.setData("image/svg+xml", QByteArray(buf.getvalue()))
            md.setText(buf.getvalue().decode("utf-8", "replace"))
            cb.setMimeData(md)
            self.log("Plot copied (SVG).")
        else:
            img = self._render_qimage(fig, self.export_opts.clip_dpi)
            cb.setImage(img)
            self.log(f"Plot copied {fig.get_figwidth() * 25.4:.0f}×{fig.get_figheight() * 25.4:.0f} mm "
                     f"({img.width()}×{img.height()} px @ {self.export_opts.clip_dpi} dpi).")

    def _export_plot(self):
        if not self.datasets:
            return
        path, flt = QFileDialog.getSaveFileName(self, "Export plot", "",
                                                "PNG image (*.png);;SVG vector (*.svg)")
        if not path:
            return
        fig = self._export_fig()
        dpi = self.export_opts.png_dpi
        is_png = path.lower().endswith(".png") or "png" in flt.lower()
        if is_png and not path.lower().endswith(".png"):
            path += ".png"
        elif not is_png and not path.lower().endswith(".svg"):
            path += ".svg"
        kw = {"facecolor": fig.get_facecolor(), "edgecolor": "none"}
        if is_png:
            kw["pil_kwargs"] = {"dpi": (dpi, dpi)}
        fig.savefig(path, dpi=dpi, **kw)
        self.log(f"Exported plot to {path}"
                 + f" (figure {fig.get_figwidth() * 25.4:.0f}×{fig.get_figheight() * 25.4:.0f} mm"
                 + (f" @ {dpi} dpi)" if is_png else ")"))

    def _export_data_gina(self):
        ds, curve = self._sel_curve()
        if curve is None:
            self.log("Export data: select a curve.")
            return
        default = f"{ds.meta.name}_{curve.name}.txt".replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(self, "Export curve (GINA)", default, "Text (*.txt)")
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        io_gina.save(ds, curve, path)
        self.log(f"Exported curve '{curve.name}' to {path}")

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export log", "spikeless_log.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(self._log_text(), encoding="utf-8")
            self.log(f"Log exported to {path}")

    def _export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "spikeless_report.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(self._report_text, encoding="utf-8")
            self.log(f"Report exported to {path}")

    # ---- per-export options (the ⚙ next to each Copy/Export) ----
    def _edit_plot_export_options(self):
        eo = self.export_opts
        dlg = QDialog(self)
        dlg.setWindowTitle("Plot copy / export options")
        form = QFormLayout(dlg)
        dpi = _int_spin(72, 2400, eo.png_dpi, 50)
        clip_dpi = _int_spin(72, 2400, eo.clip_dpi, 50)
        clip = QComboBox()
        clip.addItem("PNG image", "png")
        clip.addItem("SVG vector", "svg")
        clip.setCurrentIndex(max(0, clip.findData(eo.clip_format)))
        form.addRow("PNG file dpi", dpi)
        form.addRow("Clipboard dpi", clip_dpi)
        form.addRow("Copy to clipboard as", clip)
        if _run_dialog(dlg, form):
            eo.png_dpi, eo.clip_dpi, eo.clip_format = dpi.value(), clip_dpi.value(), clip.currentData()
            self._save_settings()
            self.log(f"Plot export options: PNG {eo.png_dpi} dpi, clipboard {eo.clip_dpi} dpi ({eo.clip_format}).")

    def _edit_log_export_options(self):
        eo = self.export_opts
        dlg = QDialog(self)
        dlg.setWindowTitle("Log copy / export options")
        form = QFormLayout(dlg)
        ts = QCheckBox("Include [HH:MM:SS] timestamps")
        ts.setChecked(eo.log_timestamps)
        form.addRow(ts)
        if _run_dialog(dlg, form):
            eo.log_timestamps = ts.isChecked()
            self._save_settings()
            self.log("Log export options updated.")

    def _edit_report_export_options(self):
        eo = self.export_opts
        dlg = QDialog(self)
        dlg.setWindowTitle("Report copy / export options")
        outer = QVBoxLayout(dlg)
        outer.addWidget(QLabel("Peak-table columns (shown in the report = copied):"))
        col_chks = {}
        for key, header, _f in PEAK_COLUMNS:
            c = QCheckBox(header if key != "num" else "# (row number)")
            c.setChecked(eo.report_cols.get(key, False))
            col_chks[key] = c
            outer.addWidget(c)
        html = QCheckBox("Copy tables as rich HTML (else plain tab-separated text)")
        html.setChecked(eo.report_table_html)
        outer.addWidget(html)
        allbtn = QPushButton("Export all peak tables (Excel / CSV)…")
        allbtn.clicked.connect(self._export_all_peaks)
        outer.addWidget(allbtn)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        outer.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        for key, c in col_chks.items():
            eo.report_cols[key] = c.isChecked()
        eo.report_table_html = html.isChecked()
        self._save_settings()
        self._update_report()
        self.log("Report options updated.")

    def _export_selected(self):
        data = self._selected()
        if not data:
            self.log("Export: select a curve, dataset or peaks group first.")
            return
        if data[0] in ("curve", "dataset"):
            self._export_data_gina()
        elif data[0] in ("peaks", "peak"):
            self._export_peaks(scope="one")

    def _export_all_peaks(self):
        self._export_peaks(scope="all")

    def _export_peaks(self, scope):
        """Export peak tables as Excel (a sheet per curve) or CSV. scope 'one' = the selected
        curve, 'all' = every curve with peaks. Columns follow the report options."""
        if scope == "one":
            ds, cv = self._sel_curve()
            items = [(ds, cv)] if cv is not None and cv.peaks else []
            default = (f"{ds.meta.name}_{cv.name}_peaks" if items else "peaks").replace(" ", "_")
        else:
            items = [(ds, cv) for ds in self.datasets for cv in ds.curves() if cv.peaks]
            default = "peak_tables"
        if not items:
            self.log("Export: no peaks to export.")
            return
        head, _ = self._peak_rows(items[0][1])
        if not head:
            self.log("Export: no peak columns are enabled (Report ⚙).")
            return
        path, flt = QFileDialog.getSaveFileName(self, "Export peak table(s)", default,
                                                "Excel workbook (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        xlsx = path.lower().endswith(".xlsx") or ("xlsx" in flt.lower() and not path.lower().endswith(".csv"))
        if xlsx and not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        elif not xlsx and not path.lower().endswith(".csv"):
            path += ".csv"
        n = self._write_peaks_xlsx(path, items) if xlsx else self._write_peaks_csv(path, items, scope)
        self.log(f"Exported {n} peak(s) from {len(items)} curve(s) to {path}")

    def _write_peaks_csv(self, path, items, scope):
        head, _ = self._peak_rows(items[0][1])
        prefix = ("Dataset", "Curve") if scope == "all" else ()
        lines = [",".join(prefix + head)]
        n = 0
        for ds, cv in items:
            _h, body = self._peak_rows(cv)
            for r in body:
                lines.append(",".join(((ds.meta.name, cv.name) if scope == "all" else ()) + r))
                n += 1
        Path(path).write_text("\n".join(lines), encoding="utf-8")
        return n

    def _write_peaks_xlsx(self, path, items):
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)   # drop the default empty sheet
        used, n = set(), 0
        for ds, cv in items:
            head, body = self._peak_rows(cv)
            ws = wb.create_sheet(_sheet_name(cv.name, used))
            ws.append(list(head))
            for r in body:
                ws.append([_num(c) for c in r])
                n += 1
        wb.save(path)
        return n

    # ---------------- dialogs ----------------
    def _edit_info(self):
        """Info for whichever element is selected in the Data tree."""
        data = self._selected()
        if not data:
            return
        kind = data[0]
        if kind == "dataset":
            self._edit_dataset_info()
        elif kind == "curve":
            self._curve_info()
        elif kind == "baseline":
            self._baseline_info()
        elif kind == "spikes":
            self._spikes_info()
        elif kind == "peaks":
            self._peaks_info()
        elif kind == "spike":
            _ds, curve = self._sel_curve()
            if curve is not None:
                self._edit_spike_info(curve, data[3])
        elif kind == "peak":
            _ds, curve = self._sel_curve()
            if curve is not None:
                self._edit_peak_info(curve, data[3])

    def _info_dialog(self, title, rows):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        form = QFormLayout(dlg)
        for lbl, val in rows:
            ed = QLineEdit(str(val))
            ed.setReadOnly(True)
            ed.setStyleSheet("color:#bbb;")
            form.addRow(lbl, ed)
        _run_dialog(dlg, form)

    def _curve_info(self):
        import numpy as np
        _ds, curve = self._sel_curve()
        if curve is None:
            return
        y = curve.y
        rows = [("Name", curve.name), ("Kind", curve.kind), ("Points", len(y)),
                ("x range (min)", f"{float(curve.x[0]):.3f} … {float(curve.x[-1]):.3f}"),
                ("y range", f"{float(np.nanmin(y)):.1f} … {float(np.nanmax(y)):.1f}"),
                ("Spikes", len(curve.spike_indices()) if curve.has_spikes else "—"),
                ("Baseline", "yes" if curve.baseline is not None else "—"),
                ("Peaks", len(curve.peaks) if curve.peaks else "—"),
                ("Derived curves", len(curve.children))]
        self._info_dialog(f"Curve info — {curve.name}", rows)

    def _baseline_info(self):
        import numpy as np
        _ds, curve = self._sel_curve()
        if curve is None or curve.baseline is None:
            return
        b = np.asarray(curve.baseline, float)
        flat = float(np.nanmax(b) - np.nanmin(b)) < 1e-9
        rows = [("Curve", curve.name), ("Type", "constant" if flat else "per-point / drift"),
                ("Min level", f"{float(np.nanmin(b)):.2f}"), ("Max level", f"{float(np.nanmax(b)):.2f}"),
                ("Mean level", f"{float(np.nanmean(b)):.2f}")]
        self._info_dialog(f"Baseline info — {curve.name}", rows)

    def _spikes_info(self):
        _ds, curve = self._sel_curve()
        if curve is None or not curve.has_spikes:
            return
        idxs = curve.spike_indices()
        times = ", ".join(f"{float(curve.x[i]):.2f}" for i in idxs[:12]) + (" …" if len(idxs) > 12 else "")
        rows = [("Curve", curve.name), ("Count", len(idxs)), ("Times (min)", times)]
        self._info_dialog(f"Spikes info — {curve.name}", rows)

    def _peaks_info(self):
        _ds, curve = self._sel_curve()
        if curve is None or not curve.peaks:
            return
        total = sum(pk.auc for pk in curve.peaks)
        rows = [("Curve", curve.name), ("Count", len(curve.peaks)), ("Total AUC", f"{total:.1f}"),
                ("Baseline", "local drift" if curve.peak_local_baseline else "curve baseline")]
        self._info_dialog(f"Peaks info — {curve.name}", rows)

    def _edit_dataset_info(self):
        ds, _ = self._sel_curve()
        if ds is None:
            return
        m = ds.meta
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Info — {m.name}")
        outer = QVBoxLayout(dlg)
        form = QFormLayout()
        name = QLineEdit(m.name)
        orig = QLineEdit(m.original_filename)
        orig.setReadOnly(True)
        orig.setStyleSheet("color:#888;")
        run = QLineEdit(ds.run_datetime)
        run.setReadOnly(True)
        run.setStyleSheet("color:#888;")
        molecule = QLineEdit(m.molecule)
        radio = QComboBox()
        radio.addItem("—", "")
        for iname, hours in ISOTOPES:
            radio.addItem(f"{iname}   ({hours:g} h)", iname)
        radio.setCurrentIndex(max(0, radio.findData(m.radioisotope)))
        for lbl, wdg in [("Dataset name", name), ("Original file", orig), ("Run date/time", run),
                         ("Molecule", molecule), ("Radioisotope", radio)]:
            form.addRow(lbl, wdg)
        outer.addLayout(form)

        outer.addWidget(QLabel("Conditions:"))
        cond_box = QVBoxLayout()
        outer.addLayout(cond_box)
        rows = []

        def add_row(cond: Condition | None = None):
            cond = cond or Condition()
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            pair = QCheckBox("label+value")
            pair.setChecked(bool(cond.label))
            lab = QLineEdit(cond.label)
            lab.setPlaceholderText("label")
            val = QLineEdit(cond.value)
            val.setPlaceholderText("note / value")
            lab.setVisible(pair.isChecked())
            pair.toggled.connect(lab.setVisible)
            rm = QPushButton("✖")
            rm.setFixedWidth(24)
            rm.setStyleSheet("color:#ff5555;")
            entry = (w, pair, lab, val)
            rm.clicked.connect(lambda: (_drop(entry)))
            for x in (pair, lab, val, rm):
                h.addWidget(x)
            cond_box.addWidget(w)
            rows.append(entry)

        def _drop(entry):
            entry[0].setParent(None)
            rows.remove(entry)

        for c in ds.conditions:
            add_row(c)
        add_btn = QPushButton("+ add condition")
        add_btn.clicked.connect(lambda: add_row())
        outer.addWidget(add_btn)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        outer.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        m.name = name.text().strip() or m.name
        m.molecule, m.radioisotope = molecule.text(), radio.currentData()
        if m.radioisotope:
            ds.half_life_s = lookup_half_life_s(m.radioisotope)
        ds.conditions = []
        for _w, pair, lab, val in rows:
            if pair.isChecked():
                ds.conditions.append(Condition(label=lab.text(), value=val.text()))
            elif val.text().strip():
                ds.conditions.append(Condition(label="", value=val.text()))
        self.log(f"Updated info for '{m.name}'.")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _edit_adjust(self):
        ds, curve = self._sel_curve()
        if curve is None:
            return
        a = curve.adjust
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Adjust (normalization) — {curve.name}")
        outer = QVBoxLayout(dlg)
        gn = QGroupBox("Normalization")
        fn = QFormLayout(gn)
        r_cps = QRadioButton("Counts (cps)")
        r_max = QRadioButton("% of max")
        r_tot = QRadioButton("% of total")
        grp = QButtonGroup(dlg)
        for rb in (r_cps, r_max, r_tot):
            grp.addButton(rb)
        {"cps": r_cps, "pct_max": r_max, "pct_total": r_tot}.get(a.norm_mode, r_cps).setChecked(True)
        for rb in (r_cps, r_max, r_tot):
            fn.addRow(rb)
        fn.addRow(QLabel("% modes subtract the curve's detected baseline (Processing) if present."))
        outer.addWidget(gn)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        outer.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        curve.adjust = AdjustParams(
            norm_mode="pct_total" if r_tot.isChecked() else "pct_max" if r_max.isChecked() else "cps")
        self.log(f"Adjust '{curve.name}': norm={curve.adjust.norm_mode}.")
        self._refresh_plot()
        self._update_report()

    def _edit_node_display(self):
        data = self._selected()
        ds, curve = self._sel_curve()
        if curve is None or not data:
            return
        kind = data[0]
        if kind == "curve":
            self._edit_curve_style(curve)
        elif kind in ("spike", "spikes"):   # single items share the group's style
            self._edit_spike_viz(curve)
        elif kind == "baseline":
            self._edit_baseline_viz(curve)
        elif kind == "peak":
            self._edit_peak_color(curve, data[3])   # a specific peak → just its colour
        elif kind == "peaks":
            self._edit_peak_viz(curve)               # the group → group style

    def _edit_curve_style(self, curve):
        st = curve.style
        has_base = curve.baseline is not None
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Display — {curve.name}")
        form = QFormLayout(dlg)
        color = _ColorButton(st.color)
        alpha = _spin(0, 1, st.alpha, 0.05)
        lw = _spin(0.1, 5, st.line_width_pt, 0.1)
        ls = QComboBox()
        ls.addItems(_LINESTYLES)
        ls.setCurrentText(st.linestyle)
        fill = QCheckBox("(baseline ↔ curve)" if has_base else "needs a baseline")
        fill.setEnabled(has_base)
        fill.setChecked(st.fill and has_base)
        fillc = _ColorButton(st.fill_color)
        filla = _spin(0, 1, st.fill_alpha, 0.05)
        leg = QCheckBox("Show in legend")
        leg.setChecked(curve.show_legend)
        leglbl = QLineEdit(curve.legend_label or curve.name)
        for lbl, wdg in [("Colour", color), ("Alpha", alpha), ("Line width (pt)", lw),
                         ("Line style", ls), ("Fill", fill), ("Fill colour", fillc),
                         ("Fill alpha", filla), ("In legend", leg), ("Legend label", leglbl)]:
            form.addRow(lbl, wdg)
        if _run_dialog(dlg, form):
            st.color = color.color
            st.alpha, st.line_width_pt = alpha.value(), lw.value()
            st.linestyle = ls.currentText()
            st.fill = fill.isChecked() and has_base
            st.fill_color, st.fill_alpha = fillc.color, filla.value()
            curve.show_legend = leg.isChecked()
            curve.legend_label = leglbl.text()
            self._refresh_plot()

    def _edit_spike_viz(self, curve):
        v = curve.spike_viz
        dlg = QDialog(self)
        dlg.setWindowTitle("Spikes display")
        form = QFormLayout(dlg)
        r_pts = QRadioButton("Single points")
        r_seg = QRadioButton("Colour n-1 → n+1")
        grp = QButtonGroup(dlg)
        grp.addButton(r_pts)
        grp.addButton(r_seg)
        (r_seg if v.mode == "segment" else r_pts).setChecked(True)
        color = _ColorButton(v.color)
        leg = QCheckBox("Show in legend")
        leg.setChecked(v.in_legend)
        form.addRow(r_pts)
        form.addRow(r_seg)
        form.addRow("Colour", color)
        form.addRow(leg)
        if _run_dialog(dlg, form):
            curve.spike_viz = SpikeViz(mode="segment" if r_seg.isChecked() else "points",
                                       color=color.color, in_legend=leg.isChecked())
            self._refresh_plot()

    def _edit_baseline_viz(self, curve):
        v = curve.baseline_viz
        dlg = QDialog(self)
        dlg.setWindowTitle("Baseline display")
        form = QFormLayout(dlg)
        auto = QCheckBox("Auto (desaturated curve colour)")
        auto.setChecked(v.color is None)
        color = _ColorButton(v.color or "#888888")
        color.setEnabled(v.color is not None)
        auto.toggled.connect(lambda on: color.setDisabled(on))
        alpha = _spin(0, 1, v.alpha, 0.05)
        ls = QComboBox()
        ls.addItems(_LINESTYLES)
        ls.setCurrentText(v.linestyle)
        form.addRow(auto)
        form.addRow("Colour", color)
        form.addRow("Alpha", alpha)
        form.addRow("Line style", ls)
        if _run_dialog(dlg, form):
            curve.baseline_viz = BaselineViz(color=None if auto.isChecked() else color.color,
                                             alpha=alpha.value(), linestyle=ls.currentText())
            self._refresh_plot()

    def _edit_peak_viz(self, curve):
        v = curve.peak_viz
        dlg = QDialog(self)
        dlg.setWindowTitle("Peaks display")
        form = QFormLayout(dlg)
        r_fill = QRadioButton("Fill AUC")
        r_mark = QRadioButton("Markers")
        grp = QButtonGroup(dlg)
        grp.addButton(r_fill)
        grp.addButton(r_mark)
        (r_mark if v.mode == "markers" else r_fill).setChecked(True)
        color = _ColorButton(v.color)
        alpha = _spin(0, 1, v.alpha, 0.05)
        marker = QComboBox()
        marker.addItems(_MARKERS)
        marker.setCurrentText(v.marker)
        annot = QComboBox()
        for key, lbl in _ANNOT:
            annot.addItem(lbl, key)
        annot.setCurrentIndex(max(0, annot.findData(curve.annotate)))
        lsize = _spin(4, 24, v.label_size, 0.5)
        lpos = QComboBox()
        for key in ("auto", "above", "right", "left"):
            lpos.addItem(key.capitalize(), key)
        lpos.setCurrentIndex(max(0, lpos.findData(v.label_pos)))
        lauto = QCheckBox("auto (readable on background)")
        lauto.setChecked(v.label_color is None)
        lcolor = _ColorButton(v.label_color or v.color)
        lcolor.setEnabled(v.label_color is not None)
        lauto.toggled.connect(lambda on: lcolor.setDisabled(on))
        leg = QCheckBox("Show in legend")
        leg.setChecked(v.in_legend)
        form.addRow(r_fill)
        form.addRow(r_mark)
        form.addRow("Colour", color)
        form.addRow("Fill alpha", alpha)
        form.addRow("Marker", marker)
        form.addRow("On-graph label", annot)
        form.addRow("Label size (pt)", lsize)
        form.addRow("Label position", lpos)
        form.addRow("Label colour", lcolor)
        form.addRow("", lauto)
        form.addRow(leg)
        if _run_dialog(dlg, form):
            curve.peak_viz = PeakViz(mode="markers" if r_mark.isChecked() else "fill",
                                     color=color.color, alpha=alpha.value(),
                                     marker=marker.currentText(), in_legend=leg.isChecked(),
                                     label_size=lsize.value(),
                                     label_color=None if lauto.isChecked() else lcolor.color,
                                     label_pos=lpos.currentData())
            curve.annotate = annot.currentData()
            self._refresh_plot()

    def _edit_spike_info(self, curve, i):
        idxs = curve.spike_indices()
        if i >= len(idxs):
            return
        si = int(idxs[i])
        dlg = QDialog(self)
        dlg.setWindowTitle("Spike info")
        form = QFormLayout(dlg)
        for lbl, val in [("Time (min)", f"{curve.x[si]:.3f}"), ("Sample index", str(si)),
                         ("y (raw)", f"{curve.y[si]:.1f}")]:
            ed = QLineEdit(val)
            ed.setReadOnly(True)
            form.addRow(lbl, ed)
        _run_dialog(dlg, form)

    def _peak_color_row(self, form, pk, curve):
        """Add a 'Colour' + 'use group colour' pair to `form`; returns (auto_checkbox, button).
        Ticked auto => pk.color None (inherit the group peak_viz colour)."""
        auto = QCheckBox("use group colour")
        auto.setChecked(pk.color is None)
        btn = _ColorButton(pk.color or curve.peak_viz.color)
        btn.setEnabled(pk.color is not None)
        auto.toggled.connect(lambda on: btn.setDisabled(on))
        form.addRow("Colour", btn)
        form.addRow("", auto)
        return auto, btn

    def _edit_peak_color(self, curve, i):
        if not curve.peaks or i >= len(curve.peaks):
            return
        pk = curve.peaks[i]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Peak {i + 1} display")
        form = QFormLayout(dlg)
        auto, btn = self._peak_color_row(form, pk, curve)
        annot = QComboBox()
        annot.addItem("(group default)", None)
        for key, lbl in _ANNOT:
            annot.addItem(lbl, key)
        annot.setCurrentIndex(max(0, annot.findData(pk.annotate)))
        form.addRow("On-graph label", annot)
        if _run_dialog(dlg, form):
            pk.color = None if auto.isChecked() else btn.color
            pk.annotate = annot.currentData()   # None => inherit the curve's group label
            self._refresh_plot()

    def _edit_peak_info(self, curve, i):
        if not curve.peaks or i >= len(curve.peaks):
            return
        pk = curve.peaks[i]
        dlg = QDialog(self)
        dlg.setWindowTitle("Peak info")
        form = QFormLayout(dlg)
        name = QLineEdit(pk.name)
        name.setPlaceholderText(f"peak {i + 1}")
        form.addRow("Name", name)
        auto, colorbtn = self._peak_color_row(form, pk, curve)
        for lbl, val in [("Rt (min)", f"{pk.rt:.3f}"), ("x start (min)", f"{pk.x_start:.3f}"),
                         ("x end (min)", f"{pk.x_end:.3f}"), ("width (min)", f"{pk.length:.3f}"),
                         ("y max (above base)", f"{pk.y_max:.1f}"), ("AUC", f"{pk.auc:.2f}"),
                         ("% of group", f"{pk.pct:.2f}"), ("skewness", f"{pk.skew:.3f}")]:
            ed = QLineEdit(val)
            ed.setReadOnly(True)
            ed.setStyleSheet("color:#bbb;")
            form.addRow(lbl, ed)
        if _run_dialog(dlg, form):
            pk.name = name.text()
            pk.color = None if auto.isChecked() else colorbtn.color
            self._rebuild_tree()
            self._refresh_plot()

    # ---------------- detection params ----------------
    def _edit_spike_params(self):
        p = self.spike_params
        dlg = QDialog(self)
        dlg.setWindowTitle("Spike detection")
        form = QFormLayout(dlg)
        window = _int_spin(3, 101, p.window, 2)
        n_sigma = _spin(1, 50, p.n_sigma, 0.5)
        max_width = _int_spin(1, 10, p.max_width, 1)
        interp = QComboBox()
        for key, lbl in _INTERP_METHODS:
            interp.addItem(lbl, key)
        interp.setCurrentIndex(max(0, interp.findData(self.interp_method)))
        form.addRow("Window (odd)", window)
        form.addRow("Threshold (n·σ)", n_sigma)
        form.addRow("Max width", max_width)
        form.addRow("Interpolation", interp)
        if _run_dialog(dlg, form):
            self.spike_params = SpikeParams(window=window.value() | 1, n_sigma=n_sigma.value(),
                                            max_width=max_width.value())
            self.interp_method = interp.currentData()
            self.log(f"Spike params: window={self.spike_params.window}, interp={self.interp_method}.")

    def _edit_baseline_params(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Baseline algorithm")
        form = QFormLayout(dlg)
        method = QComboBox()
        for key in ("min", "first_n", "snip", "none"):
            method.addItem(BASELINE_LABELS[key], key)
        method.setCurrentIndex(max(0, method.findData(self.baseline_method)))
        n_spin = _int_spin(1, 100000, self.baseline_n, 1)
        form.addRow("Method", method)
        form.addRow("N", n_spin)
        n_label = form.labelForField(n_spin)  # relabel + enable N per method (shared knob)

        def _sync_n():
            m = method.currentData()
            n_spin.setEnabled(m in ("first_n", "snip"))
            n_label.setText("Peak half-width (pts)" if m == "snip"
                            else "First N points" if m == "first_n" else "N (unused)")
        method.currentIndexChanged.connect(_sync_n)
        _sync_n()
        if _run_dialog(dlg, form):
            self.baseline_method = method.currentData()
            self.baseline_n = n_spin.value()
            self.log(f"Baseline algorithm: {self.baseline_method}.")

    def _edit_peak_params(self):
        p = self.peak_params
        dlg = QDialog(self)
        dlg.setWindowTitle("Peak detection")
        form = QFormLayout(dlg)
        prom = _spin(0, 1e9, p.min_prominence, 1)
        height = QLineEdit("" if p.min_height is None else f"{p.min_height:g}")
        dist = _int_spin(1, 100000, p.min_distance, 1)
        local = QCheckBox("Local (drift) baseline per peak")
        local.setChecked(p.local_baseline)
        form.addRow("Min prominence (0=auto)", prom)
        form.addRow("Min height (blank=none)", height)
        form.addRow("Min distance (points)", dist)
        form.addRow(local)
        if _run_dialog(dlg, form):
            try:
                h = float(height.text().replace(",", ".")) if height.text().strip() else None
            except ValueError:
                h = None
            self.peak_params = PeakParams(min_prominence=prom.value(), min_height=h,
                                          min_distance=dist.value(), local_baseline=local.isChecked())
            self.log(f"Peak params: prominence={self.peak_params.min_prominence:g}, "
                     f"local baseline={self.peak_params.local_baseline}.")

    def _edit_app_options(self):
        ao = self.app_opts
        dlg = QDialog(self)
        dlg.setWindowTitle("Options")
        root = QVBoxLayout(dlg)
        host = QWidget()
        outer = QVBoxLayout(host)

        # --- Background (collapsed) ---
        bg = ao.background
        bgw = QWidget()
        f = QFormLayout(bgw)
        chk = QCheckBox("Checkered")
        chk.setChecked(bg.checkered)
        ca = _ColorButton(bg.color_a)
        cb = _ColorButton(bg.color_b)
        size = _spin(0.2, 20, bg.size_mm, 0.1)
        f.addRow(chk)
        f.addRow("Colour A / solid", ca)
        f.addRow("Colour B (checker)", cb)
        f.addRow("Checker cell (mm)", size)
        outer.addWidget(_Collapsible("Background", bgw, expanded=False))

        # --- Export-area border (collapsed) ---
        bd = ao.export_border
        bdw = QWidget()
        fb = QFormLayout(bdw)
        bd_on = QCheckBox("Show dotted border")
        bd_on.setChecked(bd.on)
        bd_color = _ColorButton(bd.color)
        bd_style = QComboBox()
        bd_style.addItems(list(BORDER_STYLES))
        bd_style.setCurrentText(bd.style)
        bd_width = _spin(0.1, 3, bd.width, 0.1)
        fb.addRow(bd_on)
        fb.addRow("Colour", bd_color)
        fb.addRow("Style", bd_style)
        fb.addRow("Width (pt)", bd_width)
        outer.addWidget(_Collapsible("Export-area border", bdw, expanded=False))

        # --- Plot view (collapsed) ---
        pvw = QWidget()
        f2 = QFormLayout(pvw)
        smax = _int_spin(2, 20, ao.scale_max, 1)
        f2.addRow("Resolution slider max (×)", smax)
        outer.addWidget(_Collapsible("Plot view", pvw, expanded=False))

        # --- Data visualization (collapsed) ---
        dvw = QWidget()
        fdv = QVBoxLayout(dvw)
        crop = QCheckBox("Crop fill areas where a curve passes (clean alpha overlaps)")
        crop.setChecked(self.plot_opts.crop_fills)
        crop.setToolTip("Cuts AUC/baseline fills around each curve line so overlapping "
                        "semi-transparent areas read cleanly. Best on an opaque plot background.")
        fdv.addWidget(crop)
        outer.addWidget(_Collapsible("Data visualization", dvw, expanded=False))

        # --- Processing features shown (collapsed) ---
        procw = QWidget()
        fp = QVBoxLayout(procw)
        proc_chks = {}
        for key, label, _run, _gear in PROC_FEATURES:
            c = QCheckBox(label)
            c.setChecked(ao.proc_visible.get(key, True))
            proc_chks[key] = c
            fp.addWidget(c)
        outer.addWidget(_Collapsible("Processing features shown", procw, expanded=False))

        # --- Menu windows (collapsed) ---
        mww = QWidget()
        fm = QVBoxLayout(mww)
        fm.addWidget(QLabel("Open by default:"))
        dock_labels = {"data": "Data", "processing": "Processing", "log": "Log",
                       "report": "Report", "plot_options": "Plot options"}
        dock_chks = {}
        for key, _attr in DOCK_KEYS:
            c = QCheckBox(dock_labels[key])
            c.setChecked(ao.docks_open.get(key, key != "plot_options"))
            c.setStyleSheet("margin-left:18px;")   # indent the list so it reads under "Open by default:"
            if key == "plot_options":
                c.setToolTip("Plot options opens when the first dataset is loaded.")
            dock_chks[key] = c
            fm.addWidget(c)
        lock = QCheckBox("Lock menu windows (no drag/float)")
        lock.setChecked(ao.lock_docks)
        fm.addWidget(lock)
        outer.addWidget(_Collapsible("Menu windows", mww, expanded=False))

        outer.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        scroll.setMinimumSize(380, 340)
        root.addWidget(scroll)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        root.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        ao.scale_max = smax.value()
        self.scale_slider.setMaximum(ao.scale_max * 10)
        ao.background = Background(checkered=chk.isChecked(), color_a=ca.color,
                                  color_b=cb.color, size_mm=size.value())
        ao.export_border = ExportBorder(on=bd_on.isChecked(), color=bd_color.color,
                                        style=bd_style.currentText(), width=bd_width.value())
        ao.lock_docks = lock.isChecked()
        self.plot_opts.crop_fills = crop.isChecked()
        for key, c in proc_chks.items():
            ao.proc_visible[key] = c.isChecked()
        for key, c in dock_chks.items():
            ao.docks_open[key] = c.isChecked()
        self.plot_view.set_background(ao.background)
        self._apply_lock()
        self._populate_processing()
        self._save_settings()
        self._refresh_plot()
        self.log("Options updated.")


# ---------------- small widget helpers ----------------
class _DataTree(QTreeWidget):
    """Tree with drag-to-reorder that reorders the model (draw order = z-order) via a signal.
    A drop line shows where the item will land; the model is rebuilt so the move sticks."""

    reordered = Signal(object, object, bool)  # (source data, target data|None, drop-below)

    def dropEvent(self, e):
        src = self.currentItem()
        tgt = self.itemAt(e.position().toPoint())
        dip = self.dropIndicatorPosition()
        e.ignore()  # we own z-order; reorder the model ourselves and rebuild, don't let Qt move items
        if src is None or src is tgt:
            return
        below = dip in (QAbstractItemView.BelowItem, QAbstractItemView.OnItem)
        # dropped past the last row → move to the end of the top-level (dataset) list
        tgt_data = tgt.data(0, Qt.UserRole) if tgt is not None else None
        self.reordered.emit(src.data(0, Qt.UserRole), tgt_data, below)


class _Collapsible(QWidget):
    toggled = Signal(bool)

    def __init__(self, title, content, expanded=True):
        super().__init__()
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

    def _on_toggled(self, on):
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.toggled.emit(on)


class _ColorButton(QPushButton):
    def __init__(self, color, on_change=None):
        super().__init__(color)
        self.color = color
        self._on_change = on_change
        self._paint()
        self.clicked.connect(self._pick)

    def _paint(self):
        self.setStyleSheet(f"background:{self.color}; padding:4px;")
        self.setText(self.color)

    def _pick(self):
        dlg = QColorDialog(QColor(self.color), self)
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)
        dlg.setPalette(QApplication.palette())  # dark grey bg + light text, like the app
        if dlg.exec() != QDialog.Accepted:
            return
        c = dlg.currentColor()
        if c.isValid():
            self.color = c.name()
            self._paint()
            if self._on_change:
                self._on_change()


def _gear(slot):
    b = QPushButton("⚙")
    b.setFixedWidth(30)
    b.clicked.connect(slot)
    return b


def _tool(text, tip, slot):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.clicked.connect(slot)
    return b


def _clear_layout(lay):
    """Remove and delete every item (widgets and spacers) from a layout, in place."""
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


def _num(v):
    """Coerce a formatted cell to a number for Excel (so columns stay summable); else keep text."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return v


def _sheet_name(name, used):
    """A valid, unique (<=31 char) Excel sheet name."""
    s = "".join(c for c in str(name) if c not in '[]:*?/\\')[:31] or "Sheet"
    base, i = s, 1
    while s in used:
        suffix = f"_{i}"
        s = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(s)
    return s


class _DockTitleBar(QWidget):
    """Custom dock title bar: [title] … Copy  Export  ⚙  ✕ — so the log/report get their
    copy/export tools on the title line instead of a button row at the bottom."""

    def __init__(self, dock, tools):
        super().__init__()
        self.setStyleSheet(
            "QToolButton{color:#e0e0e0;border:none;padding:2px 6px;} "
            "QToolButton:hover{background:#4a4d4f;border-radius:2px;} "
            "QToolButton:disabled{color:#777;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 1, 2, 1)
        h.setSpacing(0)
        title = QLabel(dock.windowTitle())
        title.setStyleSheet("font-weight:600; padding-right:6px;")
        h.addWidget(title)
        h.addStretch(1)
        self.buttons = {}
        for key, text, tip, slot in tools:
            b = _tool(text, tip, slot)
            self.buttons[key] = b
            h.addWidget(b)
        close = _tool("✕", "Close", dock.close)
        h.addWidget(close)


def _cform(w):
    """A compact form layout (less line spacing) for the Plot-options panel."""
    f = QFormLayout(w)
    f.setVerticalSpacing(4)
    f.setContentsMargins(6, 4, 6, 4)
    return f


def _pen_icon():
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor("#9aa"))
    p.drawText(pm.rect(), Qt.AlignCenter, "✎")
    p.end()
    return QIcon(pm)


def _app_icon():
    """The window/taskbar icon, if the bundled .ico is present (generated by misc/icon.py)."""
    p = Path(__file__).with_name("assets") / "spikeless.ico"
    return QIcon(str(p)) if p.exists() else None


def _spin(lo, hi, val, step):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(2 if step < 1 else 0)
    s.setValue(val)
    return s


def _int_spin(lo, hi, val, step):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    return s


def _pair(left, right):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(left)
    h.addWidget(right, 1)
    return w


def _triple(a, b, c):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(a, 1)
    h.addWidget(b)
    h.addWidget(c)
    return w


def _set_halflife(spin, unit, hl_s):
    if not hl_s:
        return
    for u, factor in (("d", 86400.0), ("h", 3600.0), ("min", 60.0), ("s", 1.0)):
        if hl_s >= factor:
            spin.setValue(hl_s / factor)
            unit.setCurrentText(u)
            return
    spin.setValue(hl_s)
    unit.setCurrentText("s")


def _run_dialog(dlg, form):
    box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    form.addRow(box)
    return dlg.exec() == QDialog.Accepted
