"""Spikeless - the report: what was loaded, what was done to it, the peak tables, the plot.

One HTML text, built from the session as it stands, is both the preview and every format:
PDF and .odt are Qt's print of it, .md Qt's markdown of it, .html it with the plot inlined;
the workbook takes the same tables, a sheet each. The Report window picks the format and
the sections, saved with the options the moment they change.
"""

from __future__ import annotations

import base64
import datetime as _dt
from html import escape as esc
from io import BytesIO
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QPageSize, QPdfWriter, QShortcut, QTextDocument, \
    QTextDocumentWriter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .options import PREFS, save_prefs

# Peak-table columns (key, header, value(i, pk)): the same spec drives the report, the
# workbook and the peak exports, so what is shown is what is written.
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
SECTIONS = [("plot", "Plot", "The figure, as Export writes it"),
            ("datasets", "Datasets", "File, run date, molecule, radioisotope, conditions"),
            ("curves", "Curves", "Each curve, and how it, its spikes, baseline and peaks "
                                 "were made"),
            ("spikes", "Spikes", "Time and height of each spike found"),
            ("peaks", "Peak tables", "One per curve with peaks, with the columns ticked")]
FORMATS = [(".pdf", "PDF"), (".odt", "Document (.odt) — opens in Word and LibreOffice"),
           (".xlsx", "Excel workbook — a sheet per table"), (".md", "Markdown text"),
           (".html", "Web page")]
PLOT = "plot.png"                      # the plot's name inside the report
_NORM = {"pct_max": "% of max", "pct_total": "% of total"}


def peak_rows(cv):
    """Header + value rows of cv's peaks, in the columns ticked for the report."""
    cols = [(h, f) for k, h, f in PEAK_COLUMNS if PREFS["report_cols"].get(k)]
    return (tuple(h for h, _ in cols),
            [tuple(f(i, pk) for _, f in cols) for i, pk in enumerate(cv.peaks or [], 1)])


def curve_paths(ds):
    """(curve, its name after its ancestors': original › spikeless), in tree order."""
    def walk(c, trail):
        name = f"{trail} › {c.name}" if trail else c.name
        yield c, name
        for ch in c.children:
            yield from walk(ch, name)
    return list(walk(ds.root, ""))


def curve_lines(ds, cv) -> list[str]:
    """What the curve is, and how it and its parts were made: a sentence each."""
    how = cv.how
    if cv.kind == "original":
        out = [f"As loaded: {len(cv.y)} points, one every {ds.dt_s:g} s, "
               f"{cv.x[0]:.2f}–{cv.x[-1]:.2f} min."]
    else:
        out = [f"Made by: {how.get('curve') or cv.kind}."]
    if cv.has_spikes:
        out.append(f"Spikes: {len(cv.spike_indices())} found"
                   + (f" — {how['spikes']}" if how.get("spikes") else "") + ".")
    if cv.baseline is not None:
        out.append(f"Baseline: {how.get('baseline') or 'detected'}.")
    if cv.peaks:
        out.append(f"Peaks: {len(cv.peaks)}"
                   + (f" — {how['peaks']}" if how.get("peaks") else "") + ".")
    if cv.adjust.norm_mode in _NORM:
        out.append(f"Shown as {_NORM[cv.adjust.norm_mode]}.")
    return out


def _table(head, rows, border=1) -> str:
    h = "<tr>" + "".join(f"<th>{esc(c)}</th>" for c in head) + "</tr>" if head else ""
    return (f"<table border='{border}' cellspacing='0' cellpadding='3'>{h}"
            + "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>"
                      for r in rows) + "</table>")


def _spike_rows(cv):
    return [(str(i), f"{cv.x[k]:.2f}", f"{cv.y[k]:.0f}")
            for i, k in enumerate(cv.spike_indices(), 1)]


def html(datasets, plot_width_px: int | None = None) -> str:
    """The report as HTML. With plot_width_px, the plot is the image named PLOT."""
    on = PREFS["report_sections"]
    out = ["<h1>Radio-HPLC report</h1>",
           f"<p>{_dt.datetime.now():%Y-%m-%d %H:%M} · Spikeless {__version__}</p>"]
    if not datasets:
        out.append("<p>Nothing loaded.</p>")
    if on["plot"] and plot_width_px and datasets:
        out.append(f"<p><img src='{PLOT}' width='{plot_width_px}'></p>")
    for ds in datasets:
        out.append(f"<h2>{esc(ds.meta.name)}</h2>")
        if on["datasets"]:
            rows = [(k, v) for k, v in (("File", ds.meta.original_filename),
                                        ("Run", ds.run_datetime), ("Molecule", ds.meta.molecule),
                                        ("Radioisotope", ds.meta.radioisotope)) if v]
            out.append(_table(None, rows + [("Condition", c.text()) for c in ds.conditions],
                              border=0))
        for cv, path in curve_paths(ds):
            parts = []
            if on["curves"]:
                parts.append("<p>" + "<br>".join(esc(s) for s in curve_lines(ds, cv)) + "</p>")
            if on["spikes"] and cv.has_spikes:
                parts.append(_table(("Spike", "Time (min)", "Height (cps)"), _spike_rows(cv)))
            if on["peaks"] and cv.peaks:
                head, rows = peak_rows(cv)
                if head:
                    parts.append(_table(head, rows))
            if parts:
                out.append(f"<h3>{esc(path)}</h3>" + "".join(parts))
    return "".join(out)


