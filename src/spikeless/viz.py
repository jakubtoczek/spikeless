"""Per-artifact visualisation options (plain dataclasses, no deps → importable anywhere)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpikeViz:
    """How detected spikes are drawn."""

    mode: str = "points"      # "points" (dots) | "segment" (recolour n-1..n+1)
    color: str = "#ff2020"
    in_legend: bool = False


@dataclass
class CurveViz:
    """How the spikeless (corrected) curve is drawn (unused legacy; curves use Style)."""

    color: str = "#00a000"
    alpha: float = 1.0
    linestyle: str = "solid"
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
