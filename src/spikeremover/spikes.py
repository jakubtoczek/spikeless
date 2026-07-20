"""Single-point spike detection (Hampel filter) and removal for radio-HPLC signals.

A spike is one timepoint whose value sits far above the local median. The Hampel filter
(rolling median + MAD) is local, so it flags a spike even when it rides on a genuine
chromatographic peak, while leaving the (multi-point) peak itself untouched. Removal
replaces flagged points by linear interpolation from their nearest clean neighbors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter

_MAD_TO_SIGMA = 1.4826  # MAD -> std for normally distributed data


@dataclass
class SpikeParams:
    window: int = 7  # rolling window size (odd); larger = smoother median reference
    n_sigma: float = 5.0  # threshold in robust std units
    max_width: int = 1  # max consecutive points a spike may span (keeps real peaks safe)
    positive_only: bool = True  # only flag upward excursions (spikes are high cps)
    poisson_floor: bool = True  # floor the noise scale at sqrt(median): correct for cps counting data


def _limit_run_width(mask: np.ndarray, max_width: int) -> np.ndarray:
    """Keep only True-runs no longer than max_width (drops wide excursions = real peaks)."""
    out = mask.copy()
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if (j - i) > max_width:
                out[i:j] = False
            i = j
        else:
            i += 1
    return out


def detect(y: np.ndarray, params: SpikeParams | None = None) -> np.ndarray:
    """Return a boolean mask, True where y has a spike."""
    p = params or SpikeParams()
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return np.zeros(len(y), dtype=bool)
    win = max(3, p.window | 1)  # force odd, >= 3

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
    candidate = excess > p.n_sigma * sigma
    return _limit_run_width(candidate, p.max_width)


def remove(y: np.ndarray, mask: np.ndarray, method: str = "linear") -> np.ndarray:
    """Return a copy of y with masked points replaced by interpolation of clean neighbors.

    method:
      "linear" — straight line between the nearest clean points (for a single-point spike
                 that is exactly n-1 -> n+1). Safe: cannot overshoot.
      "pchip"  — monotone cubic (PCHIP). Smoother across multi-point gaps and, unlike a plain
                 cubic spline, will not overshoot into ringing on a peak flank.
    """
    y = np.asarray(y, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return y.copy()
    out = y.copy()
    idx = np.arange(len(y))
    clean = ~mask
    if clean.sum() < 2:
        return out  # nothing reliable to interpolate from
    if method == "pchip":
        from scipy.interpolate import PchipInterpolator
        out[mask] = PchipInterpolator(idx[clean], y[clean], extrapolate=True)(idx[mask])
    else:
        out[mask] = np.interp(idx[mask], idx[clean], y[clean])
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

    pch = remove(y, mask, method="pchip")
    assert abs(pch[120] - baseline[120]) < 6, pch[120]      # pchip also restores baseline
    assert pch[200] == y[200], "apex changed by pchip removal"
    print("spikes self-check OK")


if __name__ == "__main__":
    _self_check()
