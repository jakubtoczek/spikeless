"""A session file: the datasets open, every curve made from them, and the plot options, in
one JSON file (.spikeless), to reopen an analysis where it was left.

Arrays are written as lists. Reading is forgiving the way the options are: a key it does not
know is dropped and a missing one keeps its default, so a file from an older or newer
version still opens. Curve ids are not kept: each curve opened gets a new one.
"""

from __future__ import annotations

import dataclasses
import json
import typing

import numpy as np

from . import __version__
from .dataset import Condition, Curve, Dataset, Peak
from .plotting import PlotOptions

EXT = ".spikeless"
_ARRAYS = {"x": float, "y": float, "baseline": float, "spike_mask": bool, "spike_shown": bool}
_LISTS = {"peaks": Peak, "children": Curve, "conditions": Condition}


def _plain(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"{type(o).__name__} is not JSON")


def dumps(datasets: list[Dataset], plot: PlotOptions) -> str:
    return json.dumps({"app": "Spikeless", "version": __version__,
                       "datasets": [dataclasses.asdict(d) for d in datasets],
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


def loads(text: str) -> tuple[list[Dataset], PlotOptions]:
    """(datasets, plot options) from a session file's text; ValueError if it isn't one."""
    try:
        got = json.loads(text)
        if got.get("app") != "Spikeless":
            raise ValueError("no Spikeless mark")
        return ([_make(Dataset, d) for d in got["datasets"]],
                _make(PlotOptions, got.get("plot") or {}))
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"Not a Spikeless session file ({e}).") from e


def _self_check():
    from .peaks import analyze_peaks, detect_peaks
    from .spikes import detect

    x = np.arange(600) / 60.0
    y = 8 + 300 * np.exp(-0.5 * ((np.arange(600) - 300) / 6) ** 2)
    y[100] += 2000
    ds = Dataset(root=Curve(x=x, y=y), conditions=[Condition("pH", "7")])
    ds.meta.radioisotope, ds.half_life_s = "¹⁷⁷Lu", 574300.8
    root = ds.root
    root.spike_mask = detect(y)
    root.spike_shown = np.ones(1, bool)
    child = Curve(x=x, y=y * 2, name="clean", kind="spikeless", how={"curve": "Hampel w=7"})
    child.baseline = np.full(600, 8.0)
    child.peaks = detect_peaks(child.y, child.baseline)
    analyze_peaks(x, child.y, child.peaks, child.baseline)
    child.peaks[0].name = "main"
    root.children.append(child)
    plot = PlotOptions(plot_w_mm=120)
    plot.y.vmax = 500.0

    (ds2,), plot2 = loads(dumps([ds], plot))
    r2, c2 = ds2.root, ds2.root.children[0]
    assert np.array_equal(r2.y, y) and r2.spike_mask.dtype == bool and r2.spike_mask[100]
    assert c2.kind == "spikeless" and c2.how == {"curve": "Hampel w=7"} and c2.id != child.id
    assert np.array_equal(c2.baseline, child.baseline)
    assert c2.peaks[0].name == "main" and c2.peaks[0].auc == child.peaks[0].auc
    assert ds2.conditions[0].text() == "pH: 7" and ds2.meta.radioisotope == "¹⁷⁷Lu"
    assert plot2 == plot, "plot options changed on the way"

    # forgiving: an unknown key is dropped, a missing one defaults
    raw = json.loads(dumps([ds], plot))
    raw["datasets"][0]["root"]["from_the_future"] = 1
    del raw["datasets"][0]["root"]["style"]
    (ds3,), _ = loads(json.dumps(raw))
    assert ds3.root.style.color == Curve(x=x, y=y).style.color
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
