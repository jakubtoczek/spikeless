"""Spikeless - the Options window, and the one JSON file it saves to.

Topics on the left, a page each; every change saved the moment it is made, to
`spikeless_options.json` beside Spikeless.bat; Export… / Import… / Reset to defaults at the
foot. Whatever is missing or malformed in the file keeps its default, so an old or
hand-edited file never stops the app.

What lives here: what the mouse does on the chromatogram, how the figure is exported and
copied, the isotopes (half-lives, which are decay-corrected), the HPLC methods (region names by
retention time, their conditions), the log, and the settings a run starts with (spikes,
background, finding regions). The report's choices are saved here too but set in the Report
window. A run's own processing is not: it belongs to the run, and is saved with the session.

"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import plotting
from .adjust import ISOTOPES, OLD_HALF_LIVES, set_half_lives
from .plotview import Background
from .widgets import ColorButton, guard_fields

APP_DIR = Path(__file__).resolve().parents[2]          # where Spikeless.bat is
OPTIONS_FILE = APP_DIR / "spikeless_options.json"
GREY = "color:#8d8d8d;"

PREFS: dict = {
    "chrom": {"left_drag": "zoom", "right_drag": "pan",       # "zoom" | "pan"
              "left_click": "centre",                          # "centre" | "line"
              "wheel_y": False,                                # the wheel zooms the height too
              "light": True,                                   # white around the plot, dark text
              "edge_unit": "min"},                             # a region's typed edges: point | s | min
    "raw_trace": {"color": "#b0b0b0", "width": 0.8, "style": "solid"},   # × the trace's width
    "spike_line": {"color": "#e02020", "width": 1.0},                    # (the figure too)
    "bg_line": {"color": "#808080", "width": 0.8, "style": "dashed"},
    "y_below_pct": 3.0,                       # the y axis starts this % of its top below zero
    "spikes": {"n_sigma": 5.0, "window": 7, "max_width": 1,   # a new run's
               "auto": True},                     # found on load and as the threshold moves
    "bg": {"mode": "auto", "stretch_from": 0.5, "stretch_to": 1.5,   # a new run's
           "drift": "snip", "n": 40,
           "offer": {"none": True, "auto": True, "stretch": True, "drift": False}},  # in the step
    "find": {"n_sigma": 8.0, "min_gap_s": 10.0, "smooth": 5, "foot_sigma": 2.0,  # a new run's
             "auto": False,
             "sigma_at": "base"},     # σ where the apex stands (2026.10.16): marks the rule
    "background": asdict(Background()),   # behind the figure preview (transparency)
    "png_dpi": 600,
    "clip_dpi": 600,
    "clip_format": "png",
    "log_timestamps": True,
    "isotopes": [list(x) for x in ISOTOPES],   # [name, half-life h, decay-correct]
    "methods": [],                            # [method, region name, Rt from, Rt to] (min)
    "method_info": [],                        # [method, field, value]: its conditions
    "report_format": ".pdf",
    "report_scope": "summary",                # report.SCOPES
    "report_sections": {"plot": True, "runs": True, "processing": True, "spikes": True,
                        "results": True},
    "run_fields": {"isotope": False, "method": False, "molecule": True,   # the Runs panel's
                   "conditions": True, "color": True, "details": True},
    "table_cols": {"start": True, "end": True, "rt": True, "net": True,       # under the plot
                   "unc": True, "pct": True, "pct_reg": False, "height": False,
                   "w_half": False, "sym": False, "rs": False, "sn": False, "flags": True},
    "report_cols": {"start": True, "end": True, "rt": True, "net": True,      # + Region, always
                    "unc": True, "pct": True, "pct_reg": False, "height": False,
                    "w_half": False, "sym": False, "rs": False, "sn": False, "flags": True},
}
_DEFAULTS = copy.deepcopy(PREFS)
_CHOICES = {("chrom", "left_drag"): ("zoom", "pan"), ("chrom", "right_drag"): ("zoom", "pan"),
            ("chrom", "left_click"): ("centre", "line"),
            ("chrom", "edge_unit"): ("point", "s", "min"),
            ("bg", "mode"): ("none", "auto", "stretch", "drift"), ("bg", "drift"): ("snip", "arpls"),
            ("raw_trace", "style"): ("solid", "dotted", "dashed", "dashdot"),
            ("bg_line", "style"): ("solid", "dotted", "dashed", "dashdot")}
BG_MODES = {"none": "None", "auto": "Mean outside the regions", "stretch": "Mean of a stretch",
            "drift": "Follows a drift"}
USUAL_FIELDS = ["Column", "Mobile phase A", "Mobile phase B", "Gradient", "Flow rate (mL/min)",
                "Column temperature (°C)", "Injection volume (µL)", "UV detection (nm)",
                "Radio-detector"]


def _merge(default, got):
    """`got` where it has the default's type (any number for a number); a dict key by key,
    so a key a later version adds keeps its default."""
    if isinstance(default, dict):
        got = got if isinstance(got, dict) else {}
        return {k: _merge(v, got.get(k)) for k, v in default.items()}
    num = (int, float)
    if type(default) in num and type(got) in num:
        return type(default)(got)
    return copy.deepcopy(got if type(got) is type(default) else default)


def _num(v):
    return type(v) in (int, float)


def load_prefs(path: Path | None = None, got=None) -> None:
    """Options from a JSON file (or a dict); what is missing or malformed keeps its default."""
    if got is None:
        try:
            got = json.loads((path or OPTIONS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
    got = got if isinstance(got, dict) else {}
    find = got.get("find")
    if isinstance(find, dict) and find.get("sigma_at") != "base":
        find.pop("n_sigma", None)          # a threshold of the old rule (σ of the background)
    for k, v in _DEFAULTS.items():
        PREFS[k] = _merge(v, got.get(k))
    new = {r[0]: r[1] for r in ISOTOPES}         # the half-lives shipped before DDEP: the new ones
    PREFS["isotopes"] = [[r[0], new[r[0]] if OLD_HALF_LIVES.get(r[0]) == r[1] else float(r[1]),
                          bool(r[2]) if len(r) > 2 else False]
                         for r in PREFS["isotopes"] if isinstance(r, list) and len(r) in (2, 3)
                         and isinstance(r[0], str) and _num(r[1])]
    PREFS["methods"] = [[r[0], r[1], float(r[2]), float(r[3])] for r in PREFS["methods"]
                        if isinstance(r, list) and len(r) == 4 and isinstance(r[0], str)
                        and isinstance(r[1], str) and _num(r[2]) and _num(r[3])]
    PREFS["method_info"] = [list(r) for r in PREFS["method_info"] if isinstance(r, list)
                            and len(r) == 3 and all(isinstance(c, str) for c in r)]
    for (key, sub), ok in _CHOICES.items():
        if PREFS[key][sub] not in ok:
            PREFS[key][sub] = _DEFAULTS[key][sub]
    set_half_lives(PREFS["isotopes"])
    sync_style()


def sync_style() -> None:
    """The options the drawing reads (plotting.STYLE), from PREFS."""
    r, s, b = PREFS["raw_trace"], PREFS["spike_line"], PREFS["bg_line"]
    plotting.STYLE.update(y_below_pct=PREFS["y_below_pct"], raw_color=r["color"],
                          raw_width=r["width"], raw_style=r["style"], spike_color=s["color"],
                          spike_width=s["width"], bg_color=b["color"], bg_width=b["width"],
                          bg_style=b["style"])


def params(key) -> dict:
    """A new run's settings (Options › Spikes / Regions), its "auto" (and marker) left out."""
    return {k: v for k, v in PREFS[key].items() if k not in ("auto", "sigma_at")}