def num(v):
    """A formatted cell back to a number for Excel (so columns stay summable); else text."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return v


def sheet_name(name, used):
    """A valid, unique (<=31 char) Excel sheet name."""
    s = "".join(c for c in str(name) if c not in '[]:*?/\\')[:31] or "Sheet"
    base, i = s, 1
    while s in used:
        suffix = f"_{i}"
        s = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(s)
    return s


def to_xlsx(datasets, path, png: bytes | None = None, width_px: int | None = None) -> None:
    """The report as a workbook: the datasets and curves on one sheet, the spikes on one,
    each peak table on its own, the plot on its own."""
    from openpyxl import Workbook

    on = PREFS["report_sections"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    used = {"Report"}
    ws.append(["Radio-HPLC report", f"{_dt.datetime.now():%Y-%m-%d %H:%M}",
               f"Spikeless {__version__}"])
    if on["datasets"] or on["curves"]:
        ws.append([])
        ws.append(["Dataset"] + (["File", "Run", "Molecule", "Radioisotope", "Conditions"]
                                 if on["datasets"] else []) + (["Curve", "About"]
                                                                if on["curves"] else []))
        for ds in datasets:
            info = [ds.meta.original_filename, ds.run_datetime, ds.meta.molecule,
                    ds.meta.radioisotope, "; ".join(c.text() for c in ds.conditions)]
            for cv, p in (curve_paths(ds) if on["curves"] else [(None, None)]):
                ws.append([ds.meta.name] + (info if on["datasets"] else [])
                          + ([p, " ".join(curve_lines(ds, cv))] if cv else []))
    if on["spikes"]:
        sp = wb.create_sheet(sheet_name("Spikes", used))
        sp.append(["Dataset", "Curve", "Spike", "Time (min)", "Height (cps)"])
        for ds in datasets:
            for cv, p in curve_paths(ds):
                for r in (_spike_rows(cv) if cv.has_spikes else []):
                    sp.append([ds.meta.name, p] + [num(c) for c in r])
    if on["peaks"]:
        for ds in datasets:
            for cv, p in curve_paths(ds):
                head, rows = peak_rows(cv)
                if cv.peaks and head:
                    pk = wb.create_sheet(sheet_name(cv.name, used))
                    pk.append([f"{ds.meta.name} — {p}"])
                    pk.append(list(head))
                    for r in rows:
                        pk.append([num(c) for c in r])
    if on["plot"] and png:
        from openpyxl.drawing.image import Image as XLImage
        img = XLImage(BytesIO(png))
        img.height, img.width = round(img.height * width_px / img.width), width_px
        wb.create_sheet(sheet_name("Plot", used)).add_image(img, "A1")
    wb.save(path)


def png_bytes(img) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


class ReportWindow(QMainWindow):
    """Pick the format and the sections, see the report, save it as one file."""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Spikeless — report")
        self.resize(1100, 760)
        side = QWidget()
        side.setFixedWidth(320)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 0, 0, 0)
        self.c_format = QComboBox()
        self.c_format.addItems([lab for _, lab in FORMATS])
        self.c_format.setToolTip("What Save report writes")
        self.c_format.activated.connect(self._format_set)
        v.addWidget(QLabel("<b>Format</b>"))
        v.addWidget(self.c_format)
        v.addSpacing(8)
        v.addWidget(QLabel("<b>Sections</b>"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setToolTip("Tick what goes in; the peak tables' columns are under them")
        self.tree.itemChanged.connect(self._ticked)
        v.addWidget(self.tree, 1)
        h = QHBoxLayout()
        b = QPushButton("Copy")
        b.setToolTip("The report's text and tables, to paste into a document (the plot has "
                     "its own Copy)")
        b.clicked.connect(self.copy)
        h.addWidget(b)
        b = QPushButton("Save report…")
        b.setToolTip("Ctrl+S")
        b.clicked.connect(self.save)
        h.addWidget(b, 1)
        v.addSpacing(8)
        v.addLayout(h)
        QShortcut(QKeySequence.Save, self, self.save)
        self.view = QTextBrowser()
        root = QWidget()
        hl = QHBoxLayout(root)
        hl.addWidget(side)
        hl.addWidget(self.view, 1)
        self.setCentralWidget(root)
        self.statusBar()
        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self.sync()

    def sync(self):
        """Format and ticks from the options (they may have been reset or imported)."""
        exts = [e for e, _ in FORMATS]
        fmt = PREFS["report_format"]
        self.c_format.setCurrentIndex(exts.index(fmt) if fmt in exts else 0)
        self.tree.blockSignals(True)
        self.tree.clear()
        for key, label, tip in SECTIONS:
            it = self._tick(self.tree, label, "report_sections", key)
            it.setToolTip(0, tip)
            if key == "peaks":
                for ck, head, _ in PEAK_COLUMNS:
                    self._tick(it, "# (row number)" if ck == "num" else head, "report_cols", ck)
                it.setExpanded(True)
        self.tree.blockSignals(False)
        self.refresh_later()

    @staticmethod
    def _tick(parent, label, key, sub):
        it = QTreeWidgetItem(parent, [label])
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Checked if PREFS[key][sub] else Qt.Unchecked)
        it.setData(0, Qt.UserRole, (key, sub))
        return it

    def _ticked(self, it, _col=0):
        key, sub = it.data(0, Qt.UserRole)
        PREFS[key][sub] = it.checkState(0) == Qt.Checked
        save_prefs()
        self.refresh()

    def _format_set(self, i):
        PREFS["report_format"] = FORMATS[i][0]
        save_prefs()

    def open(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh_later(self):
        """After a change to the data or the plot: redrawn once things settle, if shown."""
        if self.isVisible():
            self._timer.start()

    def _plot(self):
        """(QImage, width in px at 96 dpi) of the plot as the report shows it, or (None, None)."""
        if not (PREFS["report_sections"]["plot"] and self.main.datasets):
            return None, None
        fig = self.main._export_fig()
        return self.main._render_qimage(fig, 300), round(fig.get_figwidth() * 96)

    def refresh(self):
        img, w = self._plot()
        if img is not None:
            self.view.document().addResource(QTextDocument.ImageResource, QUrl(PLOT), img)
        sb = self.view.verticalScrollBar()
        pos = sb.value()
        self.view.setHtml(html(self.main.datasets, w))
        sb.setValue(min(pos, sb.maximum()))

    def copy(self):
        text = html(self.main.datasets)
        doc = QTextDocument()
        doc.setHtml(text)
        md = QMimeData()
        md.setHtml(text)
        md.setText(doc.toMarkdown())
        QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage("Copied (the plot has its own Copy)", 5000)

    def write(self, path: Path) -> None:
        ext = path.suffix.lower()
        img, w = self._plot()
        if ext == ".xlsx":
            return to_xlsx(self.main.datasets, path, png_bytes(img) if img else None, w)
        text = html(self.main.datasets, w)
        if ext == ".html":
            if img is not None:
                b64 = base64.b64encode(png_bytes(img)).decode("ascii")
                text = text.replace(f"src='{PLOT}'", f"src='data:image/png;base64,{b64}'")
            path.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>"
                            f"Radio-HPLC report</title></head><body>{text}</body></html>",
                            encoding="utf-8")
            return
        doc = QTextDocument()
        if img is not None:
            doc.addResource(QTextDocument.ImageResource, QUrl(PLOT), img)
        doc.setHtml(text)
        if ext == ".pdf":
            pdf = QPdfWriter(str(path))
            pdf.setPageSize(QPageSize(QPageSize.A4))
            doc.print_(pdf)
        elif ext == ".md":
            md = doc.toMarkdown()
            if img is not None:                       # the plot beside it, as <name>_plot.png
                beside = path.with_name(f"{path.stem}_plot.png")
                beside.write_bytes(png_bytes(img))
                md = md.replace(f"]({PLOT})", f"]({beside.name})")
            path.write_text(md, encoding="utf-8")
        elif not QTextDocumentWriter(str(path), b"ODF").write(doc):
            raise OSError(f"could not write {path}")

    def save(self):
        ext, lab = FORMATS[self.c_format.currentIndex()]
        m = self.main
        stem = m._session_path.stem if m._session_path else \
            (m.datasets[0].meta.name if m.datasets else "spikeless")
        stem = "".join("_" if c in '\\/:*?"<>|' else c for c in stem)
        path, _ = QFileDialog.getSaveFileName(self, "Save report", str(m._dir / f"{stem}_report"
                                                                        f"{ext}"),
                                              f"{lab} (*{ext})")
        if not path:
            return
        path = Path(path)
        if not path.name.lower().endswith(ext):       # not with_suffix: names carry dots
            path = path.with_name(path.name + ext)
        try:
            self.write(path)
        except OSError as e:
            QMessageBox.warning(self, "Spikeless", f"Could not write the report:\n{e}")
            return
        self.statusBar().showMessage(f"Written to {path}", 6000)
        m.log(f"Report saved to {path}")
