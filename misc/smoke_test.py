"""Headless smoke test for the Spikeless UI. QT_QPA_PLATFORM=offscreen.

Drives a synthetic GINA export through the four steps the way the mouse would — spikes
excluded on load and one put back, the background three ways, regions found, drawn, moved
and removed, a shared edge, decay, method names — then the results table, the report in every
format, the figure, a session saved and opened again, the Options window, undo / redo; and the
reference values on the example runs in C:\\Code\\Spikeless\\data when that folder is there.
Run it after touching anything:  python misc/smoke_test.py
"""
import json
import os
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QMessageBox,  # noqa: E402
                               QTableWidget)

from spikeless import figure, options, report, session  # noqa: E402
from spikeless.adjust import decay_on, lookup_half_life_s  # noqa: E402

TMP = Path(tempfile.gettempdir())
options.OPTIONS_FILE = TMP / "_spikeless_smoke_options.json"   # the shipped defaults,
options.OPTIONS_FILE.unlink(missing_ok=True)                    # not the user's file
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from spikeless.app import MainWindow  # noqa: E402

# ---- a GINA export: 7 cps background, two peaks, three single-point spikes (one on a peak) ----
n = 900
t = np.arange(n, dtype=float)
lam = 7 + 1500 * np.exp(-0.5 * ((t - 480) / 7) ** 2) + 120 * np.exp(-0.5 * ((t - 200) / 8) ** 2)
y = np.random.default_rng(7).poisson(lam).astype(float)   # seeded: the assertions are fixed
spike_at = [100, 476, 700]                                # 476: on the big peak's rising edge
y[spike_at] += 4000
lines = ["Interval Values Smoke Run, 07/07/2026 14:17", '"Time, s"\t"Taux comptage du canal A, cps"']
lines += ['"%02d\\"00"\t"%s"' % (i, ("%.3f" % v).replace(".", ",")) if i < 60 else
          '"%02d\'%02d"\t"%s"' % (i // 60, i % 60, ("%.3f" % v).replace(".", ","))
          for i, v in enumerate(y)]
src = TMP / "spikeless_smoke.txt"
src.write_bytes(("\n".join(lines) + "\n").encode("cp1252"))

app = QApplication([])
w = MainWindow()
assert not w.runs, "starts empty"


def last_log():
    return w.log_view.toPlainText().rstrip().splitlines()[-1]


# ---- ① load: spikes excluded at once, the "Interval Values" prefix dropped ----
w._load(str(src))
run = w.sel
assert len(w.runs) == 1 and run.name == "Smoke Run", run.name
assert run.spike_list() == spike_at, run.spike_list()
assert "3 spike(s) excluded" in w.log_view.toPlainText()
assert len(run.sha256) == 64
assert w.spike_list.count() == 3 and w.step["spikes"]._btn.text() == "② Spikes — 3 excluded"

# ---- ④ Find peaks: both peaks, % of total with the outside row adding to 100 ----
w._find()
res = w.results[run.id]
assert len(res.rows) == 2, [(r.start, r.end) for r in res.rows]
small, big = res.rows
assert abs(small.rt - 200 / 60) < 0.05 and abs(big.rt - 8.0) < 0.05, (small.rt, big.rt)
assert abs(sum(r.pct for r in res.rows) + 100 * res.outside / res.total - 100) < 1e-9
true_big = 1500 * 7 * np.sqrt(2 * np.pi)
assert abs(big.net - true_big) < 3 * big.unc + 0.02 * true_big, (big.net, true_big)
assert big.spikes == 1 and big.net_with_spikes > big.net + 2000, big
assert abs(res.background - 7) < 0.5, res.background
assert w.table.rowCount() == 4, w.table.rowCount()     # 2 regions + outside + total
heads = [w.table.horizontalHeaderItem(c).text() for c in range(w.table.columnCount())]
assert heads[:1] == ["Region"] and "% of total" in heads and "Net counts" in heads, heads

# ---- ② a spike put back is back; the list's tick is the switch; undo ----
it = w.spike_list.item(1)                                  # the one on the big peak
it.setCheckState(Qt.Unchecked)
assert run.kept == [476] and run.trace()[476] == y[476], "unticking did not put it back"
assert w.results[run.id].rows[1].net > big.net + 2000, "the area did not take the spike back"
w._undo_step()
run = w.sel
assert run.kept == [] and last_log() .endswith("Undone: keep the spike at 7.93 min.")
w._redo_step()
assert w.sel.kept == [476]
w._undo_step()
run = w.sel

# ---- ② the threshold: higher finds fewer, undo restores ----
w.sens.setValue(30)                                         # 15 σ
assert run.spike_params.n_sigma == 15 and len(run.spike_list()) == 3   # 4000 cps: still spikes
w._undo_step()
run = w.sel
assert run.spike_params.n_sigma == 5

# ---- ③ background: a stretch, a drift, back to auto ----
w._stretch(0.5, 1.5)
run = w.sel
sel = (run.x >= 0.5) & (run.x <= 1.5)
assert run.bg_mode == "stretch" and abs(w.results[run.id].background
                                        - run.trace()[sel].mean()) < 1e-9
w.bg_radio["drift"].setChecked(True)
assert run.bg_mode == "drift" and "SNIP" in w.results[run.id].background_how
w.bg_radio["auto"].setChecked(True)
assert run.bg_mode == "auto"

# ---- ④ drawing: snapped, clipped against neighbours, n.d. on noise; edges; Del ----
r0, r1 = run.regions
w._drawn(11.0, 11.6, False)                                 # noise only
k = w.sel_region
row = w.results[run.id].rows[k]
assert run.regions[k].how == "drawn" and "n.d." in row.flags and row.pct is None, row
w._delete_region()
assert len(run.regions) == 2
w._drawn(r1.start - 0.3, r1.start + 0.2, True)              # overlaps the big one: cut at its start
k = w.sel_region
assert abs(run.regions[k].end - r1.start) < 1e-9, (run.regions[k], r1)
# that edge is now shared: moving it moves both
shared = run.regions[k].end
w._edge_moved(k, "end", shared - 0.05, True)
assert abs(run.regions[k].end - (shared - 0.05)) < 1e-9
assert abs(run.regions[k + 1].start - (shared - 0.05)) < 1e-9
assert run.regions[k + 1].how == "moved", run.regions[k + 1].how
w._undo_step()
w._undo_step()                                              # the edge, then the drawn region
run = w.sel
assert len(run.regions) == 2 and run.regions[1].how == "auto"
# ← → nudge the last-touched edge one point
w.canvas._edge = (1, "end")
end0 = run.regions[1].end
w.canvas.keyPressEvent(type("K", (), {"key": lambda self: Qt.Key_Right})())
assert abs(w.sel.regions[1].end - end0 - 1 / 60) < 1e-9
w._undo_step()
run = w.sel
# a region's line under it, its note, its name typed in the table
w.sel_region = 1
w.refresh()
w.r_under.setCurrentIndex(1)
w.r_under.activated.emit(1)
assert run.regions[1].under == "line"
w._undo_step()
run = w.sel
w.table.item(1, 0).setText("product")
assert run.regions[1].name == "product" and w.results[run.id].rows[1].name == "product"

# ---- methods name regions; decay per isotope ----
options.PREFS["methods"] = [["M", "free", 3.0, 3.6], ["M", "product", 7.5, 8.5]]
run.method = "M"
w.refresh()
assert w.results[run.id].rows[0].name == "free" and w.results[run.id].rows[0].named
base = run.trace()
options.PREFS["isotopes"][6][2] = True                      # ⁶⁸Ga: decay-corrected
options.set_half_lives(options.PREFS["isotopes"])
run.isotope = "⁶⁸Ga"
w.refresh()
k = run.trace()[600] / base[600]                            # 10 min after the run start
assert run.decayed() and abs(k - 2 ** (10 / (1.12782 * 60))) < 1e-9, k
assert "decay-corrected" in w.summary.text()
options.PREFS["isotopes"][6][2] = False
options.set_half_lives(options.PREFS["isotopes"])
w.refresh()
assert not run.decayed()

# ---- the report: preview and every format carry the same numbers ----
rep = report.html(w)
assert "Smoke Run" in rep and "Spikes: 3 excluded" in rep and "Hampel" in rep, rep[:800]
assert "with its excluded spike(s) kept" in rep, "the spike-kept area is missing"
w._report()
rw = w.report_win
assert "Smoke Run" in rw.view.toPlainText()
for ext in (".pdf", ".odt", ".xlsx", ".md", ".html"):
    out = TMP / f"spikeless_smoke_report{ext}"
    rw.write(out)
    assert out.stat().st_size > 1000, (ext, out.stat().st_size)
rt = f"{w.results[run.id].rows[1].rt:.2f}"
assert rt in (TMP / "spikeless_smoke_report.md").read_text(encoding="utf-8")
assert (TMP / "spikeless_smoke_report_plot.png").exists(), "the markdown's figure is not beside it"
assert any(nm.startswith("Pictures/") for nm in
           zipfile.ZipFile(TMP / "spikeless_smoke_report.odt").namelist()), "no figure in the .odt"
assert "data:image/png;base64" in (TMP / "spikeless_smoke_report.html").read_text("utf-8")
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(TMP / "spikeless_smoke_report.xlsx")
assert {"Report", "Results", "Spikes", "Figure"} <= set(wb.sheetnames), wb.sheetnames
rs = list(wb["Results"].values)
assert rs[0][:2] == ("Run", "Region") and rs[2][1] == "product", rs[:3]
assert rs[2][rs[0].index("Rt (min)")] == float(rt), rs[2]
assert len(list(wb["Spikes"].values)) == 4                  # header + 3 spikes
# a section unticked leaves the report and is saved; a column unticked leaves the table too
tree = rw.tree
results_item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).text(0) == "Results")
unc = next(results_item.child(i) for i in range(results_item.childCount())
           if results_item.child(i).text(0) == "± counts")
