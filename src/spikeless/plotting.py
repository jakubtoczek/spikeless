"""The chromatogram as a matplotlib figure: the screen plot and the exported one.

draw() puts the runs on an axes — each shown run's trace (spikes excluded and bridged), and
as asked its regions (shaded between the trace and what lies under them, labelled), its
background, its excluded spikes, its trace as recorded. The screen canvas calls it on an axes
the size of the window; build_figure() on a figure sized in mm for export, where the plot AREA
is exactly the size asked and the figure is that plus the label margins.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

import numpy as np
from matplotlib.colors import to_hex, to_rgb, to_rgba
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, MultipleLocator

_MAX_TICKS = 2000
PT_PER_MM = 2.834645669
Y_TITLE = "Count rate (cps)"
LABELS = {"none": "None", "name": "Name", "pct": "% of total", "both": "Name and %"}
# (a region with no name of its own — no typed name, no method window — shows only its %)


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
    """The figure as exported (Figure window). stack, pct_max and region_labels apply on
    screen too, so the screen shows what the figure will."""

    plot_w_mm: float = 80.0
    plot_h_mm: float = 40.0
    total_w_mm: float | None = None   # None = auto (plot area + label margins); else fixes figure width
    total_h_mm: float | None = None   # (plot area then shrinks to fit the total)
    bg_color: str = "#ffffff"
    bg_alpha: float = 1.0
    outside_color: str = "#ffffff"
    outside_alpha: float = 0.0
    legend: bool = True               # run names, when more than one run is shown
    legend_loc: str = "upper right"
    legend_font_family: str = "sans-serif"
    legend_font_size: float = 7.0
    line_width_pt: float = 0.75
    show_regions: bool = True
    region_labels: str = "both"       # a key of LABELS
    label_size: float = 7.0
    region_alpha: float = 0.3
    show_background: bool = False
    show_spikes: bool = False
    show_raw: bool = False
    stack: bool = False               # overlays one above the other, background subtracted
    pct_max: bool = False             # each run as % of its highest point above background
    x: AxisOptions = field(default_factory=lambda: AxisOptions(title="Time (min)"))
    y: AxisOptions = field(default_factory=lambda: AxisOptions(title=Y_TITLE, unit="cps"))


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


# ---------------- runs
def _scales(runs, opts):
    """Per shown run: (background, multiplier, offset) so that the drawn value is
    (y - b) * k + off when stacked or in % of max, else y as is (b drawn as its own line)."""
    out, off = {}, 0.0
    shown = [r for r in runs if r.shown]
    step = 0.0
    if opts.stack:
        step = 1.1 * max((float(np.nanmax(r.trace() - r.background()[0])) for r in shown),
                         default=1.0)
        if opts.pct_max:
            step = 110.0
    for r in reversed(shown):                     # the first run on top
        b = r.background()[0]
        if opts.stack or opts.pct_max:
            top = float(np.nanmax(r.trace() - b)) or 1.0
            k = 100.0 / top if opts.pct_max else 1.0
            out[r.id] = (b, k, off)
            off += step
        else:
            out[r.id] = (b, 1.0, 0.0)
    return out


def _f(v, b, k, off, flat):
    return v if flat else (v - b) * k + off


def visible_range(runs, opts, x0=None, x1=None):
    """(ymin, ymax) of the shown runs' traces (and background lines) between x0 and x1."""
    sc = _scales(runs, opts)
    flat = not (opts.stack or opts.pct_max)
    lo, hi = 0.0, 1.0
    for r in runs:
        if not r.shown:
            continue
        sel = np.ones(len(r.x), bool)
        if x0 is not None:
            sel = (r.x >= x0) & (r.x <= x1)
        if not sel.any():
            continue
        b, k, off = sc[r.id]
        v = _f(r.trace(), b, k, off, flat)[sel]
        lo, hi = min(lo, float(np.nanmin(v))), max(hi, float(np.nanmax(v)))
    return lo, hi


