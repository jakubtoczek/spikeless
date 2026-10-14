"""Signal arithmetic for the processing steps: decay correction, baseline, normalization.

Nothing here mutates its inputs. Decay correction and baseline subtraction each make a new
child curve (app.py); normalization is applied at plot time from a curve's `adjust` params,
so changing it and changing it back returns the original trace.

Baseline estimation is a small registry (BASELINE_METHODS): an estimator returns a scalar
or a per-point array, and estimate_baseline broadcasts either.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np

_LN2 = np.log(2.0)

# ---------------------------------------------------------------- half-lives
# The isotopes the dropdowns offer, (name, half-life in hours): the lab's common list, in
# its order. Options › Isotopes edits it, through set_half_lives.
ISOTOPES = [
    ("⁹⁹ᵐTc", 6.00718), ("²⁰¹Tl", 73.01), ("¹¹¹In", 67.313), ("¹²³I", 13.2234),
    ("¹²⁵I", 1425.6), ("¹⁸F", 1.8288), ("⁶⁸Ga", 1.12782), ("⁶⁴Cu", 12.7004),
    ("⁹⁰Y", 64.053), ("¹⁷⁷Lu", 159.528), ("¹⁶¹Tb", 166.9),
]
HALF_LIFE_S = {name: h * 3600.0 for name, h in ISOTOPES}


def set_half_lives(pairs):
    """The isotope table, (name, hours) pairs; rows without both are left out."""
    HALF_LIFE_S.clear()
    HALF_LIFE_S.update({k: float(h) * 3600.0 for k, h in pairs if k and h})


def lookup_half_life_s(isotope: str) -> float | None:
    """Half-life (s) of an isotope of the table, or None."""
    return HALF_LIFE_S.get(isotope)


# ---------------------------------------------------------------- decay
def decay_factor(x_min: np.ndarray, half_life_s: float | None,
                 ref_offset_s: float = 0.0) -> np.ndarray:
    """Multiplier that corrects each sample back to the reference time.

    x_min: sample times in minutes from run start. ref_offset_s: reference time in seconds
    from run start (0 = run start). factor = exp(+lambda * (t - t_ref)), i.e. counts are
    scaled UP to undo the decay that happened between the reference time and acquisition.
    """
    x_min = np.asarray(x_min, dtype=float)
    if not half_life_s or half_life_s <= 0:
        return np.ones_like(x_min)
    lam = _LN2 / half_life_s
    t_s = x_min * 60.0
    return np.exp(lam * (t_s - ref_offset_s))


# ---------------------------------------------------------------- baseline
def _baseline_none(y, **_):
    return 0.0


def _baseline_min(y, **_):
    return float(np.min(y))


def _baseline_first_n(y, n=20, **_):
    n = max(1, min(int(n), len(y)))
    return float(np.mean(y[:n]))


def _baseline_snip(y, n=40, **_):
    """SNIP baseline (Statistics-sensitive Nonlinear Iterative Peak-clipping): iteratively clip
    peaks down to the slow continuum, so it tracks drift instead of returning a flat floor.
    n = max half-window in samples (≈ a peak's half-width). The LLS transform compresses the
    counting range, making it Poisson-appropriate for cps data.
    Refs: Ryan 1988, Nucl. Instrum. Methods B34:396; Morhác 2008, Appl. Spectrosc. 62:91."""
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return np.clip(y, 0, None)
    v = np.log(np.log(np.sqrt(np.clip(y, 0, None) + 1.0) + 1.0) + 1.0)   # LLS forward
    for p in range(1, int(max(1, n)) + 1):
        if 2 * p >= len(v):
            break
        v[p:-p] = np.minimum(v[p:-p], 0.5 * (v[:-2 * p] + v[2 * p:]))    # increasing window
    return np.clip((np.exp(np.exp(v) - 1.0) - 1.0) ** 2 - 1.0, 0, None)  # LLS inverse


def _baseline_arpls(y, lam=1e5, ratio=1e-6, max_iter=50, **_):
    """arPLS baseline (asymmetrically reweighted penalized least squares): fit a smooth curve
    that is pulled toward the data but reweighted each iteration so points above it (peaks) stop
    tugging it up, leaving the slow continuum. Smoother than SNIP on noisy drift.
    lam = smoothness penalty (higher = stiffer baseline); scaled for typical trace lengths, so it
    absorbs `n` from the registry and ignores it. Returns the per-point baseline.
    Ref: Baek, Park, Ahn, Choo 2015, Analyst 140:250."""
    from scipy import sparse
    from scipy.sparse.linalg import spsolve

    y = np.asarray(y, dtype=float)
    N = len(y)
    if N < 3:
        return np.clip(y, 0, None)
    D = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(N - 2, N))  # 2nd difference
    H = lam * (D.T @ D)
    w = np.ones(N)
    z = y
    for _ in range(max_iter):
        z = spsolve((sparse.diags(w, 0) + H).tocsc(), w * y)
        d = y - z
        neg = d[d < 0]
        if neg.size == 0:
            break
        m, s = neg.mean(), neg.std() + 1e-12
        arg = np.clip(2.0 * (d - (2.0 * s - m)) / s, -709.0, 709.0)  # avoid exp overflow
        wt = 1.0 / (1.0 + np.exp(arg))                               # logistic reweight
        if np.linalg.norm(w - wt) / (np.linalg.norm(w) + 1e-12) < ratio:
            break
        w = wt
    return z


# key -> estimator(y, n=...) returning a scalar OR a per-point array.
# Extend here (rolling minimum, ALS, segmented/drift) — apply_adjust broadcasts either shape.
BASELINE_METHODS = {
    "none": _baseline_none,
    "min": _baseline_min,
    "first_n": _baseline_first_n,
    "snip": _baseline_snip,
    "arpls": _baseline_arpls,
}

BASELINE_LABELS = {"none": "None", "min": "Minimum", "first_n": "Average of first N points",
                   "snip": "SNIP (drift-aware)", "arpls": "arPLS (asymmetric least squares)"}


def estimate_baseline(y: np.ndarray, method: str = "min", n: int = 20) -> np.ndarray:
    """Return the baseline as a full-length array (scalar methods are broadcast)."""
    y = np.asarray(y, dtype=float)
    fn = BASELINE_METHODS.get(method, _baseline_none)
    b = fn(y, n=n)
    return np.asarray(b, dtype=float) * np.ones_like(y) if np.ndim(b) == 0 else np.asarray(b, float)


# ---------------------------------------------------------------- params + apply
@dataclass
class AdjustParams:
    """A curve's normalization, applied at plot time. Default = identity (raw cps)."""

    norm_mode: str = "cps"           # "cps" | "pct_max" | "pct_total"
    baseline_method: str = "min"     # key in BASELINE_METHODS (used by pct_* modes)
    baseline_n: int = 20


_UNIT_LABEL = {"cps": "Counts (cps)", "pct_max": "% of max", "pct_total": "% of total"}


def apply_adjust(x_min: np.ndarray, y: np.ndarray, params: AdjustParams | None,
                 unit: str = "cps", baseline: np.ndarray | None = None) -> tuple[np.ndarray, str]:
    """Return (adjusted_y, y_unit_label). Pure — does not touch the inputs.

    For %-modes the baseline subtracted is the curve's detected `baseline` if given, else the
    fallback estimate (params.baseline_method).
    """
    y = np.asarray(y, dtype=float).copy()
    p = params or AdjustParams()

    if p.norm_mode == "cps":
        return y, _UNIT_LABEL["cps"]

    base = np.asarray(baseline, float) if baseline is not None else \
        estimate_baseline(y, p.baseline_method, p.baseline_n)
    y = y - base
    if p.norm_mode == "pct_max":
        m = float(np.nanmax(y)) if y.size else 0.0
        if m > 0:
            y = y / m * 100.0
    elif p.norm_mode == "pct_total":
        tot = float(np.nansum(y))
        if tot > 0:
            y = y / tot * 100.0
    return y, _UNIT_LABEL.get(p.norm_mode, unit)


def _self_check():
    x = np.arange(600) / 60.0  # 10 min at 1 Hz, in minutes

    # decay: one half-life (100 s) doubles the sample at t=100 s when corrected to run start
    hl = 100.0
    f = decay_factor(x, hl, ref_offset_s=0.0)
    i100 = 100  # index at 100 s
    assert abs(f[0] - 1.0) < 1e-12, f[0]
    assert abs(f[i100] - 2.0) < 1e-9, f[i100]

    # baseline methods
    y = np.full(600, 5.0)
    y[300] = 105.0
    assert estimate_baseline(y, "min")[0] == 5.0
    assert abs(estimate_baseline(y, "first_n", n=10)[0] - 5.0) < 1e-9
    assert estimate_baseline(y, "none")[0] == 0.0

    # SNIP is drift-aware: it recovers a sloping baseline under a peak (constant methods can't)
    xs = np.arange(600)
    drift = 5.0 + 0.02 * xs
    sig = drift + 80.0 * np.exp(-0.5 * ((xs - 300) / 15.0) ** 2)
    bs = estimate_baseline(sig, "snip", n=40)
    assert bs.shape == sig.shape, bs.shape
    assert abs(bs[300] - drift[300]) < 8.0, (bs[300], drift[300])   # tracks slope under the apex
    assert bs[300] < sig[300] - 40.0, bs[300]                       # sits well below the peak
    assert np.all(bs[:50] < sig[:50] + 3.0)                         # hugs baseline in peak-free region

    # arPLS is also drift-aware and drops in via the registry like SNIP
    ba = estimate_baseline(sig, "arpls")
    assert ba.shape == sig.shape, ba.shape
    assert abs(ba[300] - drift[300]) < 8.0, (ba[300], drift[300])   # tracks slope under the apex
    assert ba[300] < sig[300] - 40.0, ba[300]                       # sits well below the peak
    assert np.all(ba[:50] < sig[:50] + 3.0)                         # hugs baseline in peak-free region

    # pct_max: peak becomes 100 after baseline subtraction
    ym, unit = apply_adjust(x, y, AdjustParams(norm_mode="pct_max", baseline_method="min"))
    assert abs(ym.max() - 100.0) < 1e-9, ym.max()
    assert unit == "% of max"

    # pct_total: sums to 100
    yt, _ = apply_adjust(x, y, AdjustParams(norm_mode="pct_total", baseline_method="min"))
    assert abs(np.nansum(yt) - 100.0) < 1e-6, np.nansum(yt)

    # identity leaves data untouched
    y0, u0 = apply_adjust(x, y, AdjustParams())
    assert np.array_equal(y0, y) and u0 == "Counts (cps)"

    # the isotope table is the one the options set
    assert abs(lookup_half_life_s("¹⁷⁷Lu") - 159.528 * 3600) < 1e-6
    set_half_lives([("¹⁷⁷Lu", 160.0), ("X", 0), ("", 5)])     # rows without both are dropped
    assert lookup_half_life_s("¹⁷⁷Lu") == 160.0 * 3600 and lookup_half_life_s("X") is None
    set_half_lives(ISOTOPES)
    print("adjust self-check OK")


if __name__ == "__main__":
    _self_check()
