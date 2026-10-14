"""A run: one radio-HPLC chromatogram, the spikes excluded from it, its background and its
regions (the integrated peaks).

The recorded count rate is never changed. The trace results are computed on is derived from
it each time: the excluded spikes bridged linearly between their neighbours, then — when the
run's isotope is ticked for it in Options › Isotopes — decay-corrected to the run start.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from .adjust import decay_factor, decay_on, estimate_baseline, lookup_half_life_s
from .spikes import SpikeParams, detect, remove

_ids = itertools.count(1)
COLORS = ["#1f4e79", "#c0392b", "#2e8b57", "#8e44ad", "#d35400", "#16a085", "#7f8c8d"]


@dataclass
class Region:
    start: float                  # min
    end: float
    name: str = ""                # typed by hand; else from the run's method; else "peak N (Rt)"
    under: str = "background"     # what is subtracted: "background" | "line" (between the ends)
    how: str = "auto"             # "auto" (Find peaks) | "drawn" | "moved" (auto, then adjusted)
    note: str = ""
    color: str | None = None      # None: the run's colour


@dataclass(eq=False)     # a run is itself: `in`, `index`, `remove` by identity
class Run:
    x: np.ndarray                 # min from the run start
    y: np.ndarray                 # count rate as recorded, cps
    dt_s: float = 1.0
    name: str = ""
    file: str = ""
    sha256: str = ""              # of the file as read, to trace a report to it
    run_datetime: str = ""
    headers: list = field(default_factory=list)
    signal_col: int = 1
    molecule: str = ""
    isotope: str = ""
    method: str = ""              # HPLC method (Options › Methods): names the regions
    conditions: str = ""          # free text, a line each
    color: str = COLORS[0]
    shown: bool = True
    spike_params: SpikeParams = field(default_factory=SpikeParams)
    spikes: np.ndarray | None = None     # flagged by the rule (bool per point)
    kept: list = field(default_factory=list)   # flagged points put back by the user (indices)
    bg_mode: str = "auto"         # "auto" mean outside the regions | "stretch" | "drift"
    bg_stretch: list | None = None       # [from, to] min, for "stretch"
    bg_drift: str = "snip"        # "snip" | "arpls", for "drift"
    bg_n: int = 40                # SNIP half-width, points
    regions: list = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_ids))

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)

    # ---------------- spikes ----------------
    def detect_spikes(self):
        """Flag spikes with the run's rule; points put back stay back if still flagged."""
        self.spikes = detect(self.y, self.spike_params)
        self.kept = [i for i in self.kept if self.spikes[i]]

    def excluded(self) -> np.ndarray:
        m = np.zeros(len(self.y), bool) if self.spikes is None else self.spikes.copy()
        m[self.kept] = False
        return m

    def spike_list(self) -> list[int]:
        return [] if self.spikes is None else np.flatnonzero(self.spikes).tolist()

    # ---------------- the trace results use ----------------
    def half_life_s(self) -> float | None:
        return lookup_half_life_s(self.isotope)

    def decayed(self) -> bool:
        return bool(decay_on(self.isotope) and self.half_life_s())

    def trace(self, raw: bool = False) -> np.ndarray:
        """Spikes bridged (unless raw), then decay-corrected to the run start if its isotope
        is ticked for that."""
        y = self.y.copy() if raw else remove(self.y, self.excluded())
        if self.decayed():
            y = y * decay_factor(self.x, self.half_life_s())
        return y

    def in_regions(self) -> np.ndarray:
        m = np.zeros(len(self.x), bool)
        for r in self.regions:
            m |= (self.x >= r.start) & (self.x <= r.end)
        return m

    def background(self, y: np.ndarray | None = None) -> tuple[np.ndarray, str]:
        """(background per point, cps; how it was obtained, in words)."""
        y = self.trace() if y is None else y
        if self.bg_mode == "drift":
            b = estimate_baseline(y, self.bg_drift, self.bg_n)
            how = ("SNIP, half-width %d points" % self.bg_n if self.bg_drift == "snip"
                   else "arPLS") + " (follows a drifting background)"
            return b, how
        if self.bg_mode == "stretch" and self.bg_stretch:
            a, b = sorted(self.bg_stretch)
            sel = (self.x >= a) & (self.x <= b)
            if sel.sum() >= 3:
                return (np.full(len(y), float(np.mean(y[sel]))),
                        f"mean of {a:.2f}–{b:.2f} min")
        out = ~self.in_regions()
        v = clipped_mean(y[out] if out.sum() >= 3 else y, self.dt_s)
        return np.full(len(y), v), "mean of the points outside the regions"


def clipped_mean(v: np.ndarray, dt_s: float) -> float:
    """Mean of a background stretch, leaving out what rises more than 4 Poisson σ above its
    median (a peak no region holds yet). The mean, not the median: the median of Poisson
    counts at ~7 cps sits up to 0.5 cps low."""
    med = float(np.median(v))
    lim = med + 4 * np.sqrt(max(med, 1.0) / dt_s)
    v = v[v <= lim]
    return float(np.mean(v)) if v.size else med


def new_run(x, y, dt_s, **kw) -> Run:
    run = Run(x=x, y=y, dt_s=dt_s, **kw)
    run.detect_spikes()
    return run
