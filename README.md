# Spikeless

<img src="src/spikeless/assets/spikeless.png" width="96" align="right" alt="Spikeless icon">

Radio-HPLC chromatograms exported by **GINA X**: remove the single-point spikes of the
radio-detector, integrate the peaks, make publication-ready figures and a report.
MIT-licensed (see `LICENSE`).

## Install (Windows)

No admin rights, no PATH or registry changes, nothing written into your user profile.

1. On the GitHub page: **Code ▸ Download ZIP**.
2. **Right-click the ZIP ▸ Properties ▸ tick *Unblock* ▸ OK** — without it, SmartScreen stops
   the launcher with *"Windows protected your PC"*.
3. Extract it where it can stay (`C:\Users\Public\Spikeless` serves every account).
4. Double-click **`Spikeless.bat`**. The first time it downloads
   [`uv`](https://github.com/astral-sh/uv), Python and the libraries (about 450 MB, a minute or
   two) into the shared folder `C:\ProgramData\PyApps`, which other tools installed this way
   reuse, and puts a **Spikeless** shortcut on the Desktop. Use the shortcut from then on; to pin
   it, right-click its taskbar button while it runs ▸ *Pin to taskbar*.

Self-contained instead: run **`Spikeless.bat private`** the first time, and everything goes into
`C:\Users\Public\Spikeless` (`SPIKELESS_RUNTIME` picks another place). **`uninstall.bat`**
removes it: the whole private folder, or only Spikeless's part of the shared one.

## Use

1. **Drop** a GINA `.txt` on the window (or **Open…**, or **Ctrl+V** columns copied from Excel
   or Prism). It plots at once.
2. **Detect spikes** — the spikes are marked in red, then a **spikeless** curve replaces the
   original on the plot.
3. Click the **spikeless** curve in the **Data** panel (processing acts on the curve selected
   there), then **Detect baseline** and **Detect peaks**: retention time, area and % of each
   peak, shaded on the plot. Set their two ⚙ first, as the guide's
   [step by step](GUIDE.md#a-run-step-by-step) says — the defaults miss small peaks.
4. **Report** — pick the sections, see it, save it as PDF, Word-compatible `.odt`, Excel,
   Markdown or web page. **Copy / Export** on the plot gives the figure at its exact size in mm.
5. **Save…** (Ctrl+S) keeps the whole analysis in a `.spikeless` file, to open it again later.

Each processing button has a **⚙** for its settings; **Options** holds the preferences (plot
export, isotopes, panels). Ctrl+Z / Ctrl+Y undo and redo each step.

Every panel and setting, how the numbers are made, and how to report spike removal in a
publication: **[the user guide](GUIDE.md)**.

## Dev

```
uv run python -m spikeless              # launch
uv run python -m spikeless.<module>     # self-check of spikes, peaks, adjust, io_gina,
                                        #   io_paste, plotting, options, session
uv run python misc/smoke_test.py        # headless run of the whole UI
uv run python misc/paste_test.py        # clipboard import through the UI
uv run python misc/bump.py              # stamp today's date as the version (CalVer)
uv run python misc/make_icon.py         # redraw the icon (needs Pillow)
bash misc/root_test.sh                  # where the launcher decides to install
```

Layers: `io_gina.py`, `io_paste.py` readers · `spikes.py`, `peaks.py`, `adjust.py` the maths
(no Qt) · `dataset.py` the model · `session.py` the session file · `plotting.py` the figure ·
`plotview.py` the zoomable view · `options.py`, `report.py` their windows · `app.py` the main
window. scipy is imported inside the functions that need it, to keep it off the startup path.
