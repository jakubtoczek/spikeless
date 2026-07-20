"""SpikeRemover main window (PySide6 + matplotlib)."""

from __future__ import annotations

import copy
import datetime as _dt
import io
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QToolBar,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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


@dataclass
class AppOptions:
    background: Background = field(default_factory=Background)
    lock_docks: bool = True
    export_border: ExportBorder = field(default_factory=ExportBorder)
    scale_max: int = 5   # top of the resolution slider (× plot size)


@dataclass
class ExportOptions:
    png_dpi: int = 600
    clip_dpi: int = 150
    clip_format: str = "png"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SpikeRemover — radio-HPLC spike removal")
        self.resize(1200, 800)
        self.setAcceptDrops(True)

        self.datasets: list[Dataset] = []
        self.plot_opts = PlotOptions()
        self.spike_params = SpikeParams()
        self.interp_method = "linear"
        self.baseline_method = "min"
        self.baseline_n = 20
        self.peak_params = PeakParams()
        self.app_opts = AppOptions()
        self.export_opts = ExportOptions()
        self.view_scale = 1.0        # resolution slider (× plot size, on-screen)
        self.scale_export = False    # also apply the slider to exports/clipboard
        self._fig = None
        self.d: dict = {}
        self._loading_disp = False
        self._pen = _pen_icon()

        self._build_ui()
        self._apply_lock()
        self._update_enabled()
        self._position_overlay()
        self.log("SpikeRemover ready. Drag a GINA .txt file here or use Browse.")
        self._update_report()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        self.plot_view = ZoomableFigureView()
        self.plot_view.set_background(self.app_opts.background)
        self.plot_view.filesDropped.connect(self._load_paths)
        self.plot_view.resized.connect(self._position_overlay)
        self.setCentralWidget(self.plot_view)

        self.copy_btn = QPushButton("⧉ Copy", self.plot_view)
        self.copy_btn.setToolTip("Copy plot to clipboard")
        self.copy_btn.setStyleSheet(
            "QPushButton{background:#3c3f41;color:#e0e0e0;border:1px solid #555;padding:3px 8px;}")
        self.copy_btn.clicked.connect(self._copy_plot)
        self.copy_btn.adjustSize()

        # resolution slider (× plot size on screen; optionally applied to export)
        self.scale_bar = QWidget(self.plot_view)
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
        for label, slot in [("App options…", self._edit_app_options),
                            ("Export options…", self._edit_export_options)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            tb.addWidget(b)
        self.btn_export_plot = QPushButton("Export plot…")
        self.btn_export_plot.clicked.connect(self._export_plot)
        tb.addWidget(self.btn_export_plot)

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
        for b in (self.btn_info, self.btn_adjust, self.btn_disp, self.btn_dup):
            row.addWidget(b)
        lay.addLayout(row)
        self.data_dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, self.data_dock)

    def _build_processing_dock(self):
        self.processing_dock = QDockWidget("Processing", self)
        w = QWidget()
        lay = QVBoxLayout(w)
        specs = [("Detect spikes", self._detect_spikes, self._edit_spike_params),
                 ("Detect baseline", self._detect_baseline, self._edit_baseline_params),
                 ("Detect peaks", self._detect_peaks, self._edit_peak_params),
                 ("Apply decay", self._apply_decay, self._edit_decay_options)]
        for label, run, gear in specs:
            r = QHBoxLayout()
            b = QPushButton(label)
            b.clicked.connect(run)
            r.addWidget(b)
            if gear:
                r.addWidget(_gear(gear))
            lay.addLayout(r)
        lay.addStretch(1)
        self.processing_dock.setWidget(w)
        self.addDockWidget(Qt.RightDockWidgetArea, self.processing_dock)

    def _build_log_dock(self):
        self.log_dock = QDockWidget("Log", self)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_dock.setWidget(self._text_body(self.log_view, "Export log…", self._export_log))
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

    def _build_report_dock(self):
        self.report_dock = QDockWidget("Report", self)
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_dock.setWidget(self._text_body(self.report_view, "Export report…",
                                                   self._export_report, self._copy_report_table))
        self.addDockWidget(Qt.BottomDockWidgetArea, self.report_dock)

    def _text_body(self, view, export_label, export_slot, table_slot=None):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(view)
        row = QHBoxLayout()
        exp = QPushButton(export_label)
        exp.clicked.connect(export_slot)
        cp = QPushButton("Copy")
        cp.clicked.connect(lambda: self._copy_text(view))
        row.addWidget(exp)
        row.addWidget(cp)
        if table_slot is not None:
            tb = QPushButton("Copy table")
            tb.setToolTip("Copy the peak table for pasting into Word/PowerPoint")
            tb.clicked.connect(table_slot)
            row.addWidget(tb)
        lay.addLayout(row)
        return w

    def _copy_report_table(self):
        head = ("Dataset", "Curve", "Peak", "Rt (min)", "y_max", "AUC", "%", "skew")
        rows = [head]
        for ds in self.datasets:
            for cv in ds.curves():
                for i, pk in enumerate(cv.peaks or [], 1):
                    rows.append((ds.meta.name, cv.name, pk.name or f"peak {i}", f"{pk.rt:.2f}",
                                 f"{pk.y_max:.0f}", f"{pk.auc:.1f}", f"{pk.pct:.1f}", f"{pk.skew:.2f}"))
        if len(rows) == 1:
            self.log("Copy table: no peaks yet.")
            return
        html = ("<table border=1 cellspacing=0 cellpadding=3>"
                + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
                + "</table>")
        md = QMimeData()
        md.setHtml(html)
        md.setText("\n".join("\t".join(r) for r in rows))
        QApplication.clipboard().setMimeData(md)
        self.log(f"Copied peak table ({len(rows) - 1} rows) — paste into Word/PowerPoint.")

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
        if not src or not tgt:
            return
        if src[0] == "dataset" and tgt[0] == "dataset":
            self._reorder_list(self.datasets, src[1], tgt[1], below, lambda d: d.id)
        elif src[0] == "curve" and tgt[0] == "curve" and src[1] == tgt[1]:
            ds = self._ds(src[1])
            if ds is None:
                return
            ps, pt = ds.parent_of(src[2]), ds.parent_of(tgt[2])
            if ps is None or ps is not pt:  # only reorder curves that share a parent
                return
            self._reorder_list(ps.children, src[2], tgt[2], below, lambda c: c.id)
        else:
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
        idx = next((i for i, o in enumerate(lst) if key(o) == tgt_id), None)
        if idx is None:
            lst.append(src)
        else:
            lst.insert(idx + 1 if below else idx, src)

    def _on_tree_select(self):
        data = self._selected()
        kind = data[0] if data else None
        self.btn_info.setEnabled(kind == "dataset")     # metadata lives on the dataset
        self.btn_adjust.setEnabled(kind == "curve")      # normalization is per-curve
        self.btn_disp.setEnabled(kind not in (None, "dataset"))
        self.btn_dup.setEnabled(kind == "curve")

    # ---------------- helpers ----------------
    def log(self, msg):
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {msg}")

    def _position_overlay(self):
        if not hasattr(self, "copy_btn"):
            return
        m = 10
        self.copy_btn.move(max(m, self.plot_view.width() - self.copy_btn.width() - m), m)
        self.copy_btn.raise_()
        if hasattr(self, "scale_bar"):
            self.scale_bar.move(m, max(m, self.plot_view.height() - self.scale_bar.height() - m))
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
        self.btn_export_plot.setEnabled(has)
        self.copy_btn.setEnabled(has)
        if not has:
            self.display_dock.hide()
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
        out = [f"SpikeRemover report — {ts}", ""]
        for ds in self.datasets:
            out.append(f"# {ds.meta.name}")
            out.append(f"  file: {ds.meta.original_filename}")
            if ds.run_datetime:
                out.append(f"  run: {ds.run_datetime}")
            if ds.meta.molecule:
                out.append(f"  molecule: {ds.meta.molecule}")
            if ds.meta.radioisotope:
                out.append(f"  radioisotope: {ds.meta.radioisotope}")
            for c in ds.conditions:
                out.append(f"  condition: {c.text()}")
            for cv in ds.curves():
                marks = []
                if cv.has_spikes:
                    marks.append(f"{len(cv.spike_indices())} spikes")
                if cv.baseline is not None:
                    marks.append("baseline")
                if cv.peaks:
                    marks.append(f"{len(cv.peaks)} peaks")
                out.append(f"  curve '{cv.name}' [{cv.kind}]" + (f" — {', '.join(marks)}" if marks else ""))
                if cv.peaks:
                    out.append("      #   Rt(min)   AUC        %")
                    for i, pk in enumerate(cv.peaks, 1):
                        out.append(f"      {i:<3} {pk.rt:>7.2f}  {pk.auc:>9.1f}  {pk.pct:>5.1f}")
            out.append("")
        self.report_view.setPlainText("\n".join(out))

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
        mask = detect(curve.y, self.spike_params)
        n = int(mask.sum())
        if n:
            import numpy as np
            curve.spike_mask = mask
            curve.spike_shown = np.ones(n, bool)
            cleaned = remove(curve.y, mask, method=self.interp_method)
            child = next((c for c in curve.children if c.kind == "spikeless"), None)
            if child is not None:
                child.y = cleaned
            else:
                curve.children.append(new_curve_from(curve, cleaned, "spikeless", "spikeless", "#00a000"))
            self.log(f"Detected {n} spike(s) on '{curve.name}' → spikeless child ({self.interp_method}).")
        else:
            curve.spike_mask = None
            self.log(f"No spikes on '{curve.name}'.")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _detect_baseline(self):
        ds, curve = self._need_curve()
        if curve is None:
            return
        curve.baseline = estimate_baseline(curve.y, self.baseline_method, self.baseline_n)
        curve.baseline_shown = True
        self.log(f"Baseline on '{curve.name}' ({self.baseline_method}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _detect_peaks(self):
        ds, curve = self._need_curve()
        if curve is None:
            return
        pks = detect_peaks(curve.y, curve.baseline, self.peak_params)
        curve.peak_local_baseline = self.peak_params.local_baseline
        analyze_peaks(curve.x, curve.y, pks, curve.baseline, curve.peak_local_baseline)
        curve.peaks = pks
        curve.peaks_group_shown = True
        self.log(f"Detected {len(pks)} peak(s) on '{curve.name}' "
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
        curve.children.append(new_curve_from(curve, curve.y * factor, name, base_kind, "#b000b0"))
        self.log(f"Applied decay to '{curve.name}' → '{name}' (ref {ds.decay_ref_label}).")
        self._rebuild_tree()
        self._refresh_plot()
        self._update_report()

    def _edit_decay_options(self, ds=None):
        if ds is None:
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

    def _copy_text(self, view):
        QApplication.clipboard().setText(view.toPlainText())
        self.log("Copied to clipboard.")

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
        path, _ = QFileDialog.getSaveFileName(self, "Export log", "spikeremover_log.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
            self.log(f"Log exported to {path}")

    def _export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "spikeremover_report.txt", "Text (*.txt)")
        if path:
            Path(path).write_text(self.report_view.toPlainText(), encoding="utf-8")
            self.log(f"Report exported to {path}")

    def _edit_export_options(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Export options")
        outer = QVBoxLayout(dlg)
        form = QFormLayout()
        dpi = _int_spin(72, 2400, self.export_opts.png_dpi, 50)
        clip_dpi = _int_spin(48, 1200, self.export_opts.clip_dpi, 25)
        clip = QComboBox()
        clip.addItem("PNG image", "png")
        clip.addItem("SVG vector", "svg")
        clip.setCurrentIndex(max(0, clip.findData(self.export_opts.clip_format)))
        form.addRow("PNG file dpi", dpi)
        form.addRow("Clipboard dpi", clip_dpi)
        form.addRow("Copy to clipboard as", clip)
        outer.addLayout(form)
        data_btn = QPushButton("Export selected curve (GINA X)…")
        data_btn.clicked.connect(self._export_data_gina)
        outer.addWidget(data_btn)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        outer.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        self.export_opts.png_dpi = dpi.value()
        self.export_opts.clip_dpi = clip_dpi.value()
        self.export_opts.clip_format = clip.currentData()
        self.log("Export options updated.")

    # ---------------- dialogs ----------------
    def _edit_info(self):
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
        elif kind == "spike":
            self._edit_spike_info(curve, data[3])
        elif kind == "peak":
            self._edit_peak_info(curve, data[3])
        elif kind == "spikes":
            self._edit_spike_viz(curve)
        elif kind == "baseline":
            self._edit_baseline_viz(curve)
        elif kind == "peaks":
            self._edit_peak_viz(curve)

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
        leg = QCheckBox("Show in legend")
        leg.setChecked(v.in_legend)
        form.addRow(r_fill)
        form.addRow(r_mark)
        form.addRow("Colour", color)
        form.addRow("Fill alpha", alpha)
        form.addRow("Marker", marker)
        form.addRow("On-graph label", annot)
        form.addRow(leg)
        if _run_dialog(dlg, form):
            curve.peak_viz = PeakViz(mode="markers" if r_mark.isChecked() else "fill",
                                     color=color.color, alpha=alpha.value(),
                                     marker=marker.currentText(), in_legend=leg.isChecked())
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
        for key in ("min", "first_n", "none"):
            method.addItem(BASELINE_LABELS[key], key)
        method.setCurrentIndex(max(0, method.findData(self.baseline_method)))
        n_spin = _int_spin(1, 100000, self.baseline_n, 1)
        method.currentIndexChanged.connect(lambda: n_spin.setEnabled(method.currentData() == "first_n"))
        n_spin.setEnabled(self.baseline_method == "first_n")
        form.addRow("Method", method)
        form.addRow("First N points", n_spin)
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
        dlg.setWindowTitle("App options")
        outer = QVBoxLayout(dlg)
        bg = ao.background
        g = QGroupBox("Background")
        f = QFormLayout(g)
        chk = QCheckBox("Checkered")
        chk.setChecked(bg.checkered)
        ca = _ColorButton(bg.color_a)
        cb = _ColorButton(bg.color_b)
        size = _spin(0.2, 20, bg.size_mm, 0.1)
        f.addRow(chk)
        f.addRow("Colour A / solid", ca)
        f.addRow("Colour B (checker)", cb)
        f.addRow("Checker cell (mm)", size)
        outer.addWidget(g)

        bd = ao.export_border
        gb = QGroupBox("Export-area border")
        fb = QFormLayout(gb)
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
        outer.addWidget(gb)

        form2 = QFormLayout()
        smax = _int_spin(2, 20, ao.scale_max, 1)
        form2.addRow("Resolution slider max (×)", smax)
        outer.addLayout(form2)

        lock = QCheckBox("Lock menu windows (no drag/float)")
        lock.setChecked(ao.lock_docks)
        outer.addWidget(lock)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        outer.addWidget(box)
        if dlg.exec() != QDialog.Accepted:
            return
        ao.scale_max = smax.value()
        self.scale_slider.setMaximum(ao.scale_max * 10)
        ao.background = Background(checkered=chk.isChecked(), color_a=ca.color,
                                  color_b=cb.color, size_mm=size.value())
        ao.export_border = ExportBorder(on=bd_on.isChecked(), color=bd_color.color,
                                        style=bd_style.currentText(), width=bd_width.value())
        ao.lock_docks = lock.isChecked()
        self.plot_view.set_background(ao.background)
        self._apply_lock()
        self._refresh_plot()
        self.log("App options updated.")


# ---------------- small widget helpers ----------------
class _DataTree(QTreeWidget):
    """Tree with drag-to-reorder that reorders the model (draw order = z-order) via a signal."""

    reordered = Signal(object, object, bool)  # (source data, target data, drop-below)

    def dropEvent(self, e):
        src = self.currentItem()
        tgt = self.itemAt(e.position().toPoint())
        below = self.dropIndicatorPosition() == QAbstractItemView.BelowItem
        e.ignore()  # we reorder the model ourselves; don't let Qt move the items
        if src is not None and tgt is not None and src is not tgt:
            self.reordered.emit(src.data(0, Qt.UserRole), tgt.data(0, Qt.UserRole), below)


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
