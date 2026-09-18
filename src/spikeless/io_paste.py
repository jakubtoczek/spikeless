"""Parse numeric columns pasted from the clipboard (Prism, Excel, a text editor).

Two layouts, told apart automatically:
- shared time: column 1 is time, every column after it is one run's count rate (cps);
- paired: time1, value1, time2, value2, … — recognised when the count of columns is even
  and every second one rises like a time axis, which a count-rate column never does.
Either way each value column becomes its own Dataset, so one paste can load several runs
of unequal length (blank cells are simply dropped from that pair).

Separator may be tab, semicolon or any whitespace; decimal comma is accepted; non-numeric
lines are skipped, and the last one above the data is taken as column titles if it has any.
Neither Prism nor Excel copies units with the numbers, so the time unit is guessed from the
spacing and the span — minutes unless the numbers look like seconds — and the guess is
reported as a warning so the user can see what was assumed.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np

from .dataset import Curve, Dataset, Meta

# integer / decimal / scientific, with '.' or ',' as the decimal mark
_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$")


def _num(field: str):
    """Parse one cell (decimal comma allowed), or None if it is blank or not a number."""
    f = field.strip().strip('"').replace(" ", "").replace(" ", "")
    if not _NUM_RE.match(f):
        return None
    return float(f.replace(",", "."))


def _split(line: str) -> list[str]:
    """Split a pasted row. Tabs win (Excel/Prism), then semicolons, then plain whitespace.
    Tab/semicolon splits keep empty cells, so a short column stays in its own place."""
    if "\t" in line:
        return line.split("\t")
    if ";" in line:
        return line.split(";")
    return line.split()


def _table(text: str) -> tuple[list[list[float | None]], list[str]]:
    """(grid, column titles). A grid row is a line's cells as float-or-None, at the table's
    own column count — the most common count, so one stray wide line cannot set it. Titles
    come from the last non-numeric line above the data, and may be blank."""
    rows: list[list[float | None]] = []
    titles: list[str] = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        fields = _split(ln)
        vals = [_num(f) for f in fields]
        if sum(v is not None for v in vals) >= 2:
            rows.append(vals)
        elif not rows:
            titles = [f.strip().strip('"') for f in fields]
    if not rows:
        return [], []
    ncols = Counter(len(v) for v in rows).most_common(1)[0][0]
    grid = [v[:ncols] for v in rows if len(v) >= ncols]
    titles = (titles + [""] * ncols)[:ncols]
    return grid, titles


def _column(grid, xi: int, yi: int) -> tuple[np.ndarray, np.ndarray]:
    """One (x, y) series, skipping rows where either cell is blank."""
    pairs = [(r[xi], r[yi]) for r in grid if r[xi] is not None and r[yi] is not None]
    return (np.array([p[0] for p in pairs], dtype=float),
            np.array([p[1] for p in pairs], dtype=float))


def _is_paired(grid, ncols: int) -> bool:
    """True for a time1,value1,time2,value2,… layout: every second column reads like a time
    axis — strictly rising at a near-constant step. A real count-rate column fails on one or
    the other (noise alone breaks the constant step).
    # ponytail: two cheap tests, and the chosen layout is logged; add a layout chooser to the
    # paste only if a real file ever fools it (a rising, evenly-spaced signal column)."""
    if ncols < 4 or ncols % 2:
        return False
    for xi in range(2, ncols, 2):
        xs = [r[xi] for r in grid if r[xi] is not None]
        if len(xs) < 3 or not all(b > a for a, b in zip(xs, xs[1:])):
            return False
        dx = np.diff(np.array(xs, dtype=float))
        if (dx.max() - dx.min()) > 0.05 * float(np.median(dx)):
            return False
    return True