def draw(ax, runs, opts, results, *, raw=False, spikes=False, background=False, only=None,
         sel=None, sel_region=None, edges=False, bg="#ffffff"):
    """Every shown run on ax. results: {run.id: peaks.Results}. raw / spikes / background:
    draw the trace as recorded, the excluded spikes, the background line — for every shown run,
    or only for `only`. sel: the selected run (its regions' edges drawn when `edges`,
    sel_region highlighted)."""
    sc = _scales(runs, opts)
    flat = not (opts.stack or opts.pct_max)
    lw = opts.line_width_pt
    x_end = max((float(r.x[-1]) for r in runs if r.shown), default=1.0)
    y_top = visible_range(runs, opts)[1] * 1.05
    for r in runs:
        if not r.shown:
            continue
        b, k, off = sc[r.id]
        y = r.trace()
        v = _f(y, b, k, off, flat)
        extra = only is None or r is only
        if raw and extra:
            ax.plot(r.x, _f(r.trace(raw=True), b, k, off, flat), color="#b0b0b0", lw=lw * 0.8,
                    zorder=1)
        ax.plot(r.x, v, color=r.color, lw=lw, zorder=3, label=r.name)
        if background and extra:
            ax.plot(r.x, _f(b, b, k, off, flat), color="#808080", lw=lw * 0.8, ls="--", zorder=2)
        if spikes and extra:
            ex = r.excluded()
            for i in np.flatnonzero(ex):
                ax.plot([r.x[i], r.x[i]], [v[i], _f(r.y[i], b[i], k, off, flat)],
                        color="#e02020", lw=lw, zorder=4)
            for i in r.kept:                      # flagged, put back: a ring on the point
                ax.plot([r.x[i]], [v[i]], "o", mfc="none", mec="#e02020", ms=5, zorder=4)
        res = results.get(r.id)
        if not (opts.show_regions and res):
            continue
        for j, (reg, row) in enumerate(zip(r.regions, res.rows)):
            m = (r.x >= reg.start - 1e-9) & (r.x <= reg.end + 1e-9)
            if m.sum() < 2:
                continue
            xs, ys = r.x[m], y[m]
            under = (np.interp(xs, [xs[0], xs[-1]], [ys[0], ys[-1]]) if reg.under == "line"
                     else b[m])
            col = reg.color or r.color
            ax.fill_between(xs, _f(ys, b[m], k, off, flat), _f(under, b[m], k, off, flat),
                            color=col, alpha=opts.region_alpha, lw=0, zorder=2.5)
            if edges and r is sel:
                hl = j == sel_region
                for t in (reg.start, reg.end):
                    ax.axvline(t, color=col, lw=1.6 if hl else 0.6, alpha=0.9 if hl else 0.5,
                               zorder=5)
            txt = _label(row, opts.region_labels)
            if txt:
                top = int(np.argmax(ys - under))
                px, py = xs[top], _f(ys[top], b[m][top], k, off, flat)
                dx, dy, ha, va = _label_placement(px, py, 0.0, x_end, 0.0, y_top, "auto")
                ax.annotate(txt, (px, py), textcoords="offset points", xytext=(dx, dy),
                            ha=ha, va=va, fontsize=opts.label_size,
                            color=_readable(col, bg), zorder=6)


def _label(row, mode):
    """A region's label: its name if it has one (typed or the method's), its % of total.
    None below the quantification limit: those are in the results, not on the figure, where
    small neighbours' labels would only pile up."""
    if "n.d." in row.flags or "< LOQ" in row.flags:
        return ""
    parts = []
    if mode in ("name", "both") and row.named:
        parts.append(row.name)
    if mode in ("pct", "both") and row.pct is not None:
        parts.append(f"{row.pct:.1f} %")
    return "\n".join(parts)


def y_title(opts):
    return "% of max" if opts.pct_max and opts.y.title == Y_TITLE else opts.y.title


