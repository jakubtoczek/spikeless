"""Spikeless - the Options window, and the one JSON file it saves to.

Topics on the left, a page each; every change saved the moment it is made, to
`spikeless_options.json` beside Spikeless.bat; Export… / Import… / Reset to defaults at the
foot. Whatever is missing or malformed in the file keeps its default, so an old or
hand-edited file never stops the app.

What lives here is how the plot is shown, copied and exported, which Processing buttons
show, the panels, the log and the isotope table. The report's choices are saved here too but
set in the Report window. The processing settings (each button's ⚙) are not: they start from
their defaults every session, as a threshold remembered from last week would be an analysis
nobody asked for today.

Also here, because every window needs them: `guard_wheel` (the mouse wheel over a field
scrolls the page, it does not change the value) and `ColorButton`.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .adjust import ISOTOPES, set_half_lives
from .plotting import BORDER_STYLES, ExportBorder
from .plotview import Background

APP_DIR = Path(__file__).resolve().parents[2]          # where Spikeless.bat is
OPTIONS_FILE = APP_DIR / "spikeless_options.json"
GREY = "color:#8d8d8d;"

# The Processing buttons, in pipeline order.
PROC_LABELS = {"spikes": "Detect spikes", "decay": "Apply decay",
               "baseline": "Detect baseline", "peaks": "Detect peaks"}

PREFS: dict = {
    "background": asdict(Background()),
    "export_border": asdict(ExportBorder()),
    "scale_max": 5,                     # top of the resolution slider (× plot size)
    "crop_fills": False,
    "png_dpi": 600,
    "clip_dpi": 600,
    "clip_format": "png",
    "proc_visible": {"spikes": True, "decay": False, "baseline": True, "peaks": True},
    "docks_open": {"data": True, "processing": True, "log": True, "plot_options": True},
    "lock_docks": True,
    "log_timestamps": True,
    "isotopes": [list(x) for x in ISOTOPES],
    "report_format": ".pdf",
    "report_sections": {"plot": True, "datasets": True, "curves": True, "spikes": False,
                        "peaks": True},
    "report_cols": {"num": True, "name": False, "rt": True, "x_start": False, "x_end": False,
                    "width": False, "y_max": False, "auc": True, "pct": True, "skew": False},
}
_DEFAULTS = copy.deepcopy(PREFS)


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


def load_prefs(path: Path | None = None, got=None) -> None:
    """Options from a JSON file (or a dict); what is missing or malformed keeps its default."""
    if got is None:
        try:
            got = json.loads((path or OPTIONS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
    got = got if isinstance(got, dict) else {}
    for k, v in _DEFAULTS.items():
        PREFS[k] = _merge(v, got.get(k))
    PREFS["isotopes"] = [[r[0], float(r[1])] for r in PREFS["isotopes"]
                         if isinstance(r, list) and len(r) == 2 and isinstance(r[0], str)
                         and type(r[1]) in (int, float)]
    set_half_lives(PREFS["isotopes"])


def save_prefs(path: Path | None = None) -> bool:
    try:
        (path or OPTIONS_FILE).write_text(json.dumps(PREFS, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        return True
    except OSError:
        return False


class _WheelGuard(QObject):
    """A field takes the wheel only once clicked into: scrolling a panel past a spin box
    must not change the plot. The ignored event goes on to the scroll area behind it."""

    def eventFilter(self, obj, ev):                     # noqa: N802 - Qt's name
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            ev.ignore()
            return True
        return False


_GUARD = _WheelGuard()


def guard_fields(root: QWidget) -> None:
    """Every spin box and combo under `root`: no wheel until clicked into, and a typed
    number applied on Enter or leaving the field, not at each key."""
    for w in root.findChildren(QAbstractSpinBox) + root.findChildren(QComboBox):
        # StrongFocus: the default WheelFocus would hand the field focus on the wheel event
        # itself, and the guard would let that same event through.
        w.setFocusPolicy(Qt.StrongFocus)
        w.installEventFilter(_GUARD)
        if isinstance(w, QAbstractSpinBox):
            w.setKeyboardTracking(False)


class ColorButton(QPushButton):
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


class OptionsWindow(QMainWindow):
    """The options, by topic on the left. Saved as they change; one JSON file, which can be
    exported to another computer and imported there."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Spikeless — options")
        self.resize(760, 560)
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
        save_prefs()
        self.main.apply_prefs()

    def _build(self) -> None:
        at = max(0, self.topics.currentRow())
        self.topics.clear()
        while self.pages.count():
            w = self.pages.widget(0)
            self.pages.removeWidget(w)
            w.deleteLater()
        for name, page in (("Plot", self._plot_page()), ("Screen", self._screen_page()),
                           ("Processing", self._proc_page()), ("Isotopes", self._iso_page()),
                           ("Panels", self._panels_page()), ("Log", self._log_page())):
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

    def _num(self, key, lo, hi, step, sub=None, suffix=""):
        val = PREFS[key][sub] if sub else PREFS[key]
        s = QSpinBox() if isinstance(val, int) else QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(val)
        s.setSuffix(suffix)
        s.valueChanged.connect(lambda x: self._set(key, x, sub))
        return s

    def _choice(self, key, items: dict, sub=None):
        cur = PREFS[key][sub] if sub else PREFS[key]
        c = QComboBox()
        c.addItems(list(items.values()))
        c.setCurrentIndex(list(items).index(cur) if cur in items else 0)
        c.activated.connect(lambda i: self._set(key, list(items)[i], sub))
        return c

    def _color(self, key, sub):
        b = ColorButton(PREFS[key][sub])
        b._on_change = lambda: self._set(key, b.color, sub)
        return b

    def _plot_page(self):
        w, v = self._page("Plot", "How the plot is drawn, copied and exported. Its size, axes "
                          "and legend are in the Plot options panel; each curve's look is "
                          "Display… in the Data panel.")
        self._check(v, "crop_fills", "Crop fill areas where a curve passes",
                    tip="Cuts AUC and baseline fills around each curve line, so overlapping "
                        "semi-transparent areas read cleanly. Best on an opaque plot background.")
        v.addSpacing(8)
        f = QFormLayout()
        f.addRow("Export PNG at", self._num("png_dpi", 72, 2400, 50, suffix=" dpi"))
        f.addRow("Copy at", self._num("clip_dpi", 72, 2400, 50, suffix=" dpi"))
        f.addRow("Copy as", self._choice("clip_format", {"png": "PNG image",
                                                         "svg": "SVG vector"}))
        v.addLayout(f)
        g = QLabel("A copied PNG carries its resolution, so it pastes into PowerPoint or Word "
                   "at the plot's size in mm.")
        g.setWordWrap(True)
        g.setStyleSheet(GREY)
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _screen_page(self):
        w, v = self._page("Screen", "What the plot sits on, on screen. None of this is copied "
                          "or exported.")
        v.addWidget(QLabel("<b>Background</b>"))
        self._check(v, "background", "Checkered", "checkered")
        f = QFormLayout()
        f.addRow("Colour A / solid", self._color("background", "color_a"))
        f.addRow("Colour B (checker)", self._color("background", "color_b"))
        f.addRow("Checker cell", self._num("background", 0.2, 20, 0.1, "size_mm", " mm"))
        v.addLayout(f)
        v.addSpacing(8)
        v.addWidget(QLabel("<b>Export-area guide</b>"))
        self._check(v, "export_border", "Show where the exported image ends", "on")
        f = QFormLayout()
        f.addRow("Colour", self._color("export_border", "color"))
        f.addRow("Style", self._choice("export_border", {k: k for k in BORDER_STYLES}, "style"))
        f.addRow("Width", self._num("export_border", 0.1, 3, 0.1, "width", " pt"))
        v.addLayout(f)
        v.addSpacing(8)
        f = QFormLayout()
        f.addRow("Resolution slider up to", self._num("scale_max", 2, 20, 1, suffix=" ×"))
        v.addLayout(f)
        v.addStretch(1)
        return w

    def _proc_page(self):
        w, v = self._page("Processing", "The buttons the Processing panel shows. Their "
                          "settings (each button's ⚙) start from their defaults every session.")
        for key, label in PROC_LABELS.items():
            self._check(v, "proc_visible", label, key)
        v.addStretch(1)
        return w

    def _iso_page(self):
        w, v = self._page("Isotopes", "The isotopes the Radioisotope lists offer, and the "
                          "half-lives decay correction uses. Edit a cell; + adds a row, − "
                          "removes the selected ones.")
        t = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["isotope", "half-life (h)"])
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        rows = PREFS["isotopes"]
        t.setRowCount(len(rows))
        for r, (name, h) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(name))
            t.setItem(r, 1, QTableWidgetItem(f"{h:g}"))

        def read(*_):
            out = []
            for r in range(t.rowCount()):
                name = (t.item(r, 0).text().strip() if t.item(r, 0) else "")
                try:
                    h = float((t.item(r, 1).text() if t.item(r, 1) else "").replace(",", "."))
                except ValueError:
                    h = 0.0
                if name and h > 0:
                    out.append([name, h])
            self._set("isotopes", out)
        t.itemChanged.connect(read)
        v.addWidget(t, 1)
        h = QHBoxLayout()
        for text, fn in (("+", lambda: (t.insertRow(t.rowCount()), t.scrollToBottom())),
                         ("−", lambda: ([t.removeRow(r) for r in sorted(
                             {i.row() for i in t.selectedIndexes()}, reverse=True)], read()))):
            b = QPushButton(text)
            b.setFixedWidth(34)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)
        return w

    def _panels_page(self):
        w, v = self._page("Panels", "The panels open when Spikeless starts (Plot options once "
                          "data is loaded). Locked, a panel can't be dragged off or floated.")
        for key, label in (("data", "Data"), ("processing", "Processing"), ("log", "Log"),
                           ("plot_options", "Plot options")):
            self._check(v, "docks_open", label, key)
        v.addSpacing(8)
        self._check(v, "lock_docks", "Lock the panels")
        v.addStretch(1)
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
                    "proc_visible": [1], "isotopes": [["¹⁸F", 1.83], ["bad"], [3, 4]],
                    "unknown": 1})
    assert PREFS["png_dpi"] == 600 and PREFS["clip_dpi"] == 300
    assert isinstance(PREFS["clip_dpi"], int)
    assert PREFS["background"]["size_mm"] == 2.0 and PREFS["background"]["checkered"] is True
    assert PREFS["proc_visible"] == _DEFAULTS["proc_visible"]
    assert PREFS["isotopes"] == [["¹⁸F", 1.83]] and "unknown" not in PREFS
    from .adjust import lookup_half_life_s
    assert lookup_half_life_s("¹⁸F") == 1.83 * 3600 and lookup_half_life_s("¹⁷⁷Lu") is None
    load_prefs(got={})
    assert PREFS == _DEFAULTS
    print("options self-check OK")


if __name__ == "__main__":
    _self_check()
