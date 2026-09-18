"""Headless check of the Ctrl+V clipboard import path. Run: python misc/paste_test.py"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from spikeless.app import MainWindow

QMessageBox.warning = staticmethod(lambda *a, **k: None)  # never block on a modal in a test

app = QApplication([])
w = MainWindow()

# the user's Prism paste: two columns, 1 Hz sampling written in minutes
QApplication.clipboard().setText("".join(f"{i / 60:.3f}\t{7 + i % 5}\n" for i in range(900)))
w._paste()
assert len(w.datasets) == 1, len(w.datasets)
ds = w.datasets[0]
assert ds.meta.name == "Clipboard 1", ds.meta.name
assert len(ds.root.y) == 900, len(ds.root.y)
assert abs(ds.dt_s - 1.0) < 0.02, ds.dt_s
assert 14.9 < ds.root.x[-1] < 15.0, ds.root.x[-1]
assert any("minutes" in ln for ln in w._log_text().splitlines()), "unit not logged"

# pasting again adds another dataset, numbered per paste
w._paste()
assert w.datasets[1].meta.name == "Clipboard 2", w.datasets[1].meta.name

# the same run in seconds is recognised and converted
QApplication.clipboard().setText("".join(f"{i} {7 + i % 5}\n" for i in range(900)))
w._paste()
assert abs(w.datasets[2].dt_s - 1.0) < 1e-9, w.datasets[2].dt_s
assert 14.9 < w.datasets[2].root.x[-1] < 15.0, w.datasets[2].root.x[-1]

# a shared-time-axis paste: one time column, three signal columns -> three datasets, one undo
n = len(w.datasets)
rows = ["Time\tctrl\tlow\thigh"]
rows += [f"{i / 60:.3f}\t{5 + i % 7}\t{40 + i % 11}\t{300 + i % 13}" for i in range(600)]
QApplication.clipboard().setText("\n".join(rows))
w._paste()
assert len(w.datasets) == n + 3, len(w.datasets)
assert [d.meta.name for d in w.datasets[n:]] == ["ctrl", "low", "high"], \
    [d.meta.name for d in w.datasets[n:]]
w._undo()
assert len(w.datasets) == n, "a multi-column paste needed more than one undo"

# a paired paste: time1,value1,time2,value2 of unequal length -> two datasets on their own axes
rows = ["Tmin\trunA\tTsec\trunB"]
for i in range(400):
    b = f"{i}\t{200 + i % 9}" if i < 300 else "\t"
    rows.append(f"{i / 60:.3f}\t{5 + i % 7}\t{b}")
QApplication.clipboard().setText("\n".join(rows))
w._paste()
assert len(w.datasets) == n + 2, len(w.datasets)
a, b = w.datasets[n], w.datasets[n + 1]
assert (a.meta.name, b.meta.name) == ("runA", "runB"), (a.meta.name, b.meta.name)
assert len(a.root.y) == 400 and len(b.root.y) == 300, (len(a.root.y), len(b.root.y))
assert abs(b.root.x[-1] - 299 / 60) < 1e-9, b.root.x[-1]   # runB's seconds became minutes
assert any("time/value pairs" in ln for ln in w._log_text().splitlines()), "layout not logged"
w._undo()
assert len(w.datasets) == n, "a paired paste needed more than one undo"

# junk on the clipboard must not create a dataset
QApplication.clipboard().setText("no numbers here")
w._paste()
assert len(w.datasets) == n, len(w.datasets)

# Ctrl+V inside a text field still pastes text, not a dataset
le = QLineEdit(w)
le.show()
le.setFocus()
QApplication.clipboard().setText("hello")
if QApplication.focusWidget() is le:
    w._paste()
    assert le.text() == "hello", le.text()
    assert len(w.datasets) == n, len(w.datasets)

print("paste smoke OK")