unc.setCheckState(0, Qt.Unchecked)
assert "± counts" not in report.html(w)
assert "± counts" not in [w.table.horizontalHeaderItem(c).text() for c in range(w.table.columnCount())]
assert json.loads(options.OPTIONS_FILE.read_text("utf-8"))["report_cols"]["unc"] is False
unc.setCheckState(0, Qt.Checked)

# ---- the figure: its size in mm, presets, copy ----
fig = figure.figure(w)
assert all(abs(a - b) < 0.5 for a, b in zip(fig.plot_area_mm, (80, 40))), fig.plot_area_mm
w._figure()
fw = w.figure_win
fw._preset(3)                                               # Slide
assert w.plot_opts.plot_w_mm == 160 and w.plot_opts.x.tick_font_size == 14
assert abs(figure.figure(w).plot_area_mm[0] - 160) < 0.5
figure.copy_figure(w)
assert not QApplication.clipboard().image().isNull(), "nothing on the clipboard"
texts = [t.get_text() for t in figure.figure(w).axes[0].texts]
assert any("product" in s for s in texts), texts            # named regions labelled
next(c for c in fw.side.widget().findChildren(QCheckBox)
     if c.text() == "Regions (shaded)").setChecked(False)
assert not figure.figure(w).axes[0].collections, "regions still shaded"
w.plot_opts.show_regions = True

