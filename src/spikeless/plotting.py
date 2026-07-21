"""Publication-quality matplotlib figure builder.

The plot AREA is sized exactly in mm; the figure is that plus computed label margins. The same
Figure is rasterised on-screen (plotview) and used for export. Every dataset's curve tree is
walked and each Curve draws (when shown) its trace plus its artifacts — baseline, spike overlay,
peak markers/labels — through the Curve's Adjust transform.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

import numpy as np
from matplotlib.colors import to_hex, to_rgb, to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FixedLocator, MultipleLocator

from .adjust import apply_adjust
from .dataset import Curve, Dataset

_MAX_TICKS = 2000
PT_PER_MM = 2.834645669

BORDER_STYLES = {"long dash": (0, (5, 3)), "dash": (0, (3, 2)), "dot": (0, (1, 2)), "solid": "solid"}


@dataclass
class ExportBorder:
    on: bool = True
    color: str = "#808080"
    style: str = "long dash"
    width: float = 0.5


def _desaturate(hexcolor: str, factor: float = 0.4) -> str:
    try:
        r, g, b = to_rgb(hexcolor)
    except ValueError:
        return "#888888"
    h, li, s = colorsys.rgb_to_hls(r, g, b)
    return to_hex(colorsys.hls_to_rgb(h, min(1.0, li * 1.1), s * factor))


def _rel_lum(rgb) -> float:
    """WCAG relative luminance of an (r,g,b) triple in 0..1."""
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    hi, lo = sorted((_rel_lum(a), _rel_lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _readable(fg_hex: str, bg_hex: str, target: float = 3.0) -> str:
    """Keep fg's hue but shade it — darker on a light bg, lighter on a dark bg — until it clears
    `target` contrast against bg, so labels stay readable instead of washing out on the fill colour."""
    try:
        fg, bg = to_rgb(fg_hex), to_rgb(bg_hex)
    except ValueError:
        return fg_hex
    if _contrast(fg, bg) >= target:
        return fg_hex
    h, li, s = colorsys.rgb_to_hls(*fg)
    step = -0.07 if _rel_lum(bg) > 0.4 else 0.07
    cand = fg
    for _ in range(14):
        li = min(1.0, max(0.0, li + step))
        cand = colorsys.hls_to_rgb(h, li, s)
        if _contrast(cand, bg) >= target or li in (0.0, 1.0):
            break
    return to_hex(cand)


def _label_placement(px, py, xmin, xmax, ymin, ymax, mode, pad=3):
    """(dx, dy, ha, va) offset-points + alignment for a peak label. 'auto' keeps it inside the
    axes: a peak near the top edge is labelled to the side (left if also near the right edge)
    rather than above, where it would spill out of the plot."""
    if mode == "above":
        return 0, pad, "center", "bottom"
    if mode == "right":
        return pad, 0, "left", "center"
    if mode == "left":
        return -pad, 0, "right", "center"
    xr = (xmax - xmin) or 1.0
    yr = (ymax - ymin) or 1.0
    if py > ymin + 0.88 * yr:                 # near the top → move to the side
        if px > xmin + 0.85 * xr:             # also near the right edge → put it on the left
            return -pad, 0, "right", "center"
        return pad, 0, "left", "center"
    return 0, pad, "center", "bottom"


@dataclass
class AxisOptions:
    title: str = "Time (min)"
    unit: str = ""
    lw_pt: float = 0.5
    vmin: float | None = None
    vmax: float | None = None
    major: float | None = None
    grad_start: float | None = None
    grad_end: float | None = None
    minor_on: bool = False
    minor_n: int | None = None
    major_len_mm: float = 1.0
    minor_len_mm: float = 0.5
    tick_lw_pt: float = 0.5
    tick_lw_auto: bool = True
    tick_dir: str = "out"
    tick_font_family: str = "sans-serif"
    tick_font_size: float = 7.0
    title_font_family: str = "sans-serif"
    title_font_size: float = 8.0
    title_pad_mm: float = 1.2
    tick_label_pad_mm: float = 0.6
    grid_on: bool = False
    grid_color: str = "#c0c0c0"
    grid_style: str = "dotted"
    grid_width: float = 0.4


@dataclass
class PlotOptions:
    plot_w_mm: float = 80.0
    plot_h_mm: float = 40.0
    total_w_mm: float | None = None   # None = auto (plot area + label margins); else fixes figure width
    total_h_mm: float | None = None   # (plot area then shrinks to fit the total)
    crop_fills: bool = False          # erase fill areas where a curve passes (clean alpha overlaps)
    bg_color: str = "#ffffff"
    bg_alpha: float = 1.0
    outside_color: str = "#ffffff"
    outside_alpha: float = 0.0
    legend_loc: str = "upper right"
    legend_font_family: str = "sans-serif"
    legend_font_size: float = 7.0
    x: AxisOptions = field(default_factory=lambda: AxisOptions(title="Time (min)"))
    y: AxisOptions = field(default_factory=lambda: AxisOptions(title="Counts (cps)", unit="cps"))


_X_MAJOR_CANDIDATES = [0.25, 0.5, 1, 2, 5, 10, 15, 20, 30, 60]
_MINOR_BY_MAJOR = {1: 5, 5: 5, 2: 4, 10: 5, 20: 4, 15: 3, 30: 6, 60: 6, 0.5: 5, 0.25: 5}


def _auto_x_major(span, width_mm):
    max_ticks = max(2, width_mm / 14.0)
    for c in _X_MAJOR_CANDIDATES:
        if span / c <= max_ticks:
            return float(c)
    return float(_X_MAJOR_CANDIDATES[-1])


def _nice_major(span, size_mm, per_mm=12.0):
    if span <= 0:
        return 1.0
    target = max(2, size_mm / per_mm)
    raw = span / target
    mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 5, 10):
        if m * mag >= raw:
            return float(m * mag)
    return float(10 * mag)


def _minor_n(major, axis):
    return axis.minor_n or _MINOR_BY_MAJOR.get(major, 5)


# ---------------------------------------------------------------- curve helpers
def _y_adj(curve: Curve):
    return apply_adjust(curve.x, curve.y, curve.adjust, baseline=curve.baseline)


def _base_adj(curve: Curve):
    if curve.baseline is None:
        return None
    return apply_adjust(curve.x, curve.baseline, curve.adjust, baseline=curve.baseline)[0]


def _curve_needs(curve: Curve) -> bool:
    return (curve.shown or (curve.has_spikes and curve.spikes_group_shown)
            or (curve.peaks and curve.peaks_group_shown))


def _all_curves(datasets):
    for ds in datasets:
        yield from ds.curves()


def _curve_arrays(curve: Curve):
    arrs = []
    if _curve_needs(curve):
        arrs.append(_y_adj(curve)[0])
    if curve.baseline is not None and curve.baseline_shown:
        arrs.append(_base_adj(curve))
    return arrs


def _y_unit_label(datasets, opts):
    units = {_y_adj(c)[1] for c in _all_curves(datasets) if c.shown and len(c.y)}
    non_cps = units - {"Counts (cps)"}
    return next(iter(non_cps)) if (len(non_cps) == 1 and len(units) == 1) else opts.y.title


def _data_extents(datasets):
    curves = [c for c in _all_curves(datasets) if len(c.x) and _curve_arrays(c)]
    x_max = max((float(c.x[-1]) for c in curves), default=1.0)
    y_max = max((float(np.nanmax(a)) for c in curves for a in _curve_arrays(c)), default=1.0)
    return x_max, y_max


def resolve_limits(datasets, opts):
    x_max_data, y_max_data = _data_extents(datasets)
    xmin = 0.0 if opts.x.vmin is None else opts.x.vmin
    xmax = x_max_data if opts.x.vmax is None else opts.x.vmax
    ymin = 0.0 if opts.y.vmin is None else opts.y.vmin
    ymax = (y_max_data * 1.05) if opts.y.vmax is None else opts.y.vmax
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    return xmin, xmax, ymin, ymax


def auto_extents(datasets, opts):
    xmin, xmax, ymin, ymax = resolve_limits(datasets, opts)
    return {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax,
            "xmajor": _auto_x_major(xmax - xmin, opts.plot_w_mm),
            "ymajor": _nice_major(ymax - ymin, opts.plot_h_mm)}


def _margins_mm(opts, y_max):
    ndigits = max(1, len(f"{int(round(y_max)):d}")) if np.isfinite(y_max) else 4
    ytick_w = ndigits * opts.y.tick_font_size * 0.6 * 0.352777778
    left = (opts.y.major_len_mm + 1.0 + ytick_w + opts.y.title_pad_mm
            + opts.y.title_font_size * 0.352777778 + 1.5)
    bottom = (opts.x.major_len_mm + 1.0 + opts.x.tick_font_size * 0.352777778
              + opts.x.title_pad_mm + opts.x.title_font_size * 0.352777778 + 1.5)
    return max(left, 12.0), max(bottom, 10.0), 3.0, 3.0


def _apply_axis(ax, which, axis, vmin, vmax, span_mm):
    is_x = which == "x"
    axr = ax.xaxis if is_x else ax.yaxis
    span = vmax - vmin
    auto_major = _auto_x_major(span, span_mm) if is_x else _nice_major(span, span_mm)
    major = auto_major if axis.major is None else axis.major
    if major <= 0 or span / major > _MAX_TICKS:
        major = auto_major
    if axis.grad_start is not None or axis.grad_end is not None:
        start = vmin if axis.grad_start is None else axis.grad_start
        end = vmax if axis.grad_end is None else axis.grad_end
        if end > start and (end - start) / major <= _MAX_TICKS:
            axr.set_major_locator(FixedLocator(np.arange(start, end + major * 0.5, major)))
        else:
            axr.set_major_locator(MultipleLocator(major))
    else:
        axr.set_major_locator(MultipleLocator(major))
    if axis.minor_on:
        axr.set_minor_locator(MultipleLocator(major / max(1, _minor_n(major, axis))))
    tick_w = axis.lw_pt if axis.tick_lw_auto else axis.tick_lw_pt
    ax.tick_params(axis=which, which="major", direction=axis.tick_dir,
                   length=axis.major_len_mm * PT_PER_MM, width=tick_w, labelsize=axis.tick_font_size,
                   pad=axis.tick_label_pad_mm * PT_PER_MM)
    ax.tick_params(axis=which, which="minor", direction=axis.tick_dir,
                   length=axis.minor_len_mm * PT_PER_MM, width=tick_w)
    for lbl in (ax.get_xticklabels() if is_x else ax.get_yticklabels()):
        lbl.set_fontfamily(axis.tick_font_family)
        lbl.set_fontsize(axis.tick_font_size)
    if axis.grid_on:
        if not axis.minor_on:  # ensure minor gridlines exist even if minor ticks are off
            axr.set_minor_locator(MultipleLocator(major / max(1, _minor_n(major, axis))))
        ax.grid(True, which="both", axis=which, color=axis.grid_color,
                linestyle=axis.grid_style, linewidth=axis.grid_width, zorder=0)


class _LegendState:
    def __init__(self):
        self.show = False
        self.spike = False
        self.peak = False


def _draw_curve(ax, curve: Curve, limits, leg: _LegendState, crop=False, bg="#ffffff"):
    xmin, xmax, ymin, ymax = limits
    st = curve.style
    y_adj = _y_adj(curve)[0]
    base_adj = _base_adj(curve)
    # When cropping, the curve line rides ABOVE every fill (incl. peak AUC at z=3), and a same-shape
    # halo in the plot-background colour is drawn just beneath it, erasing any fill under the stroke
    # so alpha overlaps read cleanly (3.png). Otherwise the line keeps its normal z=2.
    line_z = 3.6 if crop else 2

    if curve.shown and st.fill and base_adj is not None:
        ax.fill_between(curve.x, y_adj, base_adj, color=st.fill_color, alpha=st.fill_alpha,
                        linewidth=0, zorder=1)
    if base_adj is not None and curve.baseline_shown:
        bcol = curve.baseline_viz.color or _desaturate(st.color)
        ax.plot(curve.x, base_adj, color=bcol, alpha=curve.baseline_viz.alpha, lw=st.line_width_pt,
                linestyle=curve.baseline_viz.linestyle, zorder=1.5)
        if len(curve.x) and float(np.nanmax(base_adj) - np.nanmin(base_adj)) < 1e-9:
            c = float(np.nanmin(base_adj))  # flat baseline → annotate its level as y = c
            ax.annotate(f"y = {c:.4g}", (curve.x[-1], c), textcoords="offset points",
                        xytext=(-2, 2), ha="right", va="bottom", fontsize=6.0, color=bcol, zorder=1.6)
    if curve.shown:
        if crop:  # opaque halo the width of the stroke (+ a hair) cuts the fill around the line
            ax.plot(curve.x, y_adj, color=to_rgba(bg, 1.0), lw=st.line_width_pt + 0.8,
                    linestyle="solid", solid_capstyle="round", zorder=line_z - 0.1)
        lbl = (curve.legend_label or curve.name) if curve.show_legend else "_nolegend_"
        ax.plot(curve.x, y_adj, color=st.color, alpha=st.alpha, lw=st.line_width_pt,
                linestyle=st.linestyle, zorder=line_z, label=lbl)
        leg.show = leg.show or curve.show_legend

    if curve.has_spikes and curve.spikes_group_shown:
        idxs = curve.spike_indices()
        mask = curve.spike_shown if curve.spike_shown is not None else np.ones(len(idxs), bool)
        vis = idxs[mask[:len(idxs)]]
        v = curve.spike_viz
        lbl = "Spikes" if (v.in_legend and not leg.spike) else "_nolegend_"
        if v.mode == "segment":
            for k, i in enumerate(vis):
                sl = slice(max(0, i - 1), min(len(curve.x), i + 2))
                ax.plot(curve.x[sl], y_adj[sl], color=v.color, lw=st.line_width_pt, zorder=4,
                        label=lbl if k == 0 else "_nolegend_")
        elif len(vis):
            ax.plot(curve.x[vis], y_adj[vis], linestyle="none", marker="o", ms=3,
                    mfc=v.color, mec=v.color, zorder=4, label=lbl)
        if v.in_legend and len(vis):
            leg.spike = True
            leg.show = True

    if curve.peaks and curve.peaks_group_shown:
        v = curve.peak_viz
        vis = [pk for pk in curve.peaks if pk.shown]
        if v.mode == "markers":
            first = True
            for pk in vis:  # per-peak so pk.color can override the group colour
                col = pk.color or v.color
                lbl = "Peaks" if (v.in_legend and not leg.peak and first) else "_nolegend_"
                ax.plot([curve.x[pk.apex]], [y_adj[pk.apex]], linestyle="none", marker=v.marker,
                        ms=5, mfc=col, mec=col, zorder=5, label=lbl)
                first = False
            if v.in_legend and vis:
                leg.peak, leg.show = True, True
        else:  # fill each peak's AUC region (curve ↔ its local/curve baseline)
            first = True
            for pk in vis:
                sl = slice(pk.left, pk.right + 1)
                xs, ys = curve.x[sl], y_adj[sl]
                if curve.peak_local_baseline or base_adj is None:
                    b = np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]])
                else:
                    b = base_adj[sl]
                lbl = "Peaks" if (v.in_legend and not leg.peak and first) else "_nolegend_"
                ax.fill_between(xs, ys, b, color=(pk.color or v.color), alpha=v.alpha, linewidth=0,
                                zorder=3, label=lbl)
                first = False
            if v.in_legend and vis:
                leg.peak, leg.show = True, True
        for pk in vis:
            txt = _peak_label(curve, pk)
            if txt:
                px, py = curve.x[pk.apex], y_adj[pk.apex]
                col = v.label_color or _readable(pk.color or v.color, bg)
                dx, dy, ha, va = _label_placement(px, py, xmin, xmax, ymin, ymax, v.label_pos)
                ax.annotate(txt, (px, py), textcoords="offset points", xytext=(dx, dy),
                            ha=ha, va=va, fontsize=v.label_size, color=col, zorder=6)


def _peak_label(curve, pk):
    mode = curve.annotate if pk.annotate is None else pk.annotate  # per-peak overrides the group
    parts = []
    if mode in ("rt", "both"):
        parts.append(f"Rt {pk.rt:.2f}")
    if mode in ("auc", "both"):
        parts.append(f"{pk.pct:.0f}%")
    return "\n".join(parts)


def build_figure(datasets: list[Dataset], opts: PlotOptions | None = None,
                 border: ExportBorder | None = None) -> Figure:
    opts = opts or PlotOptions()
    xmin, xmax, ymin, ymax = resolve_limits(datasets, opts)

    left, bottom, right, top = _margins_mm(opts, ymax)
    # total size = plot area + label margins (auto); or the user fixes the total and the plot area
    # shrinks to fit inside it.
    plot_w = opts.plot_w_mm if opts.total_w_mm is None else max(5.0, opts.total_w_mm - left - right)
    plot_h = opts.plot_h_mm if opts.total_h_mm is None else max(5.0, opts.total_h_mm - bottom - top)
    fig_w = plot_w + left + right
    fig_h = plot_h + bottom + top
    fig = Figure(figsize=(fig_w / 25.4, fig_h / 25.4))
    fig.patch.set_facecolor(to_rgba(opts.outside_color, opts.outside_alpha))
    if border is not None and border.on:
        ins_x, ins_y = 1.0 / fig_w, 1.0 / fig_h
        fig.add_artist(Rectangle((ins_x, ins_y), 1 - 2 * ins_x, 1 - 2 * ins_y,
                                 transform=fig.transFigure, fill=False, edgecolor=border.color,
                                 linestyle=BORDER_STYLES.get(border.style, "solid"),
                                 linewidth=border.width, zorder=10))
    ax = fig.add_axes([left / fig_w, bottom / fig_h, plot_w / fig_w, plot_h / fig_h])
    ax.set_facecolor(to_rgba(opts.bg_color, opts.bg_alpha))

    leg = _LegendState()
    for c in _all_curves(datasets):
        _draw_curve(ax, c, (xmin, xmax, ymin, ymax), leg, crop=opts.crop_fills, bg=opts.bg_color)

    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_linewidth(opts.x.lw_pt if side == "bottom" else opts.y.lw_pt)
    _apply_axis(ax, "x", opts.x, xmin, xmax, plot_w)
    _apply_axis(ax, "y", opts.y, ymin, ymax, plot_h)
    ax.set_xlabel(opts.x.title, fontfamily=opts.x.title_font_family,
                  fontsize=opts.x.title_font_size, labelpad=opts.x.title_pad_mm * PT_PER_MM)
    ax.set_ylabel(_y_unit_label(datasets, opts), fontfamily=opts.y.title_font_family,
                  fontsize=opts.y.title_font_size, labelpad=opts.y.title_pad_mm * PT_PER_MM)
    if leg.show:
        ax.legend(loc=opts.legend_loc, frameon=False,
                  prop={"family": opts.legend_font_family, "size": opts.legend_font_size})
    return fig


def _self_check():
    x = np.arange(600) / 60.0
    y = 8 + 100 * np.exp(-0.5 * ((np.arange(600) - 300) / 20) ** 2)
    ds = Dataset(root=Curve(x=x, y=y))
    fig = build_figure([ds])
    ax = fig.axes[0]
    bb = ax.get_position()
    assert abs(bb.width * fig.get_figwidth() * 25.4 - 80) < 0.5
    assert abs(bb.height * fig.get_figheight() * 25.4 - 40) < 0.5
    print("plotting self-check OK")


if __name__ == "__main__":
    _self_check()
