"""Parser for GINA X radio-HPLC text exports.

Format (reverse-engineered from real exports):
- Windows-1252 (cp1252) encoded.
- Line 1: "<run name>, DD/MM/YYYY HH:MM".
- Line 2: tab-separated, double-quoted column headers (column set varies per file).
- Data rows: tab-separated, every field wrapped in double quotes, decimal COMMA.
- Signal = 2nd column (radiodetector count rate, cps). Col 3 ("Canal A, cps") is usually all-zero.
- Time column is display-formatted and lossy (SS"cc -> MM'SS" -> HH:MM once past 60 min),
  so we do NOT trust it for values: sampling is assumed uniform and time is rebuilt as i*dt.
  dt is inferred from the fine-resolution early rows (all known files are 1 Hz).
  # ponytail: assume uniform sampling; upgrade to per-row parsed time only if a non-uniform file appears
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .dataset import Curve, Dataset, Meta

_DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


def _unquote(field: str) -> str:
    """Strip exactly one layer of surrounding double quotes (GINA does not escape inner quotes)."""
    f = field.strip()
    if len(f) >= 2 and f.startswith('"') and f.endswith('"'):
        f = f[1:-1]
    return f


def _to_float(field: str) -> float:
    """Parse a GINA numeric field: unquote and swap decimal comma for a dot."""
    f = _unquote(field).replace(",", ".")
    try:
        return float(f)
    except ValueError:
        return float("nan")


def _time_to_seconds(raw: str):
    """Convert a GINA time field to seconds, or None if unparseable.

    Handles the three renderings seen in one run: SS"cc (first minute),
    MM'SS" (minutes), HH:MM (past 60 min, seconds resolution lost).
    """
    s = _unquote(raw).strip().rstrip('"')
    if not s:
        return None
    try:
        if ":" in s:  # HH:MM (or HH:MM:SS)
            parts = [int(p) for p in s.split(":")]
            if len(parts) == 2:
                return parts[0] * 3600 + parts[1] * 60
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif "'" in s:  # MM'SS
            m, sec = s.split("'", 1)
            return int(m) * 60 + int(sec or 0)
        elif '"' in s:  # SS"cc  (seconds " centiseconds)
            sec, cc = s.split('"', 1)
            return int(sec) + (int(cc) / 100 if cc else 0.0)
        else:
            return float(s)
    except ValueError:
        return None
    return None


def _infer_dt(time_raw: list[str]) -> float:
    """Infer the sample interval (s) from the fine-resolution early rows. Falls back to 1.0."""
    secs = []
    for raw in time_raw[:180]:  # fine region: within the first ~3 minutes
        t = _time_to_seconds(raw)
        secs.append(t)
    diffs = [b - a for a, b in zip(secs, secs[1:]) if a is not None and b is not None and b > a]
    if not diffs:
        return 1.0
    dt = float(np.median(diffs))
    return dt if dt > 0 else 1.0


def load(path: str | Path, signal_col: int = 1) -> tuple[Dataset, list[str]]:
    """Load a GINA export. Returns (Dataset, warnings). Warnings are non-fatal."""
    path = Path(path)
    warnings: list[str] = []
    text = path.read_bytes().decode("cp1252", errors="replace")
    lines = text.splitlines()

    if len(lines) < 3:
        raise ValueError("File has fewer than 3 lines — not a GINA export.")

    # Line 1: metadata
    meta_line = lines[0].strip()
    if ", " in meta_line and _DATE_RE.search(meta_line):
        run_name, run_datetime = meta_line.rsplit(", ", 1)
    else:
        run_name, run_datetime = meta_line, ""
        warnings.append("Metadata line has no recognizable 'name, DD/MM/YYYY HH:MM' — check the file.")

    # Line 2: headers
    headers = [_unquote(h) for h in lines[1].split("\t")]
    if not headers or "time" not in headers[0].lower():
        warnings.append(f"First column header is '{headers[0] if headers else ''}', expected a 'Time' column.")
    if len(headers) < 2:
        raise ValueError("Header row has fewer than 2 columns — no signal channel to read.")
    if signal_col >= len(headers):
        warnings.append(f"Signal column {signal_col} out of range; falling back to column 1.")
        signal_col = 1

    # Data rows
    time_raw: list[str] = []
    y_vals: list[float] = []
    for ln in lines[2:]:
        if not ln.strip():
            continue
        cols = ln.split("\t")
        if len(cols) <= signal_col:
            continue
        time_raw.append(cols[0])
        y_vals.append(_to_float(cols[signal_col]))

    if len(y_vals) < 10:
        warnings.append(f"Only {len(y_vals)} data rows found — file looks truncated.")
    if not y_vals:
        raise ValueError("No data rows could be parsed.")

    y = np.array(y_vals, dtype=float)
    dt = _infer_dt(time_raw)
    x = np.arange(len(y)) * dt / 60.0  # minutes

    if np.nan_to_num(y).max() == 0:
        warnings.append(f"Signal column '{headers[signal_col]}' is all zeros — wrong channel?")

    name = run_name.strip() or path.stem
    root = Curve(x=x, y=y, name="original", kind="original", legend_label=name)
    ds = Dataset(
        root=root,
        run_name=run_name.strip(),
        run_datetime=run_datetime.strip(),
        dt_s=dt,
        headers=headers,
        signal_col=signal_col,
        meta=Meta(name=name, original_filename=path.name),
    )
    return ds, warnings


def _render_time(sec: float) -> str:
    """Render seconds the way GINA does: SS\"cc, then MM'SS\", then HH:MM past 60 min."""
    sec = float(sec)
    if sec < 60:
        s = int(sec)
        cc = int(round((sec - s) * 100))
        return f'{s:02d}"{cc:02d}'
    if sec < 3600:
        m = int(sec // 60)
        s = int(round(sec - m * 60))
        return f"{m:02d}'{s:02d}"
    h = int(sec // 3600)
    m = int(round((sec - h * 3600) / 60))
    return f"{h:02d}:{m:02d}"


def save(ds, curve, path: str | Path) -> Path:
    """Write a curve's signal back to a GINA-style .txt.

    cp1252, tab-separated, double-quoted fields, decimal comma, reconstructed time column —
    the same format our loader reads, so it round-trips (GINA X compatibility is best-effort,
    since we cannot re-emit channels we never read). Two columns: time + signal.
    """
    path = Path(path)
    name = ds.run_name or ds.meta.name
    header1 = f"{name}, {ds.run_datetime}" if ds.run_datetime else name
    if ds.headers and len(ds.headers) >= 2 and ds.signal_col < len(ds.headers):
        h_time, h_sig = ds.headers[0], ds.headers[ds.signal_col]
    else:
        h_time, h_sig = "Time, s", "Taux comptage du canal A, cps"
    lines = [header1, f'"{h_time}"\t"{h_sig}"']
    dt = ds.dt_s
    y = np.asarray(curve.y, dtype=float)
    for i, v in enumerate(y):
        t = _render_time(i * dt)
        vs = ("%.3f" % float(v)).replace(".", ",")
        lines.append(f'"{t}"\t"{vs}"')
    path.write_bytes(("\n".join(lines) + "\n").encode("cp1252", errors="replace"))
    return path


def _self_check():
    import tempfile

    sample = (
        "Interval Values Demo, 07/07/2026 14:17\n"
        '"Time, s"\t"Taux comptage du canal A, cps"\t"Canal A, cps"\n'
        '"00"00"\t"8,000"\t"0,000"\n'
        '"01"00"\t"2,500"\t"0,000"\n'
        '"02"00"\t"7,000"\t"0,000"\n'
    )
    p = Path(tempfile.gettempdir()) / "_spikeless_iotest.txt"
    p.write_bytes(sample.encode("cp1252"))
    ds, warns = load(p)
    assert ds.run_name == "Interval Values Demo", ds.run_name
    assert ds.run_datetime == "07/07/2026 14:17", ds.run_datetime
    assert len(ds.root.y) == 3, len(ds.root.y)
    assert abs(ds.root.y[1] - 2.5) < 1e-9, ds.root.y
    assert abs(ds.dt_s - 1.0) < 1e-9, ds.dt_s
    assert abs(ds.root.x[2] - 2 / 60) < 1e-9, ds.root.x
    assert _time_to_seconds('"01:18"') == 4680
    assert _time_to_seconds('"01\'07"') == 67
    assert _time_to_seconds('"05"00"') == 5

    # save round-trips through our own loader
    out = Path(tempfile.gettempdir()) / "_spikeless_savetest.txt"
    save(ds, ds.root, out)
    ds2, _ = load(out)
    assert len(ds2.root.y) == len(ds.root.y), (len(ds2.root.y), len(ds.root.y))
    assert abs(ds2.root.y[1] - ds.root.y[1]) < 1e-3, (ds2.root.y[1], ds.root.y[1])
    assert abs(ds2.dt_s - ds.dt_s) < 1e-9, ds2.dt_s
    out.unlink(missing_ok=True)

    p.unlink(missing_ok=True)
    print("io_gina self-check OK")


if __name__ == "__main__":
    _self_check()
