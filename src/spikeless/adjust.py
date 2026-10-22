"""Signal arithmetic: the isotope table and decay correction, and the backgrounds that follow
a drift (SNIP, arPLS). Nothing here mutates its inputs.

A flow radio-detector's background is flat — a count rate with Poisson noise — and is taken
as a mean (run.py). SNIP and arPLS are for the trace that drifts, and are offered as such.
"""

from __future__ import annotations

import numpy as np

_LN2 = np.log(2.0)

# ---------------------------------------------------------------- half-lives
# The isotopes the lists offer: (name, half-life in hours, decay-correct runs of it), the lab's
# common list in its order, none corrected at first. Options › Isotopes edits it, through
# set_half_lives.
ISOTOPES = [
    ("⁹⁹ᵐTc", 6.0067, False), ("²⁰¹Tl", 73.0104, False), ("¹¹¹In", 67.3176, False),
    ("¹²³I", 13.2234, False), ("¹²⁵I", 1425.312, False), ("¹⁸F", 1.8288, False),
    ("⁶⁸Ga", 1.1305, False), ("⁶⁴Cu", 12.7003, False), ("⁹⁰Y", 64.0416, False),
    ("¹⁷⁷Lu", 159.4632, False), ("¹⁶¹Tb", 166.872, False),
]
# DDEP, the suite's table (C:\Code\LRB_suite\nuclides.json; 2026.10.22). What was shipped
# before: an options file still holding one of these takes the new value
OLD_HALF_LIVES = {"⁹⁹ᵐTc": 6.00718, "²⁰¹Tl": 73.01, "¹¹¹In": 67.313, "¹²⁵I": 1425.6,
                  "⁶⁸Ga": 1.12782, "⁶⁴Cu": 12.7004, "⁹⁰Y": 64.053, "¹⁷⁷Lu": 159.528, "¹⁶¹Tb": 166.9}
HALF_LIFE_S: dict[str, float] = {}
DECAY_ON: set[str] = set()


def set_half_lives(rows):
    """The isotope table, (name, hours[, correct]) rows; rows without both are left out."""
    HALF_LIFE_S.clear()
    DECAY_ON.clear()
    for r in rows:
        if r[0] and r[1]:
            HALF_LIFE_S[r[0]] = float(r[1]) * 3600.0
            if len(r) > 2 and r[2]:
                DECAY_ON.add(r[0])


set_half_lives(ISOTOPES)


def lookup_half_life_s(isotope: str) -> float | None:
    """Half-life (s) of an isotope of the table, or None."""
    return HALF_LIFE_S.get(isotope)


def decay_on(isotope: str) -> bool:
    """Runs of this isotope are decay-corrected (its tick in Options › Isotopes)."""
    return isotope in DECAY_ON


def decay_factor(x_min: np.ndarray, half_life_s: float | None) -> np.ndarray:
    """Multiplier that corrects each sample back to the run start: exp(+λ t), t the sample's
    time (x_min, minutes from the run start) — counts scaled UP to undo the decay since."""
    x_min = np.asarray(x_min, dtype=float)
    if not half_life_s or half_life_s <= 0:
        return np.ones_like(x_min)
    return np.exp(_LN2 / half_life_s * x_min * 60.0)


# ---------------------------------------------------------------- drifting background
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
    tugging it up, leaving the slow continuum. lam = smoothness penalty (higher = stiffer).
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


BASELINE_METHODS = {"snip": _baseline_snip, "arpls": _baseline_arpls}


def estimate_baseline(y: np.ndarray, method: str = "snip", n: int = 40) -> np.ndarray:
    """A drifting background, one value per point."""
    return np.asarray(BASELINE_METHODS[method](np.asarray(y, dtype=float), n=n), float)


def _self_check():
    x = np.arange(600) / 60.0  # 10 min at 1 Hz, in minutes

    # decay: one half-life (100 s) doubles the sample at t=100 s when corrected to run start
    f = decay_factor(x, 100.0)
    assert abs(f[0] - 1.0) < 1e-12 and abs(f[100] - 2.0) < 1e-9, (f[0], f[100])

    # SNIP and arPLS recover a sloping background under a peak
    xs = np.arange(600)
    drift = 5.0 + 0.02 * xs
    sig = drift + 80.0 * np.exp(-0.5 * ((xs - 300) / 15.0) ** 2)
    for m in ("snip", "arpls"):
        b = estimate_baseline(sig, m)
        assert b.shape == sig.shape, b.shape
        assert abs(b[300] - drift[300]) < 8.0, (m, b[300], drift[300])   # tracks the slope
        assert np.all(b[:50] < sig[:50] + 3.0), m                       # hugs it off-peak

    # the isotope table is the one the options set, with its decay ticks
    assert abs(lookup_half_life_s("¹⁷⁷Lu") - 159.4632 * 3600) < 1e-6 and not decay_on("¹⁷⁷Lu")
    set_half_lives([("¹⁷⁷Lu", 160.0, True), ("X", 0), ("", 5), ("¹⁸F", 1.83)])
    assert lookup_half_life_s("¹⁷⁷Lu") == 160.0 * 3600 and lookup_half_life_s("X") is None
    assert decay_on("¹⁷⁷Lu") and not decay_on("¹⁸F")
    set_half_lives(ISOTOPES)
    print("adjust self-check OK")


if __name__ == "__main__":
    _self_check()