def load_text(text: str, name: str = "Clipboard") -> tuple[list[Dataset], list[str]]:
    """Build one Dataset per value column of pasted text.
    Returns (datasets, warnings). Raises ValueError on unusable input."""
    grid, titles = _table(text)
    if len(grid) < 3:
        raise ValueError("No numeric columns on the clipboard — copy time in the first column "
                         "and counts in the ones after it (tab, semicolon or space separated).")

    ncols = len(grid[0])
    paired = _is_paired(grid, ncols)
    cols = ([(j, j + 1) for j in range(0, ncols, 2)] if paired
            else [(0, j) for j in range(1, ncols)])

    out: list[Dataset] = []
    warnings: list[str] = []
    units: list[str] = []
    ragged: list[str] = []
    zeros: list[str] = []
    first: tuple[float, float] | None = None

    for xi, yi in cols:
        x, y = _column(grid, xi, yi)
        label = titles[yi] or (name if len(cols) == 1 else f"{name} col {yi + 1}")
        if x.size < 3:
            warnings.append(f"Skipped '{label}': fewer than 3 usable rows.")
            continue
        dx = np.diff(x)
        if not np.all(dx > 0):
            warnings.append(f"Skipped '{label}': its time column does not rise.")
            continue
        dt = float(np.median(dx))

        # Unit guess: a 1 Hz run reads as ~0.017 in minutes but ~1 in seconds, and no radio-HPLC
        # run lasts 180 min — either signal alone is enough to call it seconds.
        # ponytail: heuristic, logged; add an explicit unit prompt only if it ever guesses wrong
        in_seconds = dt >= 0.5 or float(x[-1]) > 180.0
        units.append("seconds" if in_seconds else "minutes")
        if first is None:
            first = (dt, float(x[-1]))
        if (dx.max() - dx.min()) > 0.05 * dt:
            ragged.append(label)
        if float(np.nanmax(y)) == 0:
            zeros.append(label)

        root = Curve(x=x / 60.0 if in_seconds else x, y=y, name="original", kind="original",
                     legend_label=label)
        out.append(Dataset(
            root=root,
            run_name=label,
            dt_s=dt if in_seconds else dt * 60.0,
            signal_col=yi,
            meta=Meta(name=label, original_filename="(clipboard)"),
        ))

    if not out:
        raise ValueError("No usable time/value column pair on the clipboard — the first column "
                         "of a pair must be a rising time axis.")

    dt0, last0 = first
    warnings.insert(0, f"Pasted X read as {'/'.join(sorted(set(units)))} "
                       f"(spacing {dt0:g}, last value {last0:g}); Y read as count rate (cps).")
    if ncols > 2:
        how = "as time/value pairs" if paired else "on a shared time axis"
        warnings.insert(1, f"{ncols} columns pasted {how} → {len(out)} datasets.")
    if ragged:
        warnings.append(f"Sampling is not quite uniform in {', '.join(ragged)}; "
                        "X values are kept as pasted.")
    if zeros:
        warnings.append(f"All zeros: {', '.join(zeros)} — wrong column copied?")
    return out, warnings


