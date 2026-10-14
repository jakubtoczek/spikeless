# Spikeless

<img src="src/spikeless/assets/spikeless.png" width="96" align="right" alt="Spikeless icon">

Desktop GUI to clean single-point spikes from radio-HPLC spectra exported by **GINA X**,
produce publication-ready plots, and analyse/export them. MIT-licensed (see `LICENSE`).

## Install (Windows)

No admin rights, no PATH or registry changes, and nothing written into your user profile.

1. On the GitHub page: **Code ▸ Download ZIP**.
2. **Right-click the ZIP ▸ Properties ▸ tick *Unblock* ▸ OK.** Windows flags everything
   that came from the internet, and without this step SmartScreen stops the launcher with
   *"Windows protected your PC"*.
3. Extract it somewhere it can stay — `C:\Users\Public\Spikeless` works for every account on the
   machine; your Documents folder is fine too.
4. Double-click **`Spikeless.bat`**. Nothing is asked: the Python runtime goes into the
   **shared** folder `C:\ProgramData\PyApps`, where every tool set up this way re-uses the
   same `uv.exe`, Python and package cache — files common to two of them are stored once
   (hard-linked), so a second tool only costs the libraries it does not already share.

   Prefer it self-contained? Run **`Spikeless.bat private`** from a terminal (or `2`) the
   *first* time, and everything lands in `C:\Users\Public\Spikeless`, a single folder that
   `uninstall.bat` deletes whole.

   Either way it downloads [`uv`](https://github.com/astral-sh/uv), a matching Python and the
   dependencies — about 450 MB on disk, a minute or two on a normal connection — and puts
   a **Spikeless** shortcut on your Desktop.
5. From now on use the Desktop shortcut. Leave the extracted folder where it is; the
   shortcut points at it.
   To pin it to the taskbar: right-click its taskbar button while it runs (or its Start
   menu entry, which it keeps up to date) ▸ *Pin to taskbar*.

The choice is made once: from then on the folder on disk is the memory, so the Desktop
shortcut and a plain double-click find it and start straight away — no argument needed
again. Set `SPIKELESS_RUNTIME` to force some other location.

`uninstall.bat` reverses all of it: the whole folder in the private case, only Spikeless's own
virtual environment in the shared case, so anything else using that folder keeps working.

## Use

1. **Drag** a GINA `.txt` onto the window (or **Open…**). The spectrum plots immediately.
   Before any data is loaded there is no plot, and Plot options / Detect are disabled.
   Or **Ctrl+V** to paste columns straight from Prism or Excel — time then counts, or several
   value columns / `time, value, time, value` pairs for one dataset each. The log says what it
   assumed about units and layout.
   **Save…** (Ctrl+S) writes the whole session — datasets, every curve made from them, spikes,
   baselines, peaks and their names, styles, the plot options — to a `.spikeless` file; **Open…**
   or a drop opens it again (replacing what is open, after asking; Ctrl+Z gives that back).
2. **Data** panel is a **tree**. Each **dataset** node is metadata only — name, file, run
   date/time, molecule, **radioisotope** (dropdown), and user-added **conditions** (Info, each a
   free note or a label/value pair). Under it sit **curves**: the **original**, and processed
   curves you create (spikeless, decay-corrected, …). Under each curve sit its results — a
   **spikes** group (→ each spike, showing y), a **baseline**, and a **peaks** group (→ each peak
   with **Rt / y / AUC / %**). Every node has a **checkbox** (unticking a parent unticks its
   children), can be **renamed** (double-click — a pen marks editable rows) and **removed** (✖).
   **Drag** curves/datasets to reorder them = change draw order (top of tree draws under, so later
   items sit on top — matters with alpha). Drop a dataset onto another dataset, or a curve onto a
   sibling curve, to reorder; a drop line shows where it will land. Buttons act on the selection:
   **Info** (details for *any* element — dataset metadata, curve, spikes, baseline, peaks, or a
   single spike/peak), **Adjust** (normalization, curve only), **Display…** (any node — appearance),
   **Duplicate** (curve).
3. **Processing** acts on the **selected curve** (so detecting on a spikeless curve finds no
   spikes). Pipeline order is **spikes → decay → baseline → peaks**: spikes are an electronic
   artefact unrelated to sample activity, so they are removed *before* decay correction; decay
   comes before baseline/peaks so AUC/% reflect the activity-corrected signal. Each action has a
   ⚙ for its parameters:
   - **Detect spikes** → marks spikes and adds a **spikeless** child curve (⚙: window, threshold,
     max width, interpolation linear / PCHIP).
   - **Apply decay** → adds a **decay-corrected** child curve. Its ⚙ sets the isotope (+ half-life)
     and the time to decay-correct **to** (default run start); if the isotope/half-life is missing
     when you click Apply decay, that dialog opens automatically. *(Hidden by default — enable it
     in Options › Processing.)*
   - **Detect baseline** → adds a baseline and a **baseline-corrected** child curve (⚙: minimum,
     average of the first N points, SNIP or arPLS — the two that follow a drifting baseline — and
     whether negatives of the corrected curve are set to 0).
   - **Detect peaks** → adds peaks with Rt/AUC/% (⚙: prominence, height, distance, and whether
     to integrate above a **local drift line** even when the curve has a baseline). Detection runs on a **spike-suppressed** copy
     of the curve, so spikes don't become skinny false peaks. Running it on a plain curve makes a
     fresh peaks group; running it on an existing peak/peaks group reprocesses with current options.
4. **Plot options** — a collapsible panel down the **left** side; it opens with the first
   dataset (Options › Panels). Sections: **Plot area**, **Margins**, **Legend**, **Y axis**,
   **X axis** — plot size in mm, plot-area/margin background colour + alpha, legend position/font,
   axis limits, fonts, tick length/thickness, and each axis's **Advanced** (title/label spacing,
   and a grid on major + minor). (Per-curve appearance is set from the Data tree via
   **Display…**.) Numeric axis limits, **graduation start/end**, and tick thickness have **Auto**
   tickboxes (auto tick thickness = axis thickness); a ticked Auto limit shows the value
   auto-mode would use, greyed out. All sections start collapsed except **Plot area**. The mouse
   wheel scrolls the panel and only changes a field once it is clicked into; a typed number is
   applied on Enter or on leaving the field.
