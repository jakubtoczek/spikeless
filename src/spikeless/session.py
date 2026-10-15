"""A session file: the runs open — each with its spikes, background and regions — and the
figure's settings, in one JSON file (.json), to reopen an analysis where it was left.

Arrays are written as lists. Reading is forgiving the way the options are: a key it does not
know is dropped and a missing one keeps its default, so a file from an older or newer version
still opens. A file from 2026.10.14 (datasets of curves) opens too: each dataset becomes a
run, its spikes are found again, and the peaks of its most processed curve become regions.
"""

from __future__ import annotations

import dataclasses
import json
import typing

import numpy as np

from . import __version__
from .plotting import Y_TITLE, PlotOptions
from .run import COLORS, Region, Run
from .spikes import SpikeParams

EXT = ".json"
_ARRAYS = {"x": float, "y": float, "spikes": bool}
_LISTS = {"regions": Region}


def _plain(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"{type(o).__name__} is not JSON")


def dumps(runs: list[Run], plot: PlotOptions) -> str:
    return json.dumps({"app": "Spikeless", "version": __version__,
                       "runs": [dataclasses.asdict(r) for r in runs],
                       "plot": dataclasses.asdict(plot)}, default=_plain, ensure_ascii=False)


def _make(cls, d: dict):
    """A `cls` from a dict: unknown keys dropped, missing ones left to their default, nested
    dataclasses and arrays rebuilt, no id (a new one is drawn)."""
    hints = typing.get_type_hints(cls)
    kw = {}
    for f in dataclasses.fields(cls):
        if f.name not in d or f.name == "id":
            continue
        v = d[f.name]
        if dataclasses.is_dataclass(hints[f.name]):     # first: PlotOptions has an x and y too
            v = _make(hints[f.name], v)
        elif v is not None and f.name in _ARRAYS:
            v = np.asarray(v, dtype=_ARRAYS[f.name])
        elif v is not None and f.name in _LISTS:
            v = [_make(_LISTS[f.name], x) for x in v]
        kw[f.name] = v
    return cls(**kw)


def _from_dataset(d: dict, k: int) -> Run:
    """A 2026.10.14 dataset (a tree of curves) as a run."""
    root, meta = d["root"], d.get("meta", {})
    conds = [(c.get("label") + ": " if c.get("label") else "") + c.get("value", "")
             for c in d.get("conditions", [])]
    run = Run(x=root["x"], y=root["y"], dt_s=d.get("dt_s", 1.0),
              name=meta.get("name", ""), file=meta.get("original_filename", ""),
              run_datetime=d.get("run_datetime", ""), headers=d.get("headers", []),
              signal_col=d.get("signal_col", 1), molecule=meta.get("molecule", ""),
              isotope=meta.get("radioisotope", ""), conditions="\n".join(conds),
              color=COLORS[k % len(COLORS)])
    run.detect_spikes()

    def walk(c, depth=0):
        yield depth, c
        for ch in c.get("children", []):
            yield from walk(ch, depth + 1)
    peaked = [(depth, c) for depth, c in walk(root) if c.get("peaks")]
    if peaked:
        _, c = max(peaked, key=lambda t: t[0])
        x = run.x
        run.regions = [Region(float(x[p["left"]]), float(x[p["right"]]), name=p.get("name", ""))
                       for p in c["peaks"]]
    return run


def loads(text: str) -> tuple[list[Run], PlotOptions]:
    """(runs, figure settings) from a session file's text; ValueError if it isn't one."""
    try:
        got = json.loads(text)
        if got.get("app") != "Spikeless":
            raise ValueError("no Spikeless mark")
        if "runs" in got:
            runs = [_make(Run, d) for d in got["runs"]]
        else:
            runs = [_from_dataset(d, k) for k, d in enumerate(got["datasets"])]
        for r in runs:
            if not isinstance(r.spike_params, SpikeParams) or r.spikes is None:
                r.detect_spikes()
        plot = _make(PlotOptions, got.get("plot") or {})
        if plot.y.title == "Counts (cps)":          # the old default, which said counts
            plot.y.title = Y_TITLE
        old = got.get("plot") or {}
        if old.get("pct_max"):                      # before 2026.10.15: a tick, not y_mode
            plot.y_mode = "pct_max"
        if "font" not in old and isinstance(old.get("legend_font_family"), str):
            plot.font = old["legend_font_family"]   # before 2026.10.15.1: a font per text
        if old.get("region_labels") in ("none", "name", "pct", "both"):   # before .2: one list
            plot.label_name = old["region_labels"] in ("name", "both")
            plot.label_pct = old["region_labels"] in ("pct", "both")
        return runs, plot
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
        raise ValueError(f"Not a Spikeless session file ({e}).") from e