def resolve_limits(runs, opts):
    x_max = max((float(r.x[-1]) for r in runs if r.shown and len(r.x)), default=1.0)
    lo, hi = visible_range(runs, opts)
    xmin = 0.0 if opts.x.vmin is None else opts.x.vmin
    xmax = x_max if opts.x.vmax is None else opts.x.vmax
    ymin = (lo * 1.05 if lo < 0 else 0.0) if opts.y.vmin is None else opts.y.vmin
    ymax = hi * 1.05 if opts.y.vmax is None else opts.y.vmax
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    return xmin, xmax, ymin, ymax


def auto_extents(runs, opts):
    xmin, xmax, ymin, ymax = resolve_limits(runs, opts)
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


def build_figure(runs, opts: PlotOptions, results) -> Figure:
    """The figure for export: plot area exactly opts' size in mm, plus the label margins."""
    xmin, xmax, ymin, ymax = resolve_limits(runs, opts)
    left, bottom, right, top = _margins_mm(opts, ymax)
    plot_w = opts.plot_w_mm if opts.total_w_mm is None else max(5.0, opts.total_w_mm - left - right)
    plot_h = opts.plot_h_mm if opts.total_h_mm is None else max(5.0, opts.total_h_mm - bottom - top)
    fig_w, fig_h = plot_w + left + right, plot_h + bottom + top
    fig = Figure(figsize=(fig_w / 25.4, fig_h / 25.4))
    fig.plot_area_mm = (plot_w, plot_h)   # what the size fields report back when a total is fixed
    fig.patch.set_facecolor(to_rgba(opts.outside_color, opts.outside_alpha))
    ax = fig.add_axes([left / fig_w, bottom / fig_h, plot_w / fig_w, plot_h / fig_h])
    ax.set_facecolor(to_rgba(opts.bg_color, opts.bg_alpha))
    draw(ax, runs, opts, results, raw=opts.show_raw, spikes=opts.show_spikes,
         background=opts.show_background, bg=opts.bg_color)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_linewidth(opts.x.lw_pt)
    ax.spines["left"].set_linewidth(opts.y.lw_pt)
    _apply_axis(ax, "x", opts.x, xmin, xmax, plot_w)
    _apply_axis(ax, "y", opts.y, ymin, ymax, plot_h)
    ax.set_xlabel(opts.x.title, fontfamily=opts.x.title_font_family,
                  fontsize=opts.x.title_font_size, labelpad=opts.x.title_pad_mm * PT_PER_MM)
    ax.set_ylabel(y_title(opts), fontfamily=opts.y.title_font_family,
                  fontsize=opts.y.title_font_size, labelpad=opts.y.title_pad_mm * PT_PER_MM)
    if opts.legend and sum(r.shown for r in runs) > 1:
        ax.legend(loc=opts.legend_loc, frameon=False,
                  prop={"family": opts.legend_font_family, "size": opts.legend_font_size})
    return fig


def _self_check():
    from .peaks import find_regions, measure
    from .run import Run

    t = np.arange(600, dtype=float)
    y = 8 + 400 * np.exp(-0.5 * ((t - 300) / 8) ** 2)
    run = Run(x=t / 60, y=y)
    run.detect_spikes()
    run.regions = find_regions(run)
    fig = build_figure([run], PlotOptions(), {run.id: measure(run)})
    ax = fig.axes[0]
    bb = ax.get_position()
    assert abs(bb.width * fig.get_figwidth() * 25.4 - 80) < 0.5
    assert abs(bb.height * fig.get_figheight() * 25.4 - 40) < 0.5
    assert len(ax.collections) == 1 and "100.0 %" in ax.texts[0].get_text()   # the region
    o = PlotOptions(pct_max=True)
    assert y_title(o) == "% of max" and abs(visible_range([run], o)[1] - 100) < 1e-9
    print("plotting self-check OK")


if __name__ == "__main__":
    _self_check()
