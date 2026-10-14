"""Headless smoke test for the Spikeless UI. QT_QPA_PLATFORM=offscreen.

Drives one synthetic GINA export through the whole chain the way a click would:
load -> detect spikes -> baseline -> peaks -> decay, then report (every format), CSV export,
undo / redo, Del, a session saved and opened again, and the Options window.
Run it after touching app.py:  python misc/smoke_test.py
"""
import os, tempfile, time, zipfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox

from spikeless import options, report, session
from spikeless.adjust import HALF_LIFE_S
from spikeless.app import MainWindow

TMP = Path(tempfile.gettempdir())
options.OPTIONS_FILE = TMP / "_spikeless_smoke_options.json"   # the shipped defaults,
options.OPTIONS_FILE.unlink(missing_ok=True)                    # not the user's file

# ---- a GINA export with a sloping baseline, two peaks and three single-point spikes ----
n, dt = 600, 1.0
t = np.arange(n) * dt
y = 50 + 0.05 * t                                   # drift, so the baseline step has work to do
for centre, height, width in ((150, 900, 12), (380, 400, 18)):
    y += height * np.exp(-0.5 * ((t - centre) / width) ** 2)
y += np.random.default_rng(7).normal(0, 3, n)       # seeded: the assertions below are fixed
spike_at = [60, 250, 500]
y[spike_at] += 4000

lines = ["Smoke Run, 07/07/2026 14:17", '"Time, s"\t"Taux comptage du canal A, cps"']
lines += ['"%02d\\"00"\t"%s"' % (i, ("%.3f" % v).replace(".", ",")) if i < 60 else
          '"%02d\'%02d"\t"%s"' % (i // 60, i % 60, ("%.3f" % v).replace(".", ","))
          for i, v in enumerate(y)]
src = os.path.join(tempfile.gettempdir(), "spikeless_smoke.txt")
open(src, "wb").write(("\n".join(lines) + "\n").encode("cp1252"))

app = QApplication([])
w = MainWindow()
assert not w.datasets, "starts empty"

def pump(ms):
    """Let the queued half of an action story (the ones behind a delay) actually run."""
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)

# ---- load ----
w._load(src)
assert len(w.datasets) == 1, f"expected 1 dataset, got {len(w.datasets)}"
ds = w.datasets[0]
root = ds.root
assert ds.meta.name == "Smoke Run", ds.meta.name
assert ds.run_datetime == "07/07/2026 14:17", ds.run_datetime
assert len(root.y) == n and abs(ds.dt_s - 1.0) < 1e-9, (len(root.y), ds.dt_s)
assert w.data_tree.topLevelItemCount() == 1, "the dataset did not reach the tree"
assert w._sel_curve()[1] is root, "loading should select the new curve"

# ---- spikes: the story detects, flashes the overlay, then swaps to the clean curve ----
w._run_feature("spikes")
assert root.has_spikes, "the three planted spikes were not found"
found = set(root.spike_indices().tolist())
assert found == set(spike_at), f"wrong spikes: {sorted(found)}"
clean = next(c for c in root.children if c.kind == "spikeless")
assert abs(clean.y[250] - y[250]) > 3000, "the spikeless curve still carries the spike"
assert clean.y[150] > 800, "removal flattened the real peak"
assert root.spikes_group_shown and not clean.shown, "the overlay comes first, on its own"
pump(900)                                          # the story has a 500 ms delay in the middle
assert clean.shown and not root.shown and not root.spikes_group_shown, \
    "after the pause the clean curve should be the one on screen, alone"

# ---- baseline on the clean curve ----
w._select_id(("curve", ds.id, clean.id))
w._run_feature("baseline")
assert clean.baseline is not None, "no baseline"
corr = next(c for c in clean.children if c.kind == "baseline-corrected")
assert abs(float(np.median(corr.y))) < 30, f"baseline not removed: {np.median(corr.y)}"

# ---- peaks ----
w._select_id(("curve", ds.id, corr.id))
w._run_feature("peaks")
assert corr.peaks and len(corr.peaks) == 2, f"expected 2 peaks, got {corr.peaks and len(corr.peaks)}"
rts = sorted(p.rt for p in corr.peaks)
assert abs(rts[0] - 150 / 60) < 0.2 and abs(rts[1] - 380 / 60) < 0.2, rts
assert abs(sum(p.pct for p in corr.peaks) - 100) < 0.5, "percentages must add up"
big = max(corr.peaks, key=lambda p: p.auc)
assert abs(big.rt - 150 / 60) < 0.2 and big.pct > 50, "the tall peak should dominate the AUC"