def _self_check():
    from .peaks import find_regions, measure

    t = np.arange(600, dtype=float)
    y = 8 + 300 * np.exp(-0.5 * ((t - 300) / 6) ** 2)
    y[100] += 2000
    run = Run(x=t / 60, y=y, isotope="¹⁷⁷Lu", conditions="pH: 7", method="M")
    run.detect_spikes()
    run.kept = [100]
    run.regions = find_regions(run)
    run.regions[0].name, run.regions[0].note = "main", "checked"
    run.bg_mode, run.bg_stretch = "stretch", [0.5, 2.0]
    plot = PlotOptions(plot_w_mm=120, stack=True)
    plot.y.vmax = 500.0

    run.name, run.label = "alias", "on the figure"
    run.find_params.n_sigma = 7.5
    (r2,), plot2 = loads(dumps([run], plot))
    assert (r2.name, r2.label) == ("alias", "on the figure")
    assert r2.find_params.n_sigma == 7.5
    assert np.array_equal(r2.y, y) and r2.spikes.dtype == bool and r2.spikes[100]
    assert r2.kept == [100] and r2.id != run.id
    assert r2.regions == run.regions and r2.bg_stretch == [0.5, 2.0]
    assert measure(r2).rows[0].net == measure(run).rows[0].net
    assert plot2 == plot, "figure settings changed on the way"

    # forgiving: an unknown key is dropped, a missing one defaults
    raw = json.loads(dumps([run], plot))
    raw["runs"][0]["from_the_future"] = 1
    del raw["runs"][0]["color"], raw["runs"][0]["spike_params"]
    (r3,), _ = loads(json.dumps(raw))
    assert r3.color == COLORS[0] and r3.spike_params == SpikeParams()

    # a 2026.10.14 file: a dataset with an original curve, a spikeless child with peaks
    old = {"app": "Spikeless", "version": "2026.10.14", "plot": {"y": {"title": "Counts (cps)"}},
           "datasets": [{"root": {"x": (t / 60).tolist(), "y": y.tolist(), "children": [
               {"x": [], "y": [], "children": [], "peaks": [{"apex": 300, "left": 280,
                                                             "right": 320, "name": "main"}]}]},
               "dt_s": 1.0, "run_datetime": "07/07/2026 14:17",
               "meta": {"name": "Old", "original_filename": "old.txt", "radioisotope": "¹⁸F"},
               "conditions": [{"label": "pH", "value": "7"}, {"label": "", "value": "note"}]}]}
    (r4,), p4 = loads(json.dumps(old))
    assert r4.name == "Old" and r4.isotope == "¹⁸F" and r4.conditions == "pH: 7\nnote"
    assert r4.spike_list() == [100] and r4.regions[0].name == "main"
    assert abs(r4.regions[0].start - 280 / 60) < 1e-9 and p4.y.title == Y_TITLE
    assert r4.source == "Old"                       # an older run: its name is its original
    old["plot"]["pct_max"] = True
    old["plot"]["legend_font_family"] = "Arial"
    old["plot"]["region_labels"] = "pct"
    p5 = loads(json.dumps(old))[1]
    assert p5.y_mode == "pct_max" and p5.font == "Arial"
    assert not p5.label_name and p5.label_pct
    for bad in ("", "[]", '{"app": "Other"}', '{"app": "Spikeless"}'):
        try:
            loads(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"should have refused {bad!r}")
    print("session self-check OK")


if __name__ == "__main__":
    _self_check()
