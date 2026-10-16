"""Regions (integrated peaks): found by counting statistics, placed by hand, measured.

A region is a time window. Its **net counts** are the counts of the trace above what lies
under it — the run's background, or a straight line between the region's two ends — taken
by trapezoids (count rate × time). Results follow radio-HPLC practice:

- **% of total**: of all the net counts of the run (Ph. Eur. 0125: the radiochemical purity is
  relative to the total activity of the radionuclide); the counts outside every region are a
  row of their own. **% of regions** beside it.
- **± (1 σ)** = √(gross + background counts), Poisson.
- **Detection / quantification limits** (Currie 1968, Anal. Chem. 40:586), from the
  background counts B under the region: L_D = 2.71 + 4.65 √B, L_Q = 50 (1 + √(1 + B/12.5)) —
  below L_D a region is "n.d.", between L_D and L_Q "< LOQ".
- **System suitability** (Ph. Eur. 2.2.46): w½ the width at half height, symmetry factor
  As = w₀.₀₅ / 2d, resolution Rs = 1.18 (t₂ − t₁) / (w½₁ + w½₂) from the region before,
  S/N = 2H / h with h the range of the background around the region.

Find regions proposes them: maxima of the 5-point mean standing 5 σ (Poisson, of that mean)
above their surroundings, at least 10 s apart, each kept if its net counts pass L_D — a
threshold of counting statistics, not a fraction of the tallest peak (which missed a 2 %
impurity beside a large product). Those numbers are the run's FindParams (defaults shown).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .run import Region, Run


def _trapz(y, x):
    return float(np.trapezoid(y, x)) * 60.0          # cps × min -> counts


def limits(b_counts: float) -> tuple[float, float]:
    """Currie's (L_D, L_Q), in counts, for a background of b_counts under the region."""
    b = max(b_counts, 0.0)
    return 2.71 + 4.65 * np.sqrt(b), 50.0 * (1.0 + np.sqrt(1.0 + b / 12.5))


def sigma(b_cps: float, dt_s: float) -> float:
    """Poisson σ of one point of a count rate b_cps measured over dt_s, in cps."""
    return float(np.sqrt(max(b_cps, 1.0) / dt_s))


# ---------------------------------------------------------------- placing
def snap(x, y, t: float, k: int = 3) -> float:
    """t moved to the lowest point of y within ±k samples of the nearest: a rough drag lands
    in the valley (k = 0: on the nearest point)."""
    i = int(np.clip(np.searchsorted(x, t), 1, len(x) - 1))
    i -= bool(t - x[i - 1] < x[i] - t)
    lo, hi = max(0, i - k), min(len(x), i + k + 1)
    return float(x[lo + int(np.argmin(y[lo:hi]))])


def fit(regions, a: float, b: float, dt_min: float, skip=None):
    """[a, b] cut back so it overlaps none of the other regions (it may share an edge), or
    None if under two points remain. `skip`: a region not to test against (the one moved)."""
    a, b = min(a, b), max(a, b)
    for o in sorted(regions, key=lambda r: r.start):
        if o is skip or o.end <= a or o.start >= b:
            continue
        if o.start <= a:                 # the start falls inside o: begin at its end
            a = o.end
        else:                            # o lies ahead: stop at its start
            b = o.start
    return (a, b) if b - a >= 2 * dt_min - 1e-9 else None


def _bounds(s, apex, noise, lo, hi, w=5, k=2.0):
    """Bounds of one peak (s: the trace above background): out from the apex while a w-point
    mean of s stays k σ above the background — its feet — or until the valley (lowest point
    before the neighbouring apex), where two unresolved peaks share an edge.
    # ponytail: a fixed k σ foot on a w-point mean; a slow tail past it counts as outside the
    # region, which the results show — make w follow the peak width if tails matter."""
    sm = np.convolve(s, np.ones(w) / w, mode="same")
    thr = k * noise / np.sqrt(w)
    left_v = lo + int(np.argmin(sm[lo:apex + 1]))
    right_v = apex + int(np.argmin(sm[apex:hi + 1]))
    i = apex
    while i > left_v and sm[i - 1] > thr:
        i -= 1
    j = apex
    while j < right_v and sm[j + 1] > thr:
        j += 1
    i, j = max(left_v, i - 1), min(right_v, j + 1)      # the foot itself
    return (i, j) if j - i >= 2 else (max(0, apex - 1), min(len(s) - 1, apex + 1))