# ---- decay correction grows the tail, never the reference point ----
ds.half_life_s = HALF_LIFE_S["¹⁸F"]
w._run_feature("decay")
dec = next(c for c in corr.children if "decay" in c.kind)
assert abs(dec.y[0] - corr.y[0]) < 1e-6, "t=0 is the reference: it must not move"
assert dec.y[-1] > corr.y[-1], "later samples should be scaled up, not down"

# ---- each processed curve says how it was made ----
assert "Hampel" in root.how["spikes"] and "Hampel" in clean.how["curve"], (root.how, clean.how)
assert clean.how.get("baseline") and corr.how["curve"].startswith("baseline of"), corr.how
assert "prominence" in corr.how["peaks"], corr.how
assert "decay-corrected" in dec.how["curve"], dec.how

# ---- the report: the preview and every format carry the same numbers ----
rep = report.html(w.datasets)
assert "Smoke Run" in rep and "Spikes: 3 found" in rep and "Peaks: 2" in rep, rep[:600]
assert "Hampel" in rep, "the report does not say how the spikes were found"
w._report()
rw = w.report_win
assert "Smoke Run" in rw.view.toPlainText(), "the preview is empty"
for ext in (".pdf", ".odt", ".xlsx", ".md", ".html"):
    out = TMP / f"spikeless_smoke_report{ext}"
    rw.write(out)
    assert out.stat().st_size > 1000, (ext, out.stat().st_size)
assert f"{rts[0]:.2f}" in (TMP / "spikeless_smoke_report.md").read_text(encoding="utf-8")
assert (TMP / "spikeless_smoke_report_plot.png").exists(), "the markdown's plot is not beside it"
assert any(n.startswith("Pictures/") for n in
           zipfile.ZipFile(TMP / "spikeless_smoke_report.odt").namelist()), "no plot in the .odt"
assert "data:image/png;base64" in (TMP / "spikeless_smoke_report.html").read_text("utf-8")
from openpyxl import load_workbook
wb = load_workbook(TMP / "spikeless_smoke_report.xlsx")
assert "Plot" in wb.sheetnames and wb["Plot"]._images, wb.sheetnames
pk = wb[next(n for n in wb.sheetnames if "baseline" in n)]
head = [c.value for c in pk[2]]
assert pk.cell(3, head.index("Rt (min)") + 1).value == float(f"{rts[0]:.2f}"), list(pk.values)

# a section unticked in the window leaves the report, and the choice is saved
import json
from PySide6.QtCore import Qt
tables = next(rw.tree.topLevelItem(i) for i in range(rw.tree.topLevelItemCount())
              if rw.tree.topLevelItem(i).text(0) == "Peak tables")
tables.setCheckState(0, Qt.Unchecked)
assert "Rt (min)" not in report.html(w.datasets) and "Rt (min)" not in rw.view.toPlainText()
assert json.loads(options.OPTIONS_FILE.read_text("utf-8"))["report_sections"]["peaks"] is False
tables.setCheckState(0, Qt.Checked)

# ---- CSV carries the report's numbers ----
csv = os.path.join(tempfile.gettempdir(), "spikeless_smoke_peaks.csv")
assert w._write_peaks_csv(csv, corr) == 2
rows = [r.split(",") for r in open(csv, encoding="utf-8").read().splitlines()]
assert len(rows) == 3, rows                         # header + one line per peak
rt_col = rows[0].index("Rt (min)")
assert rows[1][rt_col] == f"{rts[0]:.2f}", (rows[1], rts)


# ---- undo says what it took back, and takes back exactly that; redo brings it back ----
def decay_kids():
    c = next(c for c in w.datasets[0].root.walk() if c.kind == "baseline-corrected")
    return [k for k in c.children if "decay" in k.kind]


w._undo()
assert w.log_view.toPlainText().rstrip().endswith("Undone: Apply decay."), \
    w.log_view.toPlainText()[-120:]
assert not decay_kids(), "the decay curve survived undo"
w._redo()
assert w.log_view.toPlainText().rstrip().endswith("Redone: Apply decay.")
assert len(decay_kids()) == 1, "redo did not bring the decay curve back"
w._undo()
ds = w.datasets[0]                                  # undo restores a deep copy: re-find everything
corr2 = next(c for c in ds.root.walk() if c.kind == "baseline-corrected")
assert not decay_kids() and len(corr2.peaks) == 2, "undo went one step too far"

# ---- Del removes what ✖ removes, undoably; the original curve has no ✖ ----
w._select_id(("peaks", ds.id, corr2.id))
w._delete_selected()
assert w.datasets[0].root.find(corr2.id).peaks is None, "Del did not remove the peaks"
w._undo()
assert len(w.datasets[0].root.find(corr2.id).peaks) == 2, "undo did not bring the peaks back"
w._select_id(("curve", ds.id, ds.root.id))
w._delete_selected()
assert len(w.datasets) == 1, "Del removed the dataset through its original curve"