def save_prefs(path: Path | None = None) -> bool:
    try:
        (path or OPTIONS_FILE).write_text(json.dumps(PREFS, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        return True
    except OSError:
        return False


def method_names() -> list[str]:
    return list(dict.fromkeys(r[0] for r in PREFS["methods"] + PREFS["method_info"] if r[0]))


def method_info(method: str) -> list[tuple[str, str]]:
    """(field, value) of a method's conditions (Options › Methods), the filled ones."""
    return [(r[1], r[2]) for r in PREFS["method_info"] if method and r[0] == method and r[2]]


class OptionsWindow(QMainWindow):
    """The options, by topic on the left. Saved as they change; one JSON file, which can be
    exported to another computer and imported there."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Spikeless — options")
        self.resize(860, 720)
        self.topics = QListWidget()
        self.topics.setFixedWidth(170)
        self.pages = QStackedWidget()
        self.topics.currentRowChanged.connect(self.pages.setCurrentIndex)
        foot = QHBoxLayout()
        for text, help_, fn in (
                ("Export…", "Write every option to a JSON file", self._export),
                ("Import…", "Read the options from a JSON file", self._import),
                ("Reset to defaults", "Every option back to how Spikeless ships", self._reset)):
            b = QPushButton(text)
            b.setToolTip(help_)
            b.clicked.connect(fn)
            foot.addWidget(b)
        foot.addStretch(1)
        where = QLabel(f"saved as they change, in {OPTIONS_FILE}")
        where.setStyleSheet(GREY)
        foot.addWidget(where)
        root = QWidget()
        v = QVBoxLayout(root)
        h = QHBoxLayout()
        h.addWidget(self.topics)
        h.addWidget(self.pages, 1)
        v.addLayout(h, 1)
        v.addLayout(foot)
        self.setCentralWidget(root)
        self._build()

    def open(self, topic: str | None = None):
        if topic:
            hit = self.topics.findItems(topic, Qt.MatchExactly)
            if hit:
                self.topics.setCurrentItem(hit[0])
        self.show()
        self.raise_()
        self.activateWindow()

    def _set(self, key, value, sub=None) -> None:
        """One option changed: saved, and the app follows."""
        old = PREFS[key][sub] if sub else PREFS[key]
        if old == value:
            return
        if sub:
            PREFS[key][sub] = value
        else:
            PREFS[key] = value
        if key == "isotopes":
            set_half_lives(value)
        sync_style()
        save_prefs()
        self.main.apply_prefs()

    def _build(self) -> None:
        at = max(0, self.topics.currentRow())
        self.topics.clear()
        while self.pages.count():
            w = self.pages.widget(0)
            self.pages.removeWidget(w)
            w.deleteLater()
        for name, page in (("Chromatogram", self._chrom_page()), ("Figure", self._figure_page()),
                           ("Runs", self._runs_page()), ("Spikes", self._spikes_page()),
                           ("Background", self._bg_page()), ("Regions", self._find_page()),
                           ("Results", self._results_page()), ("Isotopes", self._iso_page()),
                           ("Methods", self._methods_page()), ("Log", self._log_page())):
            self.topics.addItem(name)
            sc = QScrollArea(widgetResizable=True)
            sc.setFrameShape(QScrollArea.NoFrame)
            sc.setWidget(page)
            self.pages.addWidget(sc)
        self.topics.setCurrentRow(at)
        guard_fields(self.pages)

    @staticmethod
    def _page(title, text):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 4, 8, 4)
        t = QLabel(f"<b>{title}</b>")
        t.setStyleSheet("font-size:14px;")
        v.addWidget(t)
        g = QLabel(text)
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        return w, v

    def _check(self, v, key, text, sub=None, tip=""):
        c = QCheckBox(text)
        c.setChecked(PREFS[key][sub] if sub else PREFS[key])
        c.setToolTip(tip)
        c.toggled.connect(lambda on: self._set(key, on, sub))
        v.addWidget(c)
        return c

    def _number(self, key, lo, hi, step, sub=None, suffix=""):
        val = PREFS[key][sub] if sub else PREFS[key]
        s = QSpinBox() if isinstance(val, int) else QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(val)
        s.setSuffix(suffix)
        s.valueChanged.connect(lambda x: self._set(key, x, sub))
        return s

    def _color(self, key, sub):
        b = ColorButton(PREFS[key][sub])
        b._on_change = lambda: self._set(key, b.color, sub)
        return b

    def _offer(self, mode, on):
        PREFS["bg"]["offer"][mode] = on
        save_prefs()
        self.main.apply_prefs()

    def _choice(self, key, sub, items):
        """A list of (value, text) for PREFS[key][sub]."""
        c = QComboBox()
        for val, text in items:
            c.addItem(text, val)
        c.setCurrentIndex(max(0, c.findData(PREFS[key][sub])))
        c.activated.connect(lambda i: self._set(key, c.itemData(i), sub))
        return c

    def _tick(self, key, sub, text, tip=""):
        c = QCheckBox(text)
        c.setChecked(PREFS[key][sub])
        c.setToolTip(tip)
        c.toggled.connect(lambda on: self._set(key, on, sub))
        return c

    def _table(self, v, key, heads, kinds, need=None, rows_shown=6, extra=()):
        """An editable list of rows (kinds: str / float / bool per column): typing saves it;
        + adds a row, − removes the selected ones (extra: more widgets beside them). A row
        missing a value of the columns `need` (all of them by default) is left out. Tall
        enough for rows_shown rows without a scroll bar."""
        need = range(len(heads)) if need is None else need
        t = QTableWidget(0, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(22)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setMinimumHeight(t.horizontalHeader().sizeHint().height() + 22 * rows_shown + 4)
        rows = PREFS[key]
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (val, kind) in enumerate(zip(row, kinds)):
                it = QTableWidgetItem()
                if kind is bool:
                    it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    it.setCheckState(Qt.Checked if val else Qt.Unchecked)
                else:
                    it.setText(f"{val:g}" if kind is float else str(val))
                t.setItem(r, c, it)

        def read(*_):
            out = []
            for r in range(t.rowCount()):
                row = []
                for c, kind in enumerate(kinds):
                    it = t.item(r, c)
                    if kind is bool:
                        row.append(bool(it) and it.checkState() == Qt.Checked)
                    elif kind is float:
                        try:
                            row.append(float((it.text() if it else "").replace(",", ".")))
                        except ValueError:
                            row.append(None)
                    else:
                        row.append(it.text().strip() if it else "")
                if None not in row and all(row[i] != "" for i in need):
                    out.append(row)
            self._set(key, out)
        t.read = read

        def add():
            t.insertRow(t.rowCount())
            for c, kind in enumerate(kinds):
                if kind is bool:
                    it = QTableWidgetItem()
                    it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    it.setCheckState(Qt.Unchecked)
                    t.setItem(t.rowCount() - 1, c, it)
            t.scrollToBottom()

        t.itemChanged.connect(read)
        v.addWidget(t, 1)
        h = QHBoxLayout()
        for text, fn in (("+", add),
                         ("−", lambda: ([t.removeRow(r) for r in sorted(
                             {i.row() for i in t.selectedIndexes()}, reverse=True)], read()))):
            b = QPushButton(text)
            b.setFixedWidth(34)
            b.clicked.connect(fn)
            h.addWidget(b)
        for wdg in extra:
            h.addWidget(wdg)
        h.addStretch(1)
        v.addLayout(h)
        return t

    def _chrom_page(self):
        w, v = self._page("Chromatogram", "What the mouse does on the plot. A double-click "
                          "always shows the whole run; on a region's edge a left drag moves "
                          "it; Draw region (Regions) and Draw stretch (Background) arm drawing.")
        f = QFormLayout()
        drag = (("zoom", "Zoom to the span (the height fitted)"), ("pan", "Pan"))
        f.addRow("Left drag", self._choice("chrom", "left_drag", drag))
        f.addRow("Right drag", self._choice("chrom", "right_drag", drag))
        f.addRow("Left click", self._choice("chrom", "left_click", (
            ("centre", "A reading line there; a zoomed view centred on it"),
            ("line", "A reading line there"))))
        f.addRow(self._tick("chrom", "wheel_y", "The wheel zooms the height too (else the time "
                            "only; Ctrl+wheel the height)", "Unlocked, the height springs back "
                            "to fit the traces when zoomed out past them"))
        f.addRow(self._tick("chrom", "light", "White around the plot, its axes in dark grey "
                            "(else the app's dark grey)", "As the figure is: what ⧉ Copy "
                            "takes reads well on a page"))
        v.addLayout(f)
        styles = [(s, s) for s in _CHOICES[("raw_trace", "style")]]
        for key, title, line in (("raw_trace", "Trace as recorded", True),
                                 ("spike_line", "Excluded spikes", False),
                                 ("bg_line", "Background line", True)):
            v.addSpacing(8)
            v.addWidget(QLabel(f"<b>{title}</b> (the figure too)"))
            f = QFormLayout()
            f.addRow("Colour", self._color(key, "color"))
            f.addRow("Width (× the trace's)", self._number(key, 0.1, 5, 0.1, "width"))
            if line:
                f.addRow("Line", self._choice(key, "style", styles))
            v.addLayout(f)
        v.addStretch(1)
        return w

    def _spikes_page(self):
        w, v = self._page("Spikes", "The rule a run is loaded with (the Spikes step changes "
                          "a run's own). A rule fixed in advance is what makes spike removal "
                          "defensible: change it here, for your procedure, not run by run.")
        f = QFormLayout()
        f.addRow(self._tick("spikes", "auto", "Found on their own: when a run is loaded, and "
                            "as the threshold moves (else: Find spikes)"))
        f.addRow("Threshold", self._number("spikes", 1, 50, 0.5, "n_sigma", " σ"))
        f.addRow("Window (points, odd)", self._number("spikes", 3, 101, 2, "window"))
        f.addRow("Max width (points)", self._number("spikes", 1, 10, 1, "max_width"))
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _bg_page(self):
        w, v = self._page("Background", "The background a run is loaded with (the "
                          "Background step changes a run's own). A radio-detector's is flat "
                          "— its count rate, with Poisson noise — so a mean is right; one "
                          "that follows a drift is not offered at first.")
        f = QFormLayout()
        f.addRow("A new run's", self._choice("bg", "mode", BG_MODES.items()))
        offer = QHBoxLayout()
        for mode, text in BG_MODES.items():
            c = QCheckBox(text)
            c.setChecked(PREFS["bg"]["offer"][mode])
            c.toggled.connect(lambda on, m=mode: self._offer(m, on))
            offer.addWidget(c)
        offer.addStretch(1)
        f.addRow("Offered", offer)
        f.addRow("Stretch from", self._number("bg", 0, 1000, 0.1, "stretch_from", " min"))
        f.addRow("Stretch to", self._number("bg", 0, 1000, 0.1, "stretch_to", " min"))
        f.addRow("Drift", self._choice("bg", "drift", (("snip", "SNIP"), ("arpls", "arPLS"))))
        f.addRow("SNIP half-width", self._number("bg", 2, 1000, 1, "n", " points"))
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _find_page(self):
        w, v = self._page("Regions", "How Find regions looks for peaks, for a run loaded from "
                          "now on (the Regions step changes a run's own): an apex of the "
                          "moving mean standing the threshold above its surroundings, σ the "
                          "Poisson noise of that mean at the background; its region out to "
                          "where the mean "
                          "falls back within the feet's σ, or to the valley it shares.")
        f = QFormLayout()
        f.addRow(self._tick("find", "auto", "Found on their own: when a run is loaded, and as "
                            "the threshold moves (else: Find regions)"))
        f.addRow("Threshold", self._number("find", 1, 50, 0.5, "n_sigma", " σ"))
        f.addRow("Apexes at least", self._number("find", 0, 600, 1, "min_gap_s", " s apart"))
        f.addRow("Moving mean of", self._number("find", 1, 51, 2, "smooth", " points"))
        f.addRow("Feet at", self._number("find", 0.5, 20, 0.5, "foot_sigma", " σ"))
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _runs_page(self):
        w, v = self._page("Runs", "What the Runs panel shows for the selected run. A field "
                          "hidden keeps its value: a run's isotope still corrects its decay, "
                          "its method still names its regions.")
        for key, text, tip in (
                ("isotope", "Isotope", "Its half-life, and its decay correction if ticked in "
                 "Isotopes"),
                ("method", "Method", "Names its regions and gives the report its conditions "
                 "(Methods)"),
                ("molecule", "Molecule", "Free text, in the report"),
                ("conditions", "Conditions", "Free text, a line each (pH: 7), in the report"),
                ("color", "Colour", "Its trace's colour"),
                ("details", "Details", "Its original name, file, run date, points, SHA-256")):
            v.addWidget(self._tick("run_fields", key, text, tip))
        v.addStretch(1)
        return w

    def _results_page(self):
        from .report import COLUMNS, HELP           # report imports this module
        w, v = self._page("Results", "The columns of the results table under the plot; the "
                          "region's name is always there. The report picks its own, in the "
                          "Report window; ⤢ above the table shows them all.")
        f = QFormLayout()
        f.setVerticalSpacing(6)
        for key, head, _ in COLUMNS[1:]:
            g = QLabel(HELP.get(key, ""))
            g.setWordWrap(True)
            g.setStyleSheet(GREY)
            f.addRow(self._tick("table_cols", key, head, HELP.get(key, "")), g)
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _figure_page(self):
        w, v = self._page("Figure", "How Copy and Export write the figure. What it shows, its "
                          "size, fonts and axes are in the Figure window.")
        f = QFormLayout()
        f.addRow("Under zero, the y axis starts at −", self._number(
            "y_below_pct", 0, 50, 0.5, suffix=" % of its top"))
        f.addRow("Export PNG at", self._number("png_dpi", 72, 2400, 50, suffix=" dpi"))
        f.addRow("Copy at", self._number("clip_dpi", 72, 2400, 50, suffix=" dpi"))
        c = QComboBox()
        c.addItems(["PNG image", "SVG vector"])
        c.setCurrentIndex(1 if PREFS["clip_format"] == "svg" else 0)
        c.activated.connect(lambda i: self._set("clip_format", ("png", "svg")[i]))
        f.addRow("Copy as", c)
        v.addLayout(f)
        g = QLabel("A copied PNG carries its resolution, so it pastes into PowerPoint or Word "
                   "at the figure's size in mm.")
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        v.addSpacing(8)
        v.addWidget(QLabel("<b>Behind the preview</b> (shows through transparent parts)"))
        self._check(v, "background", "Checkered", "checkered")
        f = QFormLayout()
        f.addRow("Colour A / solid", self._color("background", "color_a"))
        f.addRow("Colour B (checker)", self._color("background", "color_b"))
        f.addRow("Checker cell", self._number("background", 0.2, 20, 0.1, "size_mm", " mm"))
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _iso_page(self):
        w, v = self._page("Isotopes", "The isotopes a run's Isotope offers (shown when ticked "
                          "in Runs), their half-lives, and whether runs of each are "
                          "decay-corrected — each point back to the run start, before "
                          "integration. Within a 15-min run that is 0.1 % for ¹⁷⁷Lu, 3 % for "
                          "⁹⁹ᵐTc, 17 % for ⁶⁸Ga.")
        self._table(v, "isotopes", ["isotope", "half-life (h)", "decay-correct runs"],
                    (str, float, bool), rows_shown=len(ISOTOPES))
        return w

    def _methods_page(self):
        w, v = self._page("Methods", "A run picks its method in Runs (its Method shown when "
                          "ticked in Runs). Its regions take their names from the method's "
                          "retention-time windows, unless one was typed; else “peak N (Rt)”.")
        self._table(v, "methods", ["method", "region", "Rt from (min)", "Rt to (min)"],
                    (str, str, float, float), rows_shown=5)
        v.addSpacing(8)
        g = QLabel("<b>Conditions</b> — in the report, for a run of the method: a row per "
                   "field; one left empty is left out.")
        g.setWordWrap(True)
        v.addWidget(g)
        pick = QComboBox()
        pick.setEditable(True)
        pick.addItems(method_names())
        pick.lineEdit().setPlaceholderText("method")
        pick.setMinimumWidth(160)
        b = QPushButton("＋ The usual fields for")
        b.setToolTip("A row for each field a chromatographic method states — column, mobile "
                     "phases, gradient, flow rate, temperature, injection volume, detectors — "
                     "to fill in")
        t = self._table(v, "method_info", ["method", "field", "value"], (str, str, str),
                        need=(0, 1), rows_shown=len(USUAL_FIELDS), extra=(b, pick))

        def usual():
            m = pick.currentText().strip()
            if not m:
                return
            have = {(r[0], r[1]) for r in PREFS["method_info"]}
            t.blockSignals(True)
            for fld in USUAL_FIELDS:
                if (m, fld) not in have:
                    r = t.rowCount()
                    t.insertRow(r)
                    for c, text in enumerate((m, fld, "")):
                        t.setItem(r, c, QTableWidgetItem(text))
            t.blockSignals(False)
            t.read()

        b.clicked.connect(usual)
        return w

    def _log_page(self):
        w, v = self._page("Log", "What the log's Copy and Export write.")
        self._check(v, "log_timestamps", "Include the [HH:MM:SS] time of each line")
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ the file

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export options", "spikeless_options.json",
                                              "JSON (*.json)")
        if path and not save_prefs(Path(path)):
            QMessageBox.warning(self, "Spikeless", f"Could not write {path}")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import options", "", "JSON (*.json)")
        if path:
            self._apply(Path(path))

    def _reset(self):
        if QMessageBox.question(self, "Spikeless", "Every option back to its default?") \
                == QMessageBox.Yes:
            self._apply(None)

    def _apply(self, path):
        load_prefs(path, None if path else {})
        save_prefs()
        self._build()
        self.main.apply_prefs()


def _self_check():
    """Malformed and partial files keep the defaults; a good value is taken."""
    load_prefs(got={"png_dpi": "lots", "clip_dpi": 300.0, "background": {"size_mm": 2},
                    "isotopes": [["¹⁸F", 1.83], ["⁶⁸Ga", 1.13, True], ["bad"], [3, 4]],
                    "methods": [["M", "product", 7, 9.5], ["M", "bad", "x", 1]],
                    "report_sections": [1], "unknown": 1})
    assert PREFS["png_dpi"] == 600 and PREFS["clip_dpi"] == 300
    assert isinstance(PREFS["clip_dpi"], int)
    assert PREFS["background"]["size_mm"] == 2.0 and PREFS["background"]["checkered"] is True
    assert PREFS["report_sections"] == _DEFAULTS["report_sections"]
    assert PREFS["isotopes"] == [["¹⁸F", 1.83, False], ["⁶⁸Ga", 1.13, True]]
    assert PREFS["methods"] == [["M", "product", 7.0, 9.5]] and method_names() == ["M"]
    assert "unknown" not in PREFS
    from .adjust import decay_on, lookup_half_life_s
    assert lookup_half_life_s("¹⁸F") == 1.83 * 3600 and lookup_half_life_s("¹⁷⁷Lu") is None
    assert decay_on("⁶⁸Ga") and not decay_on("¹⁸F")
    load_prefs(got={"chrom": {"left_drag": "fly", "wheel_y": True}, "y_below_pct": 5,
                    "method_info": [["M", "Column", "C18"], ["M", "Flow", ""], ["bad"]]})
    assert PREFS["chrom"]["left_drag"] == "zoom" and PREFS["chrom"]["wheel_y"] is True
    assert plotting.STYLE["y_below_pct"] == 5.0
    assert method_info("M") == [("Column", "C18")] and method_info("") == []
    load_prefs(got={})
    assert PREFS == _DEFAULTS
    print("options self-check OK")


if __name__ == "__main__":
    _self_check()
