"""Spikeless - editing windows: the runs' names, the selected run's regions in full, and the
selected region on its own.

Run names (▤): a run keeps the name it came with — its file's, "Clipboard 2" — in the first
column, hidden unless asked; Name is what the app and the report call it; Legend what the
figure's legend says. Grey: as it follows (the name the original, the legend the name);
white: set by hand. Clearing a cell makes it follow again. Every edit is one undo step.

Regions (⤢): every measure of each region, whatever the report's columns, and how it is drawn
— its colour (click the swatch), whether the figure labels it — and its note.

Region (Edit… on a region): its name, what its net counts are above, its note, its colour, its
label on the figure; it follows the region selected.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .options import ColorButton, guard_fields, pick_color
from .report import COLUMNS, HELP

GREY, WHITE = QColor("#8d8d8d"), QColor("#e0e0e0")


def copy_table(rows) -> None:
    """Rows of text to the clipboard: tab-separated (Excel) and as an HTML table (Word)."""
    md = QMimeData()
    md.setText("\n".join("\t".join(r) for r in rows))
    md.setHtml("<table border=1 cellspacing=0 cellpadding=3>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
    QApplication.clipboard().setMimeData(md)


def _item(text, color=None, edit=False, right=False):
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | (Qt.ItemIsEditable if edit else
                                                          Qt.NoItemFlags))
    if color is not None:
        it.setForeground(color)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class _Window(QMainWindow):
    """Shown on demand, kept in step with the main window (refresh), never rebuilt from
    inside one of its own table's signals."""

    def __init__(self, main, title, size, table=True):
        super().__init__(main)
        self.main = main
        self.setWindowTitle(title)
        self.resize(*size)
        self._filling = False
        if table:
            self.t = QTableWidget()
            self.t.verticalHeader().setVisible(False)
            self.t.itemChanged.connect(lambda it: self._filling or self._edited(it))

    def open(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh_later(self):
        if self.isVisible():
            QTimer.singleShot(0, self.refresh)


class NamesWindow(_Window):
    def __init__(self, main):
        super().__init__(main, "Spikeless — run names", (640, 340))
        self.t.setColumnCount(3)
        self.t.setHorizontalHeaderLabels(["Original", "Name", "Legend"])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setColumnHidden(0, True)
        orig = QCheckBox("Show the original names")
        orig.toggled.connect(lambda on: self.t.setColumnHidden(0, not on))
        g = QLabel("Name: what the app and the report call the run. Legend: what the figure "
                   "says. Grey: as it follows (the name the original, the legend the name); "
                   "white: set by hand. Clear a cell to make it follow again.")
        g.setWordWrap(True)
        g.setStyleSheet("color:#8d8d8d;")
        root = QWidget()
        v = QVBoxLayout(root)
        v.addWidget(g)
        v.addWidget(self.t, 1)
        v.addWidget(orig)
        self.setCentralWidget(root)

    def refresh(self):
        if not self.isVisible():
            return
        self._filling = True
        runs = self.main.runs
        self.t.setRowCount(len(runs))
        for i, r in enumerate(runs):
            self.t.setItem(i, 0, _item(r.source, GREY))
            self.t.setItem(i, 1, _item(r.name, WHITE if r.name != r.source else GREY, True))
            self.t.setItem(i, 2, _item(r.legend(), WHITE if r.label else GREY, True))
        self._filling = False

    def _edited(self, it):
        run = self.main.runs[it.row()]
        if it.column() == 1:
            self.main.rename(run, it.text())
        elif it.column() == 2:
            self.main.relabel(run, it.text())
        self.refresh_later()             # back to grey, if it follows again


class RegionPanel(_Window):
    """The selected region on its own (it follows the selection)."""

    def __init__(self, main):
        super().__init__(main, "Spikeless — region", (440, 250), table=False)
        self.head = QLabel()
        self.head.setWordWrap(True)
        self.name = QLineEdit()
        self.name.editingFinished.connect(lambda: self._set("name", self.name.text().strip()))
        self.under = QComboBox()
        self.under.addItems(["the background", "a straight line between its ends"])
        self.under.setToolTip("What its net counts are above: the run's background, or — for "
                              "a peak on another's tail — a line from its start to its end")
        self.under.activated.connect(lambda i: self._set("under", ("background", "line")[i]))
        self.note = QLineEdit()
        self.note.setPlaceholderText("why it was drawn or moved, if it matters")
        self.note.editingFinished.connect(lambda: self._set("note", self.note.text()))
        self.color = ColorButton("#808080", lambda: self._set("color", self.color.color))
        self.label = QCheckBox("Labelled on the figure")
        self.label.toggled.connect(lambda on: self._set("label", on))
        self.form = QWidget()
        f = QFormLayout(self.form)
        f.setContentsMargins(0, 0, 0, 0)
        for text, wdg in (("Name", self.name), ("Under it", self.under), ("Note", self.note),
                          ("Colour", self.color)):
            f.addRow(text, wdg)
        f.addRow(self.label)
        root = QWidget()
        v = QVBoxLayout(root)
        v.addWidget(self.head)
        v.addWidget(self.form)
        v.addStretch(1)
        guard_fields(root)
        self.setCentralWidget(root)

    def _set(self, key, val):
        if not self._filling:
            self.main.set_region(self.main.sel_region, key, val)

    def refresh(self):
        if not self.isVisible():
            return
        self._filling = True
        run, k = self.main.sel, self.main.sel_region
        ok = run is not None and 0 <= k < len(run.regions)
        self.form.setEnabled(ok)
        if ok:
            r, row = run.regions[k], self.main.results[run.id].rows[k]
            self.head.setText(f"<b>{row.name}</b> — {row.start:.2f}–{row.end:.2f} min · "
                              f"{run.name}")
            self.name.setText(r.name)
            self.name.setPlaceholderText(row.name)
            self.under.setCurrentIndex(1 if r.under == "line" else 0)
            self.note.setText(r.note)
            self.color.set_color(r.color or run.color)
            self.label.setChecked(r.label)
        else:
            self.head.setText("Select a region: in Regions, on the plot or in the results.")
            for wdg in (self.name, self.note):
                wdg.setText("")
        self._filling = False


class RegionsWindow(_Window):
    STATS = [c for c in COLUMNS if c[0] != "name"]

    def __init__(self, main):
        super().__init__(main, "Spikeless — regions", (1100, 360))
        heads = ["", "Region"] + [h for _, h, _ in self.STATS] + ["On figure", "Note"]
        self.t.setColumnCount(len(heads))
        self.t.setHorizontalHeaderLabels(heads)
        for c, (key, _, _) in enumerate(self.STATS, start=2):
            self.t.horizontalHeaderItem(c).setToolTip(HELP.get(key, ""))
        self.t.horizontalHeaderItem(0).setToolTip("Its colour: click to choose")
        self.t.horizontalHeaderItem(len(heads) - 2).setToolTip("Its label on the figure")
        self.t.horizontalHeader().setStretchLastSection(True)
        self.t.cellClicked.connect(self._clicked)
        self.what = QLabel()
        b = QPushButton("⧉ Copy")
        b.setToolTip("The table, to paste into Excel or Word")
        b.clicked.connect(lambda: copy_table(self._rows()))
        top = QHBoxLayout()
        top.addWidget(self.what, 1)
        top.addWidget(b)
        g = QLabel("Click a swatch to choose a region's colour; untick On figure to leave its "
                   "label off the figure; type a name or a note. Every measure is here, "
                   "whatever the report's columns.")
        g.setWordWrap(True)
        g.setStyleSheet("color:#8d8d8d;")
        root = QWidget()
        v = QVBoxLayout(root)
        v.addLayout(top)
        v.addWidget(self.t, 1)
        v.addWidget(g)
        self.setCentralWidget(root)

    def _rows(self):
        run = self.main.sel
        if run is None:
            return []
        res = self.main.results[run.id]
        return ([["Region"] + [h for _, h, _ in self.STATS] + ["Note"]]
                + [[row.name] + [f(row) for _, _, f in self.STATS] + [reg.note]
                   for reg, row in zip(run.regions, res.rows)])

    def refresh(self):
        if not self.isVisible():
            return
        self._filling = True
        run = self.main.sel
        regs = run.regions if run is not None else []
        self.what.setText(f"<b>{run.name}</b> — {len(regs)} region(s)" if run is not None
                          else "Select a run (Runs).")
        rows = self.main.results[run.id].rows if run is not None else []
        self.t.setRowCount(len(regs))
        last = self.t.columnCount() - 1
        for k, (reg, row) in enumerate(zip(regs, rows)):
            sw = _item("")
            sw.setBackground(QColor(reg.color or run.color))
            self.t.setItem(k, 0, sw)
            self.t.setItem(k, 1, _item(row.name, WHITE if reg.name else GREY, True))
            for c, (_, _, f) in enumerate(self.STATS, start=2):
                self.t.setItem(k, c, _item(f(row), right=True))
            on = _item("")
            on.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            on.setCheckState(Qt.Checked if reg.label else Qt.Unchecked)
            self.t.setItem(k, last - 1, on)
            self.t.setItem(k, last, _item(reg.note, edit=True))
        self.t.resizeColumnsToContents()
        self.t.setColumnWidth(0, 28)
        self._filling = False

    def _clicked(self, r, c):
        run = self.main.sel
        if c != 0 or run is None or r >= len(run.regions):
            return
        reg = run.regions[r]
        col = pick_color(self, reg.color or run.color)
        if col:
            self.main.set_region(r, "color", col)

    def _edited(self, it):
        run = self.main.sel
        k, c = it.row(), it.column()
        if run is None or k >= len(run.regions):
            return
        last = self.t.columnCount() - 1
        if c == 1:
            auto = self.main.results[run.id].rows[k].name
            name = it.text().strip()
            self.main.set_region(k, "name", "" if name == auto and not run.regions[k].name
                                 else name)
        elif c == last - 1:
            self.main.set_region(k, "label", it.checkState() == Qt.Checked)
        elif c == last:
            self.main.set_region(k, "note", it.text())