5. **Report** (toolbar) — its own window: the **format** and the **sections** on the left, the
   report as it will be written on the right, kept up to date as you work. Formats: **PDF**,
   **.odt** (opens in Word and LibreOffice), **Excel** (a sheet per table, the plot on its own
   sheet), **Markdown** (the plot beside it as a `.png`), **web page**. Sections, ticked in or
   out: the **plot** (as Export writes it, at its size in mm), the **datasets** (file, run,
   molecule, radioisotope, conditions), the **curves** (each one, and how it, its spikes, baseline
   and peaks were made — method and settings), the **spikes** (time and height of each), the
   **peak tables** (tick their columns underneath; the same columns go into the Data panel's peak
   exports). **Save report…** (Ctrl+S) writes it; **Copy** puts its text and tables on the
   clipboard for a document (the plot has its own Copy).
6. **Options** (toolbar) — its own window, topics on the left: **Plot** (crop fills, PNG export
   and copy resolution, copy as PNG or SVG), **Screen** (the checker or solid background behind
   the plot, the dotted export-area guide — neither is ever copied or exported — and the
   resolution slider's top), **Processing** (which buttons the panel shows; Apply decay is off at
   first), **Isotopes** (the Radioisotope lists and the half-lives decay correction uses: edit a
   cell, + / −), **Panels** (which open at start; lock them) and **Log** (timestamps in its copy
   and export). Every change is saved at once to `spikeless_options.json` beside
   `Spikeless.bat`; **Export… / Import…** carry it to another computer, **Reset to defaults**
   starts over. Each processing button's ⚙ settings are not kept: they start from their
   defaults every session.
7. **Copy / Export / ⚙**: the **plot** has a **⧉ Copy · ⭳ Export · ⚙** cluster in the top-right of
   the graph area; Export writes PNG (600 dpi unless set otherwise) or SVG at the exact mm size,
   transparency preserved. The **Log** carries **Copy · Export · ⚙ · ✕** on its title bar. Their ⚙
   opens Options at their page. The Data panel's **Export…** writes the selected curve back to a
   GINA-style `.txt` (it reloads; GINA X compatibility is best-effort), or the selected peaks to
   Excel / CSV.

The **Plot options / Data / Processing / Log** toolbar buttons open and close their panels;
closing a panel un-presses its button, pressing it again reopens it.

**Keys**: Ctrl+Z / Ctrl+Y undo and redo any change to the data (each named in the log), Ctrl+C
copies the plot (or the selected text), Ctrl+V pastes columns, **Del** removes the selected node
of the Data tree (what its ✖ does), Ctrl+S saves the session (in the Report window: the report).

### Plot navigation

The plot is rendered as a **vector** image you can zoom and pan: **mouse wheel** zooms centred
on the cursor, **drag** (any button) pans, **double-click** fits to the window. Drop a GINA
`.txt` straight onto it to load. The **resolution slider** (bottom-left) enlarges the plot area
1×–5× on screen (fonts/line widths stay fixed, so closely-spaced spikes/peaks separate out) —
tick **export** to apply it to exports too. The **⧉ Copy** button (top-right cluster) copies the
plot to the clipboard **at its real mm size** (the image carries its dpi, so pasting into
PowerPoint gives the Plot-options size, not a giant); copy resolution (600 dpi) is in
Options › Plot.

### Decay correction and normalization

Neither changes the loaded data:

- **Apply decay** makes a **decay-corrected** child curve: each sample corrected back to a
  reference time with the isotope's half-life (Options › Isotopes, or typed in its ⚙).
  Reference = run start (from the file header) or an offset in minutes from it.
- **Adjust** (Data panel) sets how a curve is **shown**: Counts (cps), **% of max** or **% of
  total**. The `%` modes subtract the curve's detected baseline first (or its minimum, if it has
  none).

## Spike detection algorithm

