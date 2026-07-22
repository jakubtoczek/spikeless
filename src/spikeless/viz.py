"""Per-artifact visualisation options (plain dataclasses, no deps → importable anywhere)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpikeViz:
    """How detected spikes are drawn."""

    mode: str = "segment"     # "segment" (recolour n-1..n+1) | "points" (dots) | "vline"
    color: str = "#ff2020"    # "vline": vertical line from the interpolated point up to the spike max
    in_legend: bool = False


@dataclass
class BaselineViz:
    """How a detected baseline is drawn. color None => desaturated data-curve colour."""

    color: str | None = None
    alpha: float = 0.7
    linestyle: str = "dashed"


@dataclass
class PeakViz:
    """How peaks are drawn — filled AUC region by default, or markers at the apex."""

    mode: str = "fill"        # "fill" (shade the AUC) | "markers"
    color: str = "#d000d0"
    alpha: float = 0.30
    marker: str = "v"
    in_legend: bool = False
    # on-graph label styling
    label_size: float = 7.0
    label_color: str | None = None   # None => auto: a readable shade of the peak colour on the bg
    label_pos: str = "auto"          # "auto" | "above" | "right" | "left"
