"""Single-point spike detection (Hampel filter) and removal for radio-HPLC signals.

A spike is one timepoint whose value sits far above the local median. The Hampel filter
(rolling median + MAD) is local, so it flags a spike even when it rides on a genuine
chromatographic peak, while leaving the (multi-point) peak itself untouched. Removal
replaces flagged points by linear interpolation from their nearest clean neighbors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826  # MAD -> std for normally distributed data


@dataclass
class SpikeParams:
    window: int = 7  # rolling window size (odd); larger = smoother median reference
    n_sigma: float = 5.0  # threshold in robust std units
    max_width: int = 1  # max consecutive points a spike may span (keeps real peaks safe)
    positive_only: bool = True  # only flag upward excursions (spikes are high cps)
    poisson_floor: bool = True  # floor the noise scale at sqrt(median): correct for cps counting data


def _runs(mask: np.ndarray):
    """(start, stop) of each run of True in mask."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], mask.astype(np.int8), [0]))))
    return zip(edges[::2], edges[1::2])


def detect(y: np.ndarray, params: SpikeParams | None = None) -> np.ndarray:
    """Return a boolean mask, True where y has a spike."""
    p = params or SpikeParams()
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return np.zeros(len(y), dtype=bool)
    win = max(3, p.window | 1)  # force odd, >= 3

    from scipy.ndimage import median_filter   # imported here, not at startup (see peaks.py)
    med = median_filter(y, size=win, mode="reflect")
    abs_resid = np.abs(y - med)
    mad_local = median_filter(abs_resid, size=win, mode="reflect")
    # Floor the local scale at the global noise level so a smooth region whose local MAD
    # collapses to ~0 doesn't flag trivial (~1 cps) deviations as spikes.
    global_mad = np.median(abs_resid)
    sigma = _MAD_TO_SIGMA * np.maximum(mad_local, global_mad)
    if p.poisson_floor:
        sigma = np.maximum(sigma, np.sqrt(np.maximum(med, 1.0)))
    sigma = np.maximum(sigma, 1e-9)
    diff = y - med
    excess = diff if p.positive_only else np.abs(diff)
    out = np.zeros(len(y), dtype=bool)
    for i, j in _runs(excess > p.n_sigma * sigma):
        if j - i > p.max_width:
            continue                    # a wide excursion is a real peak, not a spike
        # A spike also stands clear of both its neighbours. The apex of a narrow real peak
        # sits above the window's median but not far above the points beside it.
        nb = [y[k] for k in (i - 1, j) if 0 <= k < len(y)]
        up = y[i:j].min() - max(nb) if nb else np.inf
        down = min(nb) - y[i:j].max() if nb else np.inf
        if (up if p.positive_only else max(up, down)) > p.n_sigma * sigma[i:j].max():
            out[i:j] = True
    return out


def remove(y: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """A copy of y with the masked points excluded and bridged: the straight line between
    their nearest kept neighbours (n-1 -> n+1 for a single point). Drawn, that is the curve
    without the point; integrated, the same area as trapezoids across the gap. It cannot
    overshoot. (PCHIP was offered until 2026.10.14: a curve assumption for nothing gained.)"""
    y = np.asarray(y, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    out = y.copy()
    if not mask.any() or (~mask).sum() < 2:
        return out  # nothing to exclude, or nothing to bridge from
    idx = np.arange(len(y))
    out[mask] = np.interp(idx[mask], idx[~mask], y[~mask])
    return out


def _self_check():
    rng = np.random.default_rng(0)
    n = 400
    baseline = 8.0 + rng.normal(0, 1.5, n)
    peak = 120.0 * np.exp(-0.5 * ((np.arange(n) - 200) / 12.0) ** 2)  # wide real peak
    y = baseline + peak
    y[120] += 1500.0  # inject a single-point spike on the baseline
    y[205] += 1500.0  # inject a single-point spike ON the real peak's flank

    mask = detect(y)
    assert mask[120], "baseline spike not detected"
    assert mask[205], "spike on real peak not detected"
    assert not mask[200], "real peak apex wrongly flagged as spike"
    assert mask.sum() == 2, f"expected exactly 2 spikes, got {mask.sum()}"

    cleaned = remove(y, mask)
    assert abs(cleaned[120] - baseline[120]) < 6, cleaned[120]  # back near baseline
    assert abs(cleaned[205] - peak[205]) < 15, (cleaned[205], peak[205])  # back near peak level
    assert cleaned[200] == y[200], "apex changed by removal"

    # bridging = dropping the point: trapezoids across the gap give the same area
    keep = ~mask
    assert abs(np.trapezoid(cleaned) - np.trapezoid(y[keep], np.arange(n)[keep])) < 1e-9

    # The apex of a narrow real peak is not a spike: this 13-point profile is the one at
    # 2.55 min in a 2026-06-26 Lu-177 run, whose apex (306) was flagged before 2026.10.14.
    y2 = rng.poisson(6, 300).astype(float)
    y2[144:157] = [33, 48, 72, 154, 197, 245, 306, 235, 207, 186, 156, 125, 101]
    y2[157:165] = [80, 60, 45, 30, 20, 14, 10, 8]
    y2[60] += 1000                                           # and a spike still is
    m2 = detect(y2)
    assert not m2[150], "narrow peak apex flagged as a spike"
    assert m2[60], "spike next to the narrow peak missed"
    print("spikes self-check OK")


if __name__ == "__main__":
    _self_check()
