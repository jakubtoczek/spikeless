"""Individual-peak detection and metrics (Rt, AUC, %) for radio-HPLC traces.

Detection is scipy.signal.find_peaks (prominence); integration bounds run apex-to-valley
(the low point between each peak and its neighbour), then trim inward to the peak's feet so
the bounds hug the real peak rather than the narrow, prominence-truncated peak_widths span.
Metrics: retention time (apex x), AUC above a baseline, and each peak's % of the group total.
The baseline under a peak is either a local drift line between the peak's bounds (default) or
the curve's detected baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from .dataset import Peak

try:  # NumPy 2 renamed trapz -> trapezoid
    from numpy import trapezoid as _trapz
except ImportError:  # NumPy < 2
    from numpy import trapz as _trapz


@dataclass
class PeakParams:
    min_prominence: float = 0.0    # 0 => auto (5% of signal range)
    min_height: float | None = None
    min_distance: int = 1
    local_baseline: bool = False   # integrate above a local drift line between each peak's bounds (off by default)


def detect_peaks(y: np.ndarray, baseline: np.ndarray | None = None,
                 params: PeakParams | None = None) -> list[Peak]:
    p = params or PeakParams()
    sig = np.asarray(y, dtype=float)
    if baseline is not None:
        sig = sig - np.asarray(baseline, dtype=float)
    n = len(sig)
    if n < 3:
        return []
    prom = p.min_prominence
    if prom <= 0:
        rng = float(np.nanmax(sig) - np.nanmin(sig))
        prom = 0.05 * rng if rng > 0 else 1e-9
    apexes, _ = find_peaks(sig, prominence=max(prom, 1e-9), height=p.min_height,
                           distance=max(1, int(p.min_distance)))
    if len(apexes) == 0:
        return []
    noise = _noise(sig)
    out = []
    for k, a in enumerate(apexes):
        a = int(a)
        left, right = _peak_bounds(sig, a, noise,
                                   lo=0 if k == 0 else int(apexes[k - 1]),
                                   hi=n - 1 if k == len(apexes) - 1 else int(apexes[k + 1]))
        out.append(Peak(apex=a, left=left, right=right))
    return out


def _noise(sig):
    """Robust baseline noise scale (σ) from the median absolute deviation. Most samples are
    baseline, so this tracks the noise floor, not the peaks."""
    med = float(np.median(sig))
    mad = float(np.median(np.abs(sig - med)))
    return max(1.4826 * mad, 1e-9)


def _peak_bounds(sig, apex, noise, lo, hi, k=3.5, min_frac=0.01):
    """Integration bounds for one peak: the valley on each side (lowest point between the apex
    and its neighbouring apex), then the foot found by scanning **from the valley inward** to the
    first sample rising above a foot level set a few noise-σ above the valley floor. A noise-based
    (absolute) threshold — not a fraction of peak height — keeps sharp tall peaks from being clipped
    and short peaks from swallowing baseline noise. Scanning inward means a noise dip on the flank
    can't stop the bound short, so peaks span their real width."""
    n = len(sig)
    left_v = lo + int(np.argmin(sig[lo:apex + 1]))
    right_v = apex + int(np.argmin(sig[apex:hi + 1]))
    floor = max(float(sig[left_v]), float(sig[right_v]))
    thr = floor + max(k * noise, min_frac * (float(sig[apex]) - floor))
    left = left_v
    while left < apex and sig[left] <= thr:
        left += 1
    left = max(left_v, left - 1)      # step back to include the foot itself
    right = right_v
    while right > apex and sig[right] <= thr:
        right -= 1
    right = min(right_v, right + 1)
    if right <= left:
        left, right = max(0, apex - 1), min(n - 1, apex + 1)
    return left, right


def _local_base(xs, ys):
    """Linear drift baseline between the two peak bounds."""
    return np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]])


def _skew(xs, w):
    """Moment skewness of the mass distribution w over positions xs."""
    tot = float(np.sum(w))
    if tot <= 0:
        return 0.0
    mean = float(np.sum(xs * w) / tot)
    var = float(np.sum(((xs - mean) ** 2) * w) / tot)
    if var <= 0:
        return 0.0
    m3 = float(np.sum(((xs - mean) ** 3) * w) / tot)
    return m3 / var ** 1.5


def analyze_peaks(x: np.ndarray, y: np.ndarray, peaks: list[Peak],
                  baseline: np.ndarray | None = None, local: bool = True):
    """Fill each peak's metrics (rt, bounds, y_max, auc, skew), then pct of the group total."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    total = 0.0
    for pk in peaks:
        sl = slice(pk.left, pk.right + 1)
        xs, ys = x[sl], y[sl]
        pk.rt = float(x[pk.apex])
        pk.x_start, pk.x_end = float(x[pk.left]), float(x[pk.right])
        pk.length = pk.x_end - pk.x_start
        if len(xs) < 2:
            pk.y_max = float(y[pk.apex])
            pk.auc = pk.skew = 0.0
            continue
        if local or baseline is None:
            base = _local_base(xs, ys)
            base_apex = float(np.interp(x[pk.apex], [xs[0], xs[-1]], [ys[0], ys[-1]]))
        else:
            base = np.asarray(baseline, float)[sl]
            base_apex = float(np.asarray(baseline, float)[pk.apex])
        above = np.clip(ys - base, 0, None)
        pk.y_max = float(y[pk.apex] - base_apex)
        pk.auc = float(_trapz(above, xs))
        pk.skew = _skew(xs, above)
        total += pk.auc
    for pk in peaks:
        pk.pct = (pk.auc / total * 100.0) if total > 0 else 0.0


def _self_check():
    x = np.arange(1000) / 60.0
    y = 5.0 + np.zeros(1000)
    for c in (200, 500, 800):
        y += 100.0 * np.exp(-0.5 * ((np.arange(1000) - c) / 8.0) ** 2)
    pks = detect_peaks(y)
    assert len(pks) == 3, len(pks)
    analyze_peaks(x, y, pks)
    assert all(pk.auc > 0 for pk in pks), [pk.auc for pk in pks]
    assert abs(sum(pk.pct for pk in pks) - 100.0) < 1e-6, sum(pk.pct for pk in pks)
    assert abs(pks[0].rt - 200 / 60.0) < 0.1, pks[0].rt
    # bounds must hug the peak, not the truncated tip: sigma=8, so a real peak spans well
    # over ±2 sigma (~32 samples). Guards the "peaks too narrow" regression.
    assert all((pk.right - pk.left) >= 24 for pk in pks), [(pk.right - pk.left) for pk in pks]
    print("peaks self-check OK")


if __name__ == "__main__":
    _self_check()