def _self_check():
    tab, nl = "\t", "\n"

    # the user's Prism case: 1 Hz sampling expressed in minutes
    prism = nl.join(f"{v}{tab}{c}" for v, c in
                    ((0, 7), (0.017, 8), (0.033, 4), (0.05, 4), (0.067, 8), (14.983, 0))) + nl
    (ds,), w = load_text(prism)
    assert len(ds.root.y) == 6, len(ds.root.y)
    assert abs(ds.root.x[1] - 0.017) < 1e-12, ds.root.x[1]      # already minutes, untouched
    assert abs(ds.dt_s - 0.017 * 60) < 1e-9, ds.dt_s
    assert ds.meta.name == "Clipboard", ds.meta.name
    assert any("minutes" in s for s in w), w

    # same run in seconds, with a header row and decimal commas (French Excel)
    (ds2,), w2 = load_text("Temps;Coups\n0;7\n1,0;8\n2,0;4,5\n3,0;4\n")
    assert len(ds2.root.y) == 4, len(ds2.root.y)
    assert abs(ds2.root.x[1] - 1 / 60) < 1e-12, ds2.root.x[1]   # converted to minutes
    assert abs(ds2.root.y[2] - 4.5) < 1e-12, ds2.root.y[2]
    assert abs(ds2.dt_s - 1.0) < 1e-9, ds2.dt_s
    assert ds2.meta.name == "Coups", ds2.meta.name              # column title beats the fallback
    assert any("seconds" in s for s in w2), w2

    # shared time axis: 4 columns -> 3 datasets, named by their titles. 'treated' rises over
    # this window but not at a constant step, which is what keeps it out of the paired layout.
    multi = nl.join(tab.join(r) for r in (
        ("Time", "ctrl", "treated", "blank"),
        ("0", "5", "50", "0"), ("0.5", "6", "63", "0"),
        ("1", "7", "70", "0"), ("1.5", "8", "94", "0"))) + nl
    dss, w3 = load_text(multi)
    assert [d.meta.name for d in dss] == ["ctrl", "treated", "blank"], [d.meta.name for d in dss]
    assert list(dss[1].root.y) == [50.0, 63.0, 70.0, 94.0], dss[1].root.y
    assert all(list(d.root.x) == list(dss[0].root.x) for d in dss), "time axis not shared"
    assert any("shared time axis" in s and "3 datasets" in s for s in w3), w3
    assert any("All zeros: blank" in s for s in w3), w3

    # paired layout: time1,y1,time2,y2 -> 2 datasets, each on its own axis, unequal lengths
    pairs = nl.join(tab.join(r) for r in (
        ("Tmin", "runA", "Tsec", "runB"),
        ("0", "5", "0", "90"), ("0.1", "6", "30", "80"), ("0.2", "7", "60", "70"),
        ("0.3", "8", "90", "60"), ("0.4", "9", "", ""))) + nl
    dsp, w4 = load_text(pairs)
    assert [d.meta.name for d in dsp] == ["runA", "runB"], [d.meta.name for d in dsp]
    assert len(dsp[0].root.y) == 5 and len(dsp[1].root.y) == 4, \
        (len(dsp[0].root.y), len(dsp[1].root.y))                # the blank tail is dropped
    assert abs(dsp[0].dt_s - 6.0) < 1e-9, dsp[0].dt_s            # 0.1 min spacing, read as minutes
    assert abs(dsp[1].dt_s - 30.0) < 1e-9, dsp[1].dt_s           # 30 s spacing, read as seconds
    assert abs(dsp[0].root.x[-1] - 0.4) < 1e-12, dsp[0].root.x[-1]
    assert abs(dsp[1].root.x[-1] - 1.5) < 1e-12, dsp[1].root.x[-1]
    assert any("time/value pairs" in s for s in w4), w4
    assert any("minutes" in s and "seconds" in s for s in w4), w4   # both units reported

    # 4 columns that are NOT pairs (col 3 is a signal) stay on a shared axis
    notpairs = nl.join(tab.join(r) for r in (
        ("0", "5", "9", "1"), ("1", "6", "3", "2"),
        ("2", "7", "8", "3"), ("3", "8", "2", "4"))) + nl
    assert len(load_text(notpairs)[0]) == 3, "a noisy 3rd column was mistaken for a time axis"

    # untitled columns fall back to their position
    dss4, _ = load_text("0 1 10\n1 2 20\n2 3 30\n", name="Clipboard 7")
    assert [d.meta.name for d in dss4] == ["Clipboard 7 col 2", "Clipboard 7 col 3"], \
        [d.meta.name for d in dss4]

    # a long run in minutes must not be mistaken for seconds
    (ds5,), _ = load_text("".join(f"{i * 0.1:g} {i}\n" for i in range(300)))
    assert abs(ds5.dt_s - 6.0) < 1e-9, ds5.dt_s                 # 0.1 min spacing
    assert abs(ds5.root.x[-1] - 29.9) < 1e-9, ds5.root.x[-1]

    # one stray wide line must not turn the whole paste into a 3-column table
    dss6, _ = load_text("0 5\n1 6\n2 7 99\n3 8\n4 9\n")
    assert len(dss6) == 1, [d.meta.name for d in dss6]
    assert list(dss6[0].root.y) == [5.0, 6.0, 7.0, 8.0, 9.0], dss6[0].root.y

    # junk lines between rows are skipped
    dss7, _ = load_text("X Y\n0 5\nrubbish\n1 6\n2 7\n\n")
    assert len(dss7[0].root.y) == 3, len(dss7[0].root.y)

    for bad in ("", "hello\nworld\n", "only-one-column\n1\n2\n3\n", "0 1\n0 2\n1 3\n"):
        try:
            load_text(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should have refused: {bad!r}")

    print("io_paste self-check OK")


if __name__ == "__main__":
    _self_check()
