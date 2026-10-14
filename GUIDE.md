# Spikeless — user guide

Everything the window does, how the numbers are made, and how to report spike removal. For
installing, see the [README](README.md).

## A run, step by step

1. **Load.** Drop a GINA X `.txt` export on the window, or **Open…**. Several files: several
   datasets, overlaid. Or copy columns in Excel or Prism (time, then count rate) and press
   **Ctrl+V**; the log says what it assumed about units and layout.
2. **Spikes.** **Detect spikes**: the spikes flash red on the plot, then a **spikeless** curve
   takes the original's place. The Data panel lists each spike (time, height). If one is not a
   spike, see [When something looks wrong](#when-something-looks-wrong).
3. **Select the spikeless curve** in the Data panel. Processing always acts on the selected
   curve.
4. **Background.** In **Detect baseline ⚙**, choose **Average of first N points** (the start of
   the run, before anything elutes: the detector's background, ~5–10 cps), then **Detect
   baseline**. (The default, *Minimum*, gives 0 cps on a noisy background — see below.)
5. **Peaks.** In **Detect peaks ⚙**, set **Min prominence** to a count rate, e.g. **50** cps,
   then **Detect peaks**. Each peak's retention time, area and % appear in the Data panel and are
   shaded on the plot. Select a peak ▸ **Info** to name it (e.g. *free ¹⁷⁷Lu*, *product*).
6. **Report.** **Report** on the toolbar: tick the sections, check the preview, **Save
   report…** as PDF, `.odt`, Excel, Markdown or web page.
7. **Keep it.** **Save…** (Ctrl+S) writes the whole analysis to a `.spikeless` file; open or drop
   it later to carry on.

Ctrl+Z undoes a load, a processing step or a removal, Ctrl+Y redoes it; the log names each one.

## The window

The **plot** in the middle; **Plot options** on the left; **Data** and **Processing** on the
right; the **Log** at the bottom. The toolbar buttons of the same names show and hide them.

### Data

A tree. Each **dataset** (a run) holds its curves: the **original**, and each curve made from
it — *spikeless*, *−baseline*, *+decay* — under the curve it was made from. Under a curve: its
**spikes** (each one), its **baseline**, its **peaks** (each one, with Rt, height, area, %).

- **Tick** to show or hide (unticking a parent hides what is under it).
- **Double-click** a name (✎) to rename it; a dataset's or a peak's name goes into the report.
- **✖** or **Del** removes a node (not the original curve: remove the dataset instead).
- **Drag** datasets onto datasets, or curves onto sibling curves, to change which draws on top.
- Buttons, for the selected node: **Info** (everything about it; a dataset's file, run time,
  molecule, radioisotope and conditions are edited here), **Adjust** (show a curve as cps, % of
  max or % of total), **Display…** (colour, line, fill, legend; peak and spike styles),
  **Duplicate** (a curve), **Export…** (a curve back to a GINA-style `.txt`, or a peak table to
  Excel / CSV).

### Processing

Four buttons, in the order they should run: **Detect spikes → Apply decay → Detect baseline →
Detect peaks**. Spikes first: they are an electronic artefact, not activity, so they go before
decay correction; decay before baseline and peaks, so areas are of the corrected signal.
*Apply decay* is hidden until switched on in Options › Processing.

- **⚙** beside each: its settings (they start from their defaults every session).
- **▸** before each: what it shows and hides as it runs, and when (show the spikes, wait 0.5 s,
  show the spikeless curve…). Add steps with **＋ add**, drag to reorder.

### The plot

- **Wheel** zooms around the cursor, **drag** pans, **double-click** fits it to the window.
- **⧉ Copy · ⭳ Export** (top right): the figure at its exact size in mm — PNG (600 dpi) or SVG,
  transparency kept. A copied PNG carries its resolution, so it pastes into PowerPoint or Word at
  its real size. **⚙** opens Options › Plot.
- **res** slider (bottom left): enlarges the plot area 1–5× on screen with the text kept the
  same size, to pull close peaks apart; tick **export** to apply it to Copy / Export too.
- The checkerboard (behind transparent parts) and the dashed frame (where the exported image
  ends) are never exported.

### Plot options

The figure: **Plot area** (size in mm, background), **Margins** (a fixed total size instead),
**Legend**, **Y axis**, **X axis** (title, limits, tick spacing, fonts, tick lengths; **Advanced**:
spacing and a grid). A ticked **Auto** shows, greyed, the value it uses. The wheel scrolls the
panel; a field takes the wheel once clicked into. A typed number applies on Enter.

### Log

What was done, with times. **Copy · Export** on its title bar; ⚙ opens Options › Log.

## Report

**Report** opens its own window. On the left: the **format** (PDF, `.odt` — opens in Word and
LibreOffice, Excel — a sheet per table and the plot on its own, Markdown — the plot saved beside
it, web page) and the **sections**: the plot (as Export makes it), the datasets (file, run,
molecule, radioisotope, conditions), the curves (how each was made: method and settings), the
spikes (time and height of each), the peak tables (tick their columns underneath). On the right,
the report as it will be written, following your work. **Save report…** (Ctrl+S) writes it;
**Copy** puts its text and tables on the clipboard. Your choices are kept for next time.

## Options

**Options** opens its own window, topics on the left. **Plot** — crop fills where curves cross,
PNG and copy resolution, copy as PNG or SVG. **Screen** — the background behind the plot and the
export frame. **Processing** — which buttons show. **Isotopes** — the Radioisotope lists and the
half-lives decay correction uses (edit a cell; + / −). **Panels** — which open at start; lock
them. **Log** — times in its copy. Every change is saved at once, to `spikeless_options.json`
beside `Spikeless.bat`; **Export… / Import…** carry them to another computer, **Reset to
defaults** starts over.

## Sessions

**Save…** writes the datasets, every curve, spikes, baselines, peaks and their names, styles
and the plot options to one `.spikeless` file. **Open…** or a drop opens it; if something is
open, Spikeless asks before replacing it (Ctrl+Z brings it back). The GINA files are not needed
again: the session holds their data.

## How the numbers are made

### Spike detection

A spike is one sample far above the trace around it. Detection is a **Hampel filter**: it
compares each point to the median of its neighbourhood, so it finds a spike even on a peak's
flank and leaves the peak alone. For a window *w* (odd, default 7 points):

1. Reference: `med` = moving median over *w* points.
2. Noise: σ = 1.4826 × moving median of |y − med| (the robust standard deviation), at least
   1.4826 × the whole run's median of |y − med|, and at least **√med** — the Poisson noise of a
   count rate — so quiet stretches don't flag one-count wiggles.
3. Candidate: y − med > *n* σ (*n* = **Threshold**, default 5; upward only).
4. Width: a run of candidates wider than **Max width** (default 1 point) is a real peak — not
   flagged.
5. Neighbours: the point must also exceed **both** points beside it by *n* σ. The apex of a
   narrow real peak rises above the window's median but not far above its neighbours; a spike
   jumps away from both.

### Spike removal

The file is never changed. The flagged point is left out of a new **spikeless** curve, where the
straight line between its two neighbours bridges its place (**Linear**, the default; **PCHIP**,
a smooth monotone curve, is offered for multi-point gaps). Further processing — baseline, peaks,
decay — is done on that curve.

### Background (baseline)

**Detect baseline** estimates it on the selected curve and makes a **−baseline** curve (the
curve minus it). Methods: **Average of first N points** (the background before anything elutes —
the usual choice for a radio-detector, whose background is flat), **Minimum** (0 on a noisy
background: avoid), **SNIP** and **arPLS** (follow a drifting baseline, for traces that have one),
**None**. Optionally the −baseline curve's negative values are set to 0.

### Peaks

**Detect peaks** finds peaks by prominence (**Min prominence** in cps; *0 = auto*, 5 % of the
trace's range — which misses a small peak beside a large one), **Min height** and **Min
distance**. Each peak's bounds run from its apex down to the valley beside it, then in to its
feet. Per peak: **Rt** (apex), start, end, width (end − start), height above the baseline, **area**
and **%** — of the peaks found — and a moment skewness. The area is taken above the curve's
baseline when it has one, else above a straight line between the peak's bounds (Detect peaks ⚙
can ask for that line always). Areas (**AUC**) are in **cps·min**: × 60 gives counts. Spikes are bridged before peaks are looked for, so they never become false peaks.

### Decay correction

**Apply decay** makes a **+decay** curve, each point corrected back to the run start (or an
offset from it) with the half-life of the dataset's isotope (Options › Isotopes, or typed in its
⚙): × e^(λ (t − t_ref)). Within a 15-min run this matters for short-lived isotopes (⁶⁸Ga: 17 %
between start and end) and hardly for long ones (¹⁷⁷Lu: 0.1 %).

### Files

GINA X exports: Windows-1252, tab-separated, decimal comma; the radio-detector's count rate
(cps) is the 2nd column. The time column loses resolution after a minute, so time is rebuilt from
the sampling interval read at the start of the file (1 s in every file seen). Pasted columns:
time then one or more count-rate columns, or time/value pairs; minutes unless the numbers look
like seconds.

## Reporting spike removal

### Interpolate, or delete the point?

They are the same operation, written two ways:

- **On the plot**, a curve drawn without the point joins its two neighbours with a straight
  line — the line linear interpolation draws.
- **In an area**, integrating across the gap with trapezoids gives exactly the area with the
  interpolated point: 15 484 counts both ways on the example below.

They differ only if the gap is handled otherwise, and both alternatives are worse. The one
example spike inside a peak — a 3 120 cps sample between 25 and 211 cps, on the rising edge of
a ¹⁷⁷Lu product peak — with the peak's counts summed point by point above the 7 cps background:

| How the spike is handled | Peak area (counts) | vs. bridging |
|---|---|---|
| Kept (no cleaning) | 18 489 | +19.4 % |
| **Excluded, gap bridged linearly** (= linear interpolation) | **15 487** | — |
| PCHIP curve across the gap | 15 448 | −0.25 % |
| Excluded, counts summed with that second missing | 15 376 | −0.7 % |
| Excluded, sum rescaled by the points kept | 15 889 | +2.6 % |

Summing without the point loses the counts of that second: little on a flank (here 118
counts), the local count rate × 1 s at an apex (here ~3 000 counts, ~20 % of the peak).
Rescaling assumes the missing second was average for the peak, which a point on a flank is not.
PCHIP adds a curve assumption for no gain. So: **exclude the point and bridge it linearly** —
what Spikeless does with *Linear* — and **say it that way**: excluded, not corrected.

### What makes it rigorous

1. **A rule fixed in advance**: the default settings, or your procedure's — not adjusted run by
   run until a result looks right.
2. **Only isolated single points**: Max width 1. A wider event is real signal or another fault,
   and is reported as such.
3. **Raw data kept**: the GINA file is untouched; the original curve stays in the Data panel and
   in the session.
4. **Every exclusion listed**: Report › Spikes gives the time and height of each; Report › Curves
   gives the rule and its settings.
5. **Its effect shown when it matters**: when a spike falls inside an integrated peak, give the
   area both ways (detect peaks on the original curve too). On the background it changes a few
   counts and needs no more than the count.
6. **The figure says it**: in the caption, or mark the excluded points (Display… on the spikes:
   points, or a line from the bridged value to the spike's height).

### Methods text

With the default settings, adapt the numbers:

> Single-point spikes — isolated electronic artefacts of the flow radio-detector — were
> identified with a Hampel filter: a point was flagged when it exceeded the 7-point moving median
> by more than 5 robust standard deviations (median absolute deviation × 1.4826, at least the
> Poisson noise of the local count rate) and exceeded both adjacent points by the same margin;
> runs of more than one point were not flagged. Flagged points (n = …, … of them within integrated
> peaks) were excluded and their 1-s intervals bridged by linear interpolation between the
> adjacent points before integration. Raw chromatograms are available on request. Processing:
> Spikeless <version> (github.com/jakubtoczek/spikeless).

### In a GMP or regulatory record

Spikeless is not a validated computerised system: no audit trail, no user accounts, no
electronic signatures. Where a result is a GMP record — batch release, a regulatory file — the
result of record comes from the validated chromatography data system, and excluding a point
follows the site's procedure there (justified, documented, the original kept). Spikeless can
show and document what was excluded, and why.

## When something looks wrong

- **A small peak is missing; the product shows 100 %.** Auto prominence is 5 % of the trace's
  range: a peak under 5 % of the largest one's height is not looked for. Set **Min prominence**
  to a count rate (Detect peaks ⚙), e.g. 50 cps — about 20 × the noise of a 7 cps background.
  On the example runs this finds a 2.7 % impurity the auto setting missed, and nothing on a
  blank injection.
- **Hundreds of tiny peaks on a blank.** Same cause, same fix.
- **Areas too large, small peaks too big.** The baseline is 0: *Minimum* of a noisy background.
  Use *Average of first N points*. On an example run: an impurity at 19.8 % with *Minimum*, 15.5 %
  with the background subtracted.
- **% does not match the activity in the run.** % is of the peaks found; activity outside them
  (tailing, a small peak not found) is not in the denominator.
- **A flagged point is not a spike.** Unticking it hides its mark only. Undo (Ctrl+Z) the
  detection, raise **Threshold** in Detect spikes ⚙ and run it again.
- **The same peak gives different areas.** Peaks follow the selected curve: on the spikeless
  curve, the area is above its baseline; on the −baseline curve, above a straight line under
  each peak. Pick one way for a series and keep it.
- **The y axis stops at 0.** Its Auto minimum is 0; set **Min** in Plot options › Y axis to see a
  background-subtracted trace below zero.
- **The plot is lost off screen.** Double-click it.

## Shortcuts

| Key | |
|---|---|
| Ctrl+Z / Ctrl+Y | undo / redo a load, a processing step, a removal |
| Ctrl+C | copy the plot (or the selected text) |
| Ctrl+V | paste columns as datasets |
| Ctrl+S | save the session (in the Report window: the report) |
| Del | remove the selected node of the Data panel |
| wheel · drag · double-click | zoom · pan · fit the plot |
