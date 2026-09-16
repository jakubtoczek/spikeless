"""Headless smoke test for the Spikeless UI. QT_QPA_PLATFORM=offscreen.

Drives one synthetic GINA export through the whole chain the way a click would:
load -> detect spikes -> baseline -> peaks -> decay, then report, CSV export and undo.
Run it after touching app.py:  python misc/smoke_test.py
"""
import os, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from spikeless.adjust import ISOTOPE_HL_S
from spikeless.app import MainWindow

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
ds.half_life_s = ISOTOPE_HL_S["¹⁸F"]
w._run_feature("decay")
dec = next(c for c in corr.children if "decay" in c.kind)
assert abs(dec.y[0] - corr.y[0]) < 1e-6, "t=0 is the reference: it must not move"
assert dec.y[-1] > corr.y[-1], "later samples should be scaled up, not down"

# ---- report and CSV carry the same numbers ----
w._update_report()
rep = w._report_text
assert "Smoke Run" in rep and "3 spikes" in rep and "2 peaks" in rep, rep[:400]
csv = os.path.join(tempfile.gettempdir(), "spikeless_smoke_peaks.csv")
assert w._write_peaks_csv(csv, [(ds, corr)], "one") == 2
rows = [r.split(",") for r in open(csv, encoding="utf-8").read().splitlines()]
assert len(rows) == 3, rows                         # header + one line per peak
rt_col = rows[0].index("Rt (min)")                  # which columns are on is a saved preference
assert rows[1][rt_col] == f"{rts[0]:.2f}", (rows[1], rts)

# ---- undo says what it took back, and takes back exactly that ----
w._undo()
assert w.log_view.toPlainText().rstrip().endswith("Undone: Apply decay."), \
    w.log_view.toPlainText()[-120:]
ds = w.datasets[0]                                  # undo restores a deep copy: re-find everything
corr2 = next(c for c in ds.root.walk() if c.kind == "baseline-corrected")
assert not any("decay" in c.kind for c in corr2.children), "the decay curve survived undo"
assert len(corr2.peaks) == 2, "undo went one step too far"

# ---- removing a node is undoable too ----
w._select_id(("curve", ds.id, corr2.id))
w._remove_node(("peaks", ds.id, corr2.id))
assert w.datasets[0].root.find(corr2.id).peaks is None, "peaks not removed"
w._undo()
assert len(w.datasets[0].root.find(corr2.id).peaks) == 2, "undo did not bring the peaks back"

os.unlink(src); os.unlink(csv)
print("spikeless smoke OK")