# ---- the export-area border shows on screen but is never rendered into an export ----
from matplotlib.patches import Rectangle
assert options.PREFS["export_border"]["on"], "border option off — the next check proves nothing"


def _frames(fig):
    return [a for a in fig.artists if isinstance(a, Rectangle)]


assert len(_frames(w._fig)) == 1, "screen figure lost its export-area guide"
assert _frames(w._export_fig()) == [], "the guide leaked into the exported/copied figure"

# ---- a fixed total size drives the plot area: the field greys out and reports the result ----
d = w.d
assert d["w_mm"].isEnabled() and d["h_mm"].isEnabled(), "plot size not editable while total is Auto"
d["tot_w_auto"].setChecked(False)
d["tot_w"].setValue(200.0)
assert not d["w_mm"].isEnabled(), "plot width still editable under a fixed total"
assert d["h_mm"].isEnabled(), "plot height greyed out by a fixed total WIDTH"
shown = d["w_mm"].value()
real = w._fig.plot_area_mm[0]
assert abs(shown - real) <= 0.51, (shown, real)   # the mm fields show whole mm, like Total does
assert shown < 200.0, (shown,)                      # the label margins come out of the total
d["tot_w_auto"].setChecked(True)
assert d["w_mm"].isEnabled(), "plot width stayed grey after going back to Auto"

# ---- zoomed in, editing the plot keeps it where it is (it crept 1 px down-right per redraw) ----
v = w.plot_view
v.scale(1.5, 1.5)
v._zoomed = True


def _at():
    return v.mapFromScene(v._item.sceneBoundingRect()).boundingRect().topLeft()


before = _at()
for a in (0.5, 0.6, 0.7, 0.8, 0.9):
    d["bg_a"].setValue(a)
assert _at() == before, (before, _at())
d["h_mm"].setValue(60.0)
d["h_mm"].setValue(40.0)
assert (_at() - before).manhattanLength() <= 1, (before, _at())
v._fit()

# ---- a session comes back as it was saved, plot options included ----
w.d["h_mm"].setValue(55.0)
ses = TMP / "spikeless_smoke.spikeless"
ses.write_text(session.dumps(w.datasets, w.plot_opts), encoding="utf-8")
names = [c.name for c in w.datasets[0].root.walk()]
w.d["h_mm"].setValue(40.0)
w._remove_node(("dataset", w.datasets[0].id))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)   # "replace?" — yes
w._load(src)                                       # something for the session to replace
w._open_session(str(ses))
assert [c.name for c in w.datasets[0].root.walk()] == names, "the curve tree changed"
assert len(next(c for c in w.datasets[0].root.walk() if c.peaks).peaks) == 2
assert w.plot_opts.plot_h_mm == 55.0 and w.d["h_mm"].value() == 55.0, "plot options lost"
assert ses.name in w.windowTitle()
w._undo()
assert w.datasets[0].root.children == [], "undo did not give back what the session replaced"

# ---- the Options window: saved as changed, followed at once, reset ----
from PySide6.QtWidgets import QCheckBox, QPushButton, QTableWidget
from spikeless.adjust import lookup_half_life_s
w._options("Screen")
ow = w.options_win
assert ow.topics.currentItem().text() == "Screen"
next(c for c in ow.pages.currentWidget().findChildren(QCheckBox)
     if c.text() == "Checkered").setChecked(False)
assert w.plot_view._bg.checkered is False, "the plot did not follow the option"
assert json.loads(options.OPTIONS_FILE.read_text("utf-8"))["background"]["checkered"] is False
w._options("Processing")
next(c for c in ow.pages.currentWidget().findChildren(QCheckBox)
     if c.text() == "Apply decay").setChecked(True)
assert any(b.text() == "Apply decay" for b in w._proc_body.findChildren(QPushButton))
w._options("Isotopes")
t = ow.pages.currentWidget().findChildren(QTableWidget)[0]
t.item(0, 1).setText("7")
assert lookup_half_life_s(t.item(0, 0).text()) == 7 * 3600, "the isotope table was not taken"
ow._apply(None)                                     # Reset to defaults
from PySide6.QtCore import QEvent
QApplication.sendPostedEvents(None, QEvent.DeferredDelete)   # the old buttons, gone
assert w.plot_view._bg.checkered and lookup_half_life_s("⁹⁹ᵐTc") == 6.00718 * 3600
assert not any(b.text() == "Apply decay" for b in w._proc_body.findChildren(QPushButton))

w.close()
for f in [src, csv, ses, options.OPTIONS_FILE, TMP / "spikeless_smoke_report_plot.png"] + \
        [TMP / f"spikeless_smoke_report{e}" for e in (".pdf", ".odt", ".xlsx", ".md", ".html")]:
    os.unlink(f)
print("spikeless smoke OK")
