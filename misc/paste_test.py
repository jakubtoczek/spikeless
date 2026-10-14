"""Headless check of the Ctrl+V clipboard import path. Run: python misc/paste_test.py"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from spikeless import options  # noqa: E402
from spikeless.app import MainWindow  # noqa: E402

options.OPTIONS_FILE = Path(tempfile.gettempdir()) / "_spikeless_paste_options.json"
options.OPTIONS_FILE.unlink(missing_ok=True)                # the defaults, not the user's
QMessageBox.warning = staticmethod(lambda *a, **k: None)  # never block on a modal in a test

app = QApplication([])
w = MainWindow()

# the user's Prism paste: two columns, 1 Hz sampling written in minutes
QApplication.clipboard().setText("".join(f"{i / 60:.3f}\t{7 + i % 5}\n" for i in range(900)))
w._paste()
assert len(w.runs) == 1, len(w.runs)
r = w.runs[0]
assert r.name == "Clipboard 1", r.name
assert len(r.y) == 900, len(r.y)
assert abs(r.dt_s - 1.0) < 0.02, r.dt_s
assert 14.9 < r.x[-1] < 15.0, r.x[-1]
assert w.sel is r, "the pasted run is the one the steps act on"
assert any("minutes" in ln for ln in w._log_text().splitlines()), "unit not logged"

# pasting again adds another run, numbered per paste, in another colour
w._paste()
assert w.runs[1].name == "Clipboard 2", w.runs[1].name
assert w.runs[1].color != w.runs[0].color

# the same run in seconds is recognised and converted
QApplication.clipboard().setText("".join(f"{i} {7 + i % 5}\n" for i in range(900)))
w._paste()
assert abs(w.runs[2].dt_s - 1.0) < 1e-9, w.runs[2].dt_s
assert 14.9 < w.runs[2].x[-1] < 15.0, w.runs[2].x[-1]

# a shared-time-axis paste: one time column, three signal columns -> three runs, one undo
n = len(w.runs)
rows = ["Time\tctrl\tlow\thigh"]
rows += [f"{i / 60:.3f}\t{5 + i % 7}\t{40 + i % 11}\t{300 + i % 13}" for i in range(600)]
QApplication.clipboard().setText("\n".join(rows))
w._paste()
assert len(w.runs) == n + 3, len(w.runs)
assert [d.name for d in w.runs[n:]] == ["ctrl", "low", "high"], [d.name for d in w.runs[n:]]
w._undo_step()
assert len(w.runs) == n, "a multi-column paste needed more than one undo"

# a paired paste: time1,value1,time2,value2 of unequal length -> two runs on their own axes
rows = ["Tmin\trunA\tTsec\trunB"]
for i in range(400):
    b = f"{i}\t{200 + i % 9}" if i < 300 else "\t"
    rows.append(f"{i / 60:.3f}\t{5 + i % 7}\t{b}")
QApplication.clipboard().setText("\n".join(rows))
w._paste()
assert len(w.runs) == n + 2, len(w.runs)
a, b = w.runs[n], w.runs[n + 1]
assert (a.name, b.name) == ("runA", "runB"), (a.name, b.name)
assert len(a.y) == 400 and len(b.y) == 300, (len(a.y), len(b.y))
assert abs(b.x[-1] - 299 / 60) < 1e-9, b.x[-1]   # runB's seconds became minutes
assert any("time/value pairs" in ln for ln in w._log_text().splitlines()), "layout not logged"
w._undo_step()
assert len(w.runs) == n, "a paired paste needed more than one undo"

# junk on the clipboard must not create a run
QApplication.clipboard().setText("no numbers here")
w._paste()
assert len(w.runs) == n, len(w.runs)

# Ctrl+V inside a text field still pastes text, not a run
le = QLineEdit(w)
le.show()
le.setFocus()
QApplication.clipboard().setText("hello")
if QApplication.focusWidget() is le:
    w._paste()
    assert le.text() == "hello", le.text()
    assert len(w.runs) == n, len(w.runs)

options.OPTIONS_FILE.unlink(missing_ok=True)
print("paste smoke OK")