def find_regions(run: Run) -> list[Region]:
    """Regions for the peaks no region holds yet (see the module docstring)."""
    from scipy.signal import find_peaks   # 1.3 s to import: kept off the startup path

    p = run.find_params
    w = max(1, int(p.smooth))
    x, y = run.x, run.trace()
    b, _ = run.background()
    s = y - b
    noise = sigma(float(np.median(b)), run.dt_s)
    # on a w-point mean, n σ of that mean: one noisy point on a tail is not a peak
    sm = np.convolve(s, np.ones(w) / w, mode="same")
    apexes, _ = find_peaks(sm, prominence=p.n_sigma * noise / np.sqrt(w),
                           distance=max(1, round(p.min_gap_s / run.dt_s)))
    held = run.in_regions()
    dtm = run.dt_s / 60.0
    out = []
    for k, a in enumerate(apexes):
        if held[a]:
            continue
        lo = 0 if k == 0 else int(apexes[k - 1])
        hi = len(s) - 1 if k == len(apexes) - 1 else int(apexes[k + 1])
        i, j = _bounds(s, int(a), noise, lo, hi, w, p.foot_sigma)
        ab = fit(run.regions + out, float(x[i]), float(x[j]), dtm)
        if ab is None:
            continue
        sel = (x >= ab[0]) & (x <= ab[1])
        net, bc = _trapz(s[sel], x[sel]), _trapz(b[sel], x[sel])
        if net > limits(bc)[0]:
            out.append(Region(*ab))
    return out


# ---------------------------------------------------------------- measuring
@dataclass
class Row:
    name: str
    start: float
    end: float
    named: bool = False             # typed or from the method (not "peak N (Rt)")
    rt: float = 0.0
    net: float = 0.0                # counts
    unc: float = 0.0                # ± 1 σ, counts
    pct: float | None = None        # % of total
    pct_reg: float | None = None    # % of regions
    height: float = 0.0             # cps above what lies under the region
    w_half: float | None = None     # min
    sym: float | None = None
    rs: float | None = None
    sn: float | None = None
    flags: list = field(default_factory=list)
    spikes: int = 0                 # excluded spikes inside the region
    net_with_spikes: float | None = None   # its net counts had they been kept


@dataclass
class Results:
    rows: list                      # a Row per region, in the regions' order
    outside: float                  # net counts outside every region
    total: float                    # net counts of the run
    background: float               # cps (mean, for a drifting one)
    background_how: str
    active: bool                    # total above the run's detection limit: % make sense


def _cross(s, k, level, step):
    """Where s falls below level going from index k in direction step (±1), interpolated
    (fractional index), or None if it never does."""
    i = k
    while 0 <= i + step < len(s):
        if s[i + step] < level:
            return i + step * (s[i] - level) / (s[i] - s[i + step])
        i += step
    return None


def measure(run: Run, method_rows=()) -> Results:
    """Every region's row (see the module docstring). method_rows: [method, name, from, to]
    (Options › Methods), naming the regions whose apex falls in a window of the run's method;
    a region without a typed or method name is "peak N (Rt)"."""
    x, y = run.x, run.trace()
    b, how = run.background()
    raw = run.trace(raw=True)
    ex = run.excluded()
    total = _trapz(y - b, x)
    active = total > limits(_trapz(b, x))[0]
    inside = run.in_regions()
    wins = [(m[1], m[2], m[3]) for m in method_rows if run.method and m[0] == run.method]
    dtm = run.dt_s / 60.0
    rows, prev = [], None
    for k, r in enumerate(run.regions):
        sel = (x >= r.start - 1e-9) & (x <= r.end + 1e-9)
        xs, ys = x[sel], y[sel]
        row = Row(name=r.name or f"peak {k + 1}", start=r.start, end=r.end)
        rows.append(row)
        if len(xs) < 2:
            continue
        bs = (np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]]) if r.under == "line" else b[sel])
        s = ys - bs
        gross, bc = _trapz(ys, xs), _trapz(bs, xs)
        row.net = gross - bc
        row.unc = float(np.sqrt(max(gross + bc, 0.0)))
        top = int(np.argmax(s))
        row.rt, row.height = float(xs[top]), float(s[top])
        lh, rh = _cross(s, top, row.height / 2, -1), _cross(s, top, row.height / 2, 1)
        if lh is not None and rh is not None:
            row.w_half = (rh - lh) * dtm
        l5, r5 = _cross(s, top, row.height * 0.05, -1), _cross(s, top, row.height * 0.05, 1)
        if l5 is not None and r5 is not None and top > l5:
            row.sym = (r5 - l5) / (2 * (top - l5))
        if row.w_half:
            win = (x >= r.start - 5 * row.w_half) & (x <= r.end + 5 * row.w_half) & ~inside
            if win.sum() >= 5 and np.ptp(y[win]) > 0:
                row.sn = 2 * row.height / float(np.ptp(y[win]))
            if prev is not None and prev.w_half:
                row.rs = 1.18 * (row.rt - prev.rt) / (row.w_half + prev.w_half)
        ld, lq = limits(bc)
        row.flags = ([r.how] if r.how != "auto" else []) + \
            (["n.d."] if row.net < ld else ["< LOQ"] if row.net < lq else [])
        row.spikes = int((ex & sel).sum())
        if row.spikes:
            row.flags.append("spike excluded")
            row.net_with_spikes = _trapz(raw[sel], xs) - bc
        hit = next((n for n, lo, hi in wins if lo <= row.rt <= hi), None)
        row.name = r.name or hit or f"peak {k + 1} ({row.rt:.2f} min)"
        row.named = bool(r.name or hit)
        prev = row
    found = sum(r.net for r in rows if "n.d." not in r.flags and r.net > 0)
    for r in rows:
        if active and "n.d." not in r.flags:
            r.pct = 100 * r.net / total
            r.pct_reg = 100 * r.net / found if found > 0 else None
    return Results(rows, total - sum(r.net for r in rows), total, float(np.mean(b)), how, active)


