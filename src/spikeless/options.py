"""Spikeless - the Options window, and the one JSON file it saves to.

Topics on the left, a page each; every change saved the moment it is made, to
`spikeless_options.json` beside Spikeless.bat; Export… / Import… / Reset to defaults at the
foot. Whatever is missing or malformed in the file keeps its default, so an old or
hand-edited file never stops the app.

What lives here: how the figure is exported and copied, the isotopes (half-lives, which are
decay-corrected), the HPLC methods (region names by retention time), the log. The report's
choices are saved here too but set in the Report window. A run's processing (spike
sensitivity, background, regions) is not: it belongs to the run, and is saved with the session.

Also here, because every window needs them: `guard_fields` (the mouse wheel over a field
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
from .plotview import Background

APP_DIR = Path(__file__).resolve().parents[2]          # where Spikeless.bat is
OPTIONS_FILE = APP_DIR / "spikeless_options.json"
GREY = "color:#8d8d8d;"

PREFS: dict = {
    "background": asdict(Background()),   # behind the figure preview (transparency)
    "png_dpi": 600,
    "clip_dpi": 600,
    "clip_format": "png",
    "log_timestamps": True,
    "isotopes": [list(x) for x in ISOTOPES],   # [name, half-life h, decay-correct]
    "methods": [],                            # [method, region name, Rt from, Rt to] (min)
    "report_format": ".pdf",
    "report_sections": {"plot": True, "runs": True, "processing": True, "spikes": True,
                        "results": True},
    "report_cols": {"start": True, "end": True, "rt": True, "net": True,      # + Region, always
                    "unc": True, "pct": True, "pct_reg": False, "height": False,
                    "w_half": False, "sym": False, "rs": False, "sn": False, "flags": True},
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
    for k, v in _DEFAULTS.items():
        PREFS[k] = _merge(v, got.get(k))
    PREFS["isotopes"] = [[r[0], float(r[1]), bool(r[2]) if len(r) > 2 else False]
                         for r in PREFS["isotopes"] if isinstance(r, list) and len(r) in (2, 3)
                         and isinstance(r[0], str) and _num(r[1])]
    PREFS["methods"] = [[r[0], r[1], float(r[2]), float(r[3])] for r in PREFS["methods"]
                        if isinstance(r, list) and len(r) == 4 and isinstance(r[0], str)
                        and isinstance(r[1], str) and _num(r[2]) and _num(r[3])]
    set_half_lives(PREFS["isotopes"])


def save_prefs(path: Path | None = None) -> bool:
    try:
        (path or OPTIONS_FILE).write_text(json.dumps(PREFS, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        return True
    except OSError:
        return False


def method_names() -> list[str]:
    return list(dict.fromkeys(r[0] for r in PREFS["methods"] if r[0]))


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

    def set_color(self, color):
        self.color = color
        self._paint()

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
            self.set_color(c.name())
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
        for name, page in (("Figure", self._figure_page()), ("Isotopes", self._iso_page()),
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

    def _table(self, v, key, heads, kinds):
        """An editable list of rows (kinds: str / float / bool per column): typing saves it;
        + adds a row, − removes the selected ones. A row missing a value is left out."""
        t = QTableWidget(0, len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
                if all(x not in ("", None) for x in row):
                    out.append(row)
            self._set(key, out)

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
        h.addStretch(1)
        v.addLayout(h)
        return t

    def _figure_page(self):
        w, v = self._page("Figure", "How Copy and Export write the figure. What it shows, its "
                          "size, fonts and axes are in the Figure window.")
        f = QFormLayout()
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
        w, v = self._page("Isotopes", "The isotopes the runs' Isotope list offers, their "
                          "half-lives, and whether runs of each are decay-corrected: each "
                          "point back to the run start before integration, which the results "
                          "then say. Within a 15-min run that is 0.1 % for ¹⁷⁷Lu, 3 % for "
                          "⁹⁹ᵐTc, 17 % for ⁶⁸Ga. Edit a cell; + adds a row, − removes the "
                          "selected ones.")
        self._table(v, "isotopes", ["isotope", "half-life (h)", "decay-correct runs"],
                    (str, float, bool))
        return w

    def _methods_page(self):
        w, v = self._page("Methods", "Region names by retention time, per HPLC method. A run "
                          "picks its method (Runs step); a region whose apex falls in a window "
                          "of that method takes its name, unless one was typed. Without a "
                          "match, a region is “peak N (Rt)”. A row per region: the "
                          "method, the name, the window in minutes.")
        self._table(v, "methods", ["method", "region", "Rt from (min)", "Rt to (min)"],
                    (str, str, float, float))
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
    load_prefs(got={})
    assert PREFS == _DEFAULTS
    print("options self-check OK")


if __name__ == "__main__":
    _self_check()
