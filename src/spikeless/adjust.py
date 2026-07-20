"""Non-destructive signal adjustment: decay correction, baseline, normalization.

Applied at plot/analysis time from a Dataset's `adjust` params, so nothing here mutates
the loaded data — changing the settings and changing them back returns the original trace.

Pipeline order:  raw/spikeless  ->  decay correct  ->  (baseline subtract -> normalize)

Baseline estimation is a small registry (BASELINE_METHODS) so more methods can be added
without touching callers. It ships with the two basics (minimum, average of first N points);
drift-aware / segmented / asymmetric-least-squares estimators slot in as new entries that
return a per-point array instead of a scalar — apply_adjust already handles either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_LN2 = np.log(2.0)

# ---------------------------------------------------------------- half-lives
# Half-life in SECONDS for isotopes common in radio-HPLC. Keyed as ELEMENT+MASS
# (e.g. "LU177"). Lookup normalizes "Lu-177", "177Lu", "lu 177" to the same key.
HALF_LIVES_S: dict[str, float] = {
    "F18": 109.771 * 60,
    "GA68": 67.71 * 60,
    "SC44": 3.97 * 3600,
    "CU64": 12.701 * 3600,
    "CU67": 61.83 * 3600,
    "TC99M": 6.0067 * 3600,
    "TCM99": 6.0067 * 3600,  # alias: 'Tc-99m' normalizes letters->TCM
    "I123": 13.2234 * 3600,
    "IN111": 67.313 * 3600,
    "I124": 4.1760 * 86400,
    "TB161": 6.89 * 86400,
    "LU177": 6.647 * 86400,
    "I131": 8.0252 * 86400,
    "ZR89": 78.41 * 3600,
    "Y90": 64.053 * 3600,
    "AC225": 9.920 * 86400,
    "PB212": 10.622 * 3600,
    "RA223": 11.4377 * 86400,
}

_TIME_UNITS_S = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}

# Curated dropdown list: (display name, half-life in HOURS). Order as provided.
ISOTOPES = [
    ("⁹⁹ᵐTc", 6.007), ("²⁰¹Tl", 73.08), ("¹¹¹In", 67.296), ("¹²³I", 13.223),
    ("¹²⁵I", 1425.6), ("¹⁸F", 1.829), ("⁶⁸Ga", 1.12865), ("⁶⁴Cu", 12.9),
    ("⁹⁰Y", 64.6), ("¹⁷⁷Lu", 159.46536), ("¹⁶¹Tb", 166.872),
]
ISOTOPE_HL_S = {name: hours * 3600.0 for name, hours in ISOTOPES}


def lookup_half_life_s(isotope: str) -> float | None:
    """Half-life (s) for an isotope name (dropdown display or free text), or None."""
    if not isotope:
        return None
    if isotope in ISOTOPE_HL_S:  # exact dropdown display name (e.g. "¹⁷⁷Lu")
        return ISOTOPE_HL_S[isotope]
    letters = "".join(re.findall(r"[A-Za-z]+", isotope)).upper()
    digits = "".join(re.findall(r"\d+", isotope))
    if letters and digits:
        hit = HALF_LIVES_S.get(letters + digits)
        if hit:
            return hit
    key = "".join(ch for ch in isotope.upper() if ch.isalnum())
    return HALF_LIVES_S.get(key)


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


# key -> estimator(y, n=...) returning a scalar OR a per-point array.
# Extend here (rolling minimum, ALS, segmented/drift) — apply_adjust broadcasts either shape.
BASELINE_METHODS = {
    "none": _baseline_none,
    "min": _baseline_min,
    "first_n": _baseline_first_n,
}

BASELINE_LABELS = {"none": "None", "min": "Minimum", "first_n": "Average of first N points"}


def estimate_baseline(y: np.ndarray, method: str = "min", n: int = 20) -> np.ndarray:
    """Return the baseline as a full-length array (scalar methods are broadcast)."""
    y = np.asarray(y, dtype=float)
    fn = BASELINE_METHODS.get(method, _baseline_none)
    b = fn(y, n=n)
    return np.asarray(b, dtype=float) * np.ones_like(y) if np.ndim(b) == 0 else np.asarray(b, float)


# ---------------------------------------------------------------- params + apply
@dataclass
class AdjustParams:
    """Per-dataset, reversible display/analysis transform. Default = identity (raw cps)."""

    decay_correct: bool = False
    half_life_s: float | None = None
    ref_offset_s: float = 0.0        # reference time, seconds from run start (0 = run start)
    ref_label: str = "run start"     # human description, for log/report
    norm_mode: str = "cps"           # "cps" | "pct_max" | "pct_total"
    baseline_method: str = "min"     # key in BASELINE_METHODS (used by pct_* modes)
    baseline_n: int = 20

    @property
    def is_identity(self) -> bool:
        return not self.decay_correct and self.norm_mode == "cps"


_UNIT_LABEL = {"cps": "Counts (cps)", "pct_max": "% of max", "pct_total": "% of total"}


def apply_adjust(x_min: np.ndarray, y: np.ndarray, params: AdjustParams | None,
                 unit: str = "cps", baseline: np.ndarray | None = None) -> tuple[np.ndarray, str]:
    """Return (adjusted_y, y_unit_label). Pure — does not touch the inputs.

    For %-modes the baseline subtracted is the curve's detected `baseline` if given, else the
    fallback estimate (params.baseline_method). Decay is applied here only if params say so;
    normally decay is its own curve, so params.decay_correct stays False.
    """
    y = np.asarray(y, dtype=float).copy()
    p = params or AdjustParams()

    if p.decay_correct and p.half_life_s:
        y = y * decay_factor(x_min, p.half_life_s, p.ref_offset_s)

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

    # lookup normalizes formatting
    assert lookup_half_life_s("Lu-177") == lookup_half_life_s("177Lu") == HALF_LIVES_S["LU177"]
    assert lookup_half_life_s("unobtainium") is None
    print("adjust self-check OK")


if __name__ == "__main__":
    _self_check()