def _self_check():
    rng = np.random.default_rng(3)
    n, bg = 900, 7.0
    t = np.arange(n, dtype=float)                       # s, 1 Hz
    lam = bg + 1200 * np.exp(-0.5 * ((t - 480) / 6) ** 2) + 30 * np.exp(-0.5 * ((t - 150) / 5) ** 2)
    y = rng.poisson(lam).astype(float)
    y[300] += 2500                                      # a spike on the background
    y[478] += 4000                                      # and one on the big peak
    run = Run(x=t / 60, y=y, dt_s=1.0)
    run.detect_spikes()
    assert run.spike_list() == [300, 478], run.spike_list()
    true_big = 1200 * 6 * np.sqrt(2 * np.pi)            # counts of each Gaussian
    true_small = 30 * 5 * np.sqrt(2 * np.pi)

    run.regions = find_regions(run)
    assert len(run.regions) == 2, [(r.start, r.end) for r in run.regions]
    res = measure(run)
    small, big = res.rows
    assert abs(big.rt - 8.0) < 0.05 and abs(small.rt - 2.5) < 0.05, (small.rt, big.rt)
    assert abs(big.net - true_big) < 3 * big.unc + 0.01 * true_big, (big.net, true_big)
    assert abs(small.net - true_small) < 3 * small.unc + 40, (small.net, true_small)
    assert abs(res.background - bg) < 0.5, res.background
    assert abs(sum(r.pct for r in res.rows) + 100 * res.outside / res.total - 100) < 1e-9
    assert abs(big.w_half - 2.3548 * 6 / 60) < 0.02, big.w_half     # FWHM of a Gaussian
    assert 0.8 < big.sym < 1.25, big.sym                              # symmetric
    assert big.rs > 10 and big.sn > 100, (big.rs, big.sn)
    assert big.spikes == 1 and big.net_with_spikes > big.net + 1000, big.net_with_spikes
    assert small.flags == [] and "spike excluded" in big.flags, (small.flags, big.flags)

    # a spike put back is back in the trace
    run.kept = [478]
    assert run.trace()[478] == y[478]
    run.kept = []

    # names: typed, then the method's window, then "peak N (Rt)"
    run.method = "M"
    rows = [["M", "product", 7.5, 8.5], ["other", "x", 2, 3]]
    name = measure(run, rows).rows[0].name
    assert name == f"peak 1 ({small.rt:.2f} min)", name
    assert measure(run, rows).rows[1].name == "product"
    run.regions[0].name = "free"
    assert measure(run, rows).rows[0].name == "free"

    # placing by hand: snap to the valley, never overlap, share an edge
    xm = run.x
    assert snap(xm, run.trace(), xm[455] + 0.001, k=3) in xm[452:459]
    r0, r1 = run.regions
    assert fit(run.regions, r0.start + 0.01, r1.start + 0.05, 1 / 60) == (r0.end, r1.start)
    assert fit(run.regions, r1.start + 0.01, r1.end - 0.01, 1 / 60) is None   # inside one

    # a drawn region on noise alone is not detected; a blank has no %
    run.regions.append(Region(12.0, 12.3, how="drawn"))
    noise_row = measure(run).rows[-1]
    assert "n.d." in noise_row.flags and noise_row.pct is None, noise_row
    blank = Run(x=t / 60, y=rng.poisson(bg, n).astype(float), dt_s=1.0)
    blank.detect_spikes()
    assert find_regions(blank) == [] and not measure(blank).active

    # the threshold is the run's: high enough, the small peak is no longer found
    probe = Run(x=run.x, y=run.y, dt_s=1.0)
    probe.detect_spikes()
    probe.find_params.n_sigma = 60
    assert len(find_regions(probe)) == 1

    # a region with a straight line under it
    run.regions = [Region(7.5, 8.5, under="line")]
    assert abs(measure(run).rows[0].net - true_big) < 0.05 * true_big
    print("peaks self-check OK")


if __name__ == "__main__":
    _self_check()