# ---- a session comes back as it was saved ----
ses = TMP / "spikeless_smoke.spikeless"
ses.write_text(session.dumps(w.runs, w.plot_opts), encoding="utf-8")
before = [(r.start, r.end, r.name, r.how) for r in w.sel.regions]
w._remove_run()
assert not w.runs
w._load(str(src))                                           # something for it to replace
w._open_session(str(ses))
assert [(r.start, r.end, r.name, r.how) for r in w.sel.regions] == before
assert w.sel.method == "M" and w.plot_opts.plot_w_mm == 160 and ses.name in w.windowTitle()
w._undo_step()
assert w.sel.regions == [] and w.sel.name == "Smoke Run", "undo did not give back what was replaced"
w._redo_step()

# ---- the Options window: saved as changed, followed at once, reset ----
w._options("Isotopes")
ow = w.options_win
assert ow.topics.currentItem().text() == "Isotopes"
tab = ow.pages.currentWidget().findChildren(QTableWidget)[0]
tab.item(0, 1).setText("7")
assert lookup_half_life_s(tab.item(0, 0).text()) == 7 * 3600
tab.item(9, 2).setCheckState(Qt.Checked)                    # ¹⁷⁷Lu decay-corrected
assert decay_on("¹⁷⁷Lu")
w._options("Methods")
mt = ow.pages.currentWidget().findChildren(QTableWidget)[0]
assert mt.rowCount() == 2 and mt.item(1, 1).text() == "product"
ow._apply(None)                                             # Reset to defaults
QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
assert lookup_half_life_s("⁹⁹ᵐTc") == 6.00718 * 3600 and not decay_on("¹⁷⁷Lu")
assert options.PREFS["methods"] == [] and w.results[w.sel.id].rows[0].name.startswith("peak 1")

# ---- the example runs: reference values (devlog) ----
data = Path(__file__).resolve().parents[2] / "data"
if data.is_dir():
    def ref(stem):
        w._load(str(next(data.glob(f"Interval_Values_{stem}*.txt"))))
        w._find()
        return w.sel, w.results[w.sel.id]
    r, res = ref("HOPO-1")
    assert r.spike_list() == [587, 700] and len(res.rows) == 2, (r.spike_list(), res.rows)
    assert [round(x.pct, 1) for x in res.rows] == [14.3, 85.7], [x.pct for x in res.rows]
    r, res = ref("Imathera2")
    assert r.spike_list() == [778, 786], r.spike_list()
    imp = next(x for x in res.rows if abs(x.rt - 2.55) < 0.05)
    prod = next(x for x in res.rows if abs(x.rt - 7.90) < 0.05)
    assert abs(imp.pct - 2.2) < 0.15 and abs(prod.pct - 97.7) < 0.15, (imp.pct, prod.pct)
    r, res = ref("TestOnduleur")
    assert r.spike_list() == [1314, 4696, 5660] and res.rows == [] and not res.active

w.close()
for p in [src, ses, options.OPTIONS_FILE, TMP / "spikeless_smoke_report_plot.png"] + \
        [TMP / f"spikeless_smoke_report{e}" for e in (".pdf", ".odt", ".xlsx", ".md", ".html")]:
    p.unlink(missing_ok=True)
print("spikeless smoke OK")