A spike is a single acquisition point whose value sits far above the local trend. Detection is a
**Hampel filter** (rolling median + median absolute deviation), which is *local*, so it flags a
spike even when it rides on a genuine chromatographic peak while leaving the multi-point peak
itself untouched. For signal `y` and window `w` (odd; default 7):

1. **Local reference** `med = median_filter(y, w)` (edges reflected).
2. **Local scale** from the residual: `mad_local = median_filter(|y − med|, w)`,
   converted to a robust standard deviation `σ = 1.4826 · mad_local`
   (1.4826 makes MAD ≈ σ for Gaussian noise).
3. **Two noise floors** keep quiet regions from over-flagging:
   - global floor: `σ = max(σ, 1.4826 · median(|y − med|))`, so a locally flat window whose
     `mad_local → 0` doesn't flag ~1-count wiggles;
   - Poisson floor (count data): `σ = max(σ, sqrt(max(med, 1)))`, the shot-noise scale of cps.
4. **Threshold**: a point is a candidate when `y − med > n_sigma · σ`
   (`n_sigma` default 5; `positive_only` flags only upward excursions — real spikes are high cps).
5. **Width guard**: any run of consecutive candidates longer than `max_width` (default 1) is
   *dropped*, because a wide excursion is a real peak, not a spike.
6. **Neighbour guard**: what is left must also stand `n_sigma · σ` clear of **both** points
   beside it (beside the run, for a wider one). The apex of a narrow real peak rises above the
   window's median but not far above its neighbours; a spike jumps away from both. (Until
   2026.10.14 this step was missing, and the apex of a ~10-point peak could be flagged and
   interpolated away.)

Parameters (**⚙** next to Detect): `window`, `n_sigma`, `max_width`.

## Spike removal (interpolation)

Flagged points are replaced by interpolation from their nearest un-flagged neighbours; all other
samples are left exactly as-is, so a point on a real peak's flank is restored to the local peak
level, not to baseline. If fewer than two clean points remain, the signal is left unchanged.
Method (Detect spikes **⚙**):

- **Linear** (default) — a straight line between the nearest clean points (`numpy.interp`). For a
  single-point spike that is exactly `n-1 → n+1`. Cannot overshoot.
- **PCHIP** — monotone cubic interpolation across the gap. Smoother for multi-point gaps and,
  unlike a plain cubic spline, will not overshoot into ringing on a peak flank.

Detecting spikes never mutates the loaded data: it marks a **spikes** group on the curve and adds
a **spikeless** child curve, which you can further process (baseline, peaks, decay) like any other
curve. Show/hide, rename, or remove each node in the Data tree.

## Peaks (Rt, AUC, %)

**Detect peaks** on a curve finds local maxima (prominence-based) and computes, per peak,
**Rt** (apex x), **x start/end/width**, **y max** (above baseline), **AUC**, **%** of the group
total, and a **skewness**. Select a peak → **Info** shows all of it (name editable); **Display…**
sets the peaks group's style. Integration bounds run apex-to-valley (the low point between a peak
and its neighbour) then trim to the peak's feet, so the shaded region spans the whole peak rather
than a narrow tip. Peaks draw as a shaded **AUC fill** by default (or markers), with optional
on-graph **Rt / %** labels. A peak's area is taken above the curve's detected baseline when it
has one, else above a straight line between the peak's bounds (the **Detect peaks ⚙** can ask for
that line always). The **report** has a table per curve with peaks, in the columns ticked there;
Info and the report say which settings found them.

## GINA format notes

- Windows-1252 encoded, tab-separated, decimal comma.
- Signal = 2nd column (radiodetector count rate, cps).
- The time column is display-formatted and lossy, so time is reconstructed assuming uniform
  sampling (interval inferred from the file; all known files are 1 Hz).

## Dev

```
uv run python -m spikeless              # launch
uv run python -m spikeless.spikes       # spike-detection self-check
uv run python -m spikeless.peaks        # peak-detection self-check
uv run python -m spikeless.adjust       # decay/baseline/normalization self-check
uv run python -m spikeless.io_gina      # parser + GINA-save round-trip self-check
uv run python -m spikeless.plotting     # plot-sizing self-check
uv run python -m spikeless.options      # options file: malformed values keep their defaults
uv run python -m spikeless.session      # session file round-trip self-check
uv run python misc/bump.py              # stamp today's date as the version
uv run python misc/make_icon.py         # redraw the icon (needs Pillow)
uv run python misc/smoke_test.py        # headless UI run: load -> spikes -> baseline ->
                                        #   peaks -> decay -> report (every format) / CSV /
                                        #   undo / redo / Del / session / Options window
bash misc/root_test.sh                  # where the launcher decides to install
```

Startup is kept off scipy: `scipy.signal` and `scipy.ndimage` are imported inside the functions
that need them (1.3 s of import that nothing needs until a peak is actually detected).

## Roadmap

A **segmented** baseline estimator. Richer peak parameters.

_Done:_ SNIP and arPLS drift-aware baselines; per-peak report table + Excel export; per-peak
colour and on-graph labels; configurable per-button display actions; Report and Options windows;
session files.
