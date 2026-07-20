"""Data model: a Dataset (metadata) owning a recursive tree of Curves.

A Curve is the plotted unit (original, or a processed child: spikeless, decay-corrected …).
Each Curve carries its own optional artifacts — a spike overlay, a baseline, and detected
peaks — and may have child Curves. Processing always acts on one selected Curve, so a
spikeless curve legitimately finds no spikes, peaks can be detected on any curve, etc.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

import numpy as np

from .adjust import AdjustParams
from .viz import BaselineViz, PeakViz, SpikeViz

_ids = itertools.count(1)


@dataclass
class Style:
    color: str = "#1f4e79"
    alpha: float = 1.0
    fill_color: str = "#1f4e79"
    fill_alpha: float = 0.15
    fill: bool = False           # only meaningful with a baseline (fills baseline↔curve)
    line_width_pt: float = 0.5
    linestyle: str = "solid"


@dataclass
class Condition:
    """A user-added test condition: a free note (label empty) or a label/value pair."""

    label: str = ""
    value: str = ""

    def text(self) -> str:
        return f"{self.label}: {self.value}" if self.label else self.value


@dataclass
class Peak:
    apex: int          # apex sample index
    left: int          # integration bound (sample index)
    right: int
    shown: bool = True
    name: str = ""
    # metrics filled by analyze_peaks:
    rt: float = 0.0        # retention time = apex x (min)
    x_start: float = 0.0   # left bound (min)
    x_end: float = 0.0     # right bound (min)
    length: float = 0.0    # x_end - x_start (min)
    y_max: float = 0.0     # apex value above baseline
    auc: float = 0.0       # area above the (local or curve) baseline
    pct: float = 0.0       # % of the group's total AUC
    skew: float = 0.0      # moment skewness of the peak region


@dataclass
class Curve:
    x: np.ndarray
    y: np.ndarray
    name: str = "original"
    kind: str = "original"       # original | spikeless | decay | spikeless+decay | …
    shown: bool = True
    id: int = field(default_factory=lambda: next(_ids))
    legend_label: str = ""
    show_legend: bool = False
    style: Style = field(default_factory=Style)
    adjust: AdjustParams = field(default_factory=AdjustParams)  # normalization (display)

    # spikes overlay
    spike_mask: np.ndarray | None = None
    spike_shown: np.ndarray | None = None   # per-spike visibility (parallel to spike indices)
    spikes_group_shown: bool = True
    spike_viz: SpikeViz = field(default_factory=SpikeViz)

    # baseline
    baseline: np.ndarray | None = None
    baseline_shown: bool = True
    baseline_viz: BaselineViz = field(default_factory=BaselineViz)

    # peaks
    peaks: list[Peak] | None = None
    peaks_group_shown: bool = True
    peak_viz: PeakViz = field(default_factory=PeakViz)
    peak_local_baseline: bool = True   # drift baseline (line between each peak's bounds)
    annotate: str = "none"             # on-graph labels: none | rt | auc | both

    children: list["Curve"] = field(default_factory=list)

    def __post_init__(self):
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)

    @property
    def has_spikes(self) -> bool:
        return self.spike_mask is not None and bool(self.spike_mask.any())

    def spike_indices(self) -> np.ndarray:
        return np.flatnonzero(self.spike_mask) if self.has_spikes else np.array([], dtype=int)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def find(self, cid: int) -> "Curve | None":
        for c in self.walk():
            if c.id == cid:
                return c
        return None

    def parent_of(self, cid: int) -> "Curve | None":
        for c in self.walk():
            if any(ch.id == cid for ch in c.children):
                return c
        return None


@dataclass
class Meta:
    name: str = ""
    original_filename: str = ""
    molecule: str = ""
    radioisotope: str = ""


@dataclass
class Dataset:
    """Metadata container (no curve of its own) owning the tree of Curves."""

    root: Curve
    run_name: str = ""
    run_datetime: str = ""
    dt_s: float = 1.0
    headers: list[str] = field(default_factory=list)
    signal_col: int = 1
    meta: Meta = field(default_factory=Meta)
    conditions: list[Condition] = field(default_factory=list)
    # decay-correction settings (Apply decay ⚙)
    half_life_s: float | None = None
    decay_ref_offset_s: float = 0.0     # reference time, seconds from run start (0 = run start)
    decay_ref_label: str = "run start"
    id: int = field(default_factory=lambda: next(_ids))

    def curves(self):
        return list(self.root.walk())

    def find_curve(self, cid: int) -> Curve | None:
        return self.root.find(cid)

    def parent_of(self, cid: int) -> Curve | None:
        return self.root.parent_of(cid)


def new_id() -> int:
    return next(_ids)


def new_curve_from(src: Curve, y: np.ndarray, name: str, kind: str, color: str | None = None) -> Curve:
    """A fresh processed child curve derived from `src` (same x, new y)."""
    st = copy.deepcopy(src.style)
    if color:
        st.color = st.fill_color = color
    return Curve(x=src.x.copy(), y=np.asarray(y, float), name=name, kind=kind,
                 style=st, adjust=copy.deepcopy(src.adjust), legend_label=name)
