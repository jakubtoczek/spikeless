# Spikeless — user guide

Everything the window does, how the numbers are made, and how to report them. For installing,
see the [README](README.md).

## A run, step by step

1. **Load.** Drop a GINA X `.txt` export on the window, or **Open…** (Ctrl+O). Several files:
   several runs, overlaid. Or copy columns in Excel or Prism (time, then count rate) and press
   **Ctrl+V**; the log says what it assumed about units and layout.
2. **Spikes** are found and excluded at once: red marks on the plot, a line each in
   **② Spikes** (time, height as recorded → as bridged). Untick one that is not a spike.
3. **Background** — nothing to do for a radio-detector: **③** shows it (≈ 7 cps here), dashed
   on the plot.
4. **Peaks.** **Find peaks** (in **④**), or **drag across a peak on the plot**. Adjust an edge
   by dragging it. The results table under the plot gives each region's net counts, ± and
   **% of total** — the radiochemical purity.
5. **Name them** once for all runs of an HPLC method: Options › Methods (e.g. *free ¹⁷⁷Lu*
   2.3–2.8 min, *product* 7.5–8.5 min), then pick the method in **①**. Or type a name in the
   table.
6. **Report** (toolbar): tick sections and columns, check the preview, **Save report…** as PDF,
   `.odt`, Excel, Markdown or web page.
7. **Save…** (Ctrl+S) keeps the whole analysis in a `.spikeless` file.

Ctrl+Z / Ctrl+Y undo and redo every change to a run; the log names each.

## The window

The **plot** in the middle, the **Results** under it (the **Log** in the tab beside), the
**steps** on the right. The steps act on the **selected run** (① Runs).

### The plot

- **Wheel**: zoom the time around the cursor. **Ctrl+wheel**: zoom the height (to see a small
  peak beside a large one). **Right- or middle-drag**: pan. **Double-click**: the whole run.
- **Left-drag** across the trace: draw a region (see [Drawing regions](#drawing-regions)).
- Ticks above it: **Trace as recorded** (grey, before spikes were excluded), **Spikes** (red
  line from the bridged point to the spike's height; a ring on a spike put back), **Background**
  (dashed), **Stack** (runs one above the other, background subtracted), **% of max** (each run
  as % of its highest point above background). Stack and % of max apply to the figure too.
- **⧉ Copy · ⭳ Export · ⚙ Figure…**: the figure, see [Figure](#figure).

### Results

A row per region of the selected run, then **Outside the regions** and **Total**. Columns are
chosen in the Report window (the report shows the same): region, start, end, Rt, **net
counts**, **±**, **% of total**, % of regions, height, w½, symmetry, resolution, S/N, flags.
Hover a header for its meaning. Click a row to select the region; double-click its name to
rename it; **Del** removes it; **Ctrl+C** copies the table (pastes into Word or Excel).

The line above the table says how the numbers were made: background and how it was taken, the
run's total net counts, spikes excluded, decay correction.

### ① Runs

The runs loaded: **tick** to show, **click** to work on one, **Del** to remove it. For the
selected run: **Name** (the legend and the report use it), **Isotope** (its half-life and
whether runs of it are decay-corrected: Options › Isotopes), **Method** (names the regions:
Options › Methods), **Molecule**, **Conditions** (one per line), **Colour**. Below: its file,
run date, points and SHA-256. **Export trace…** writes the trace as used (spikes excluded,
decay-corrected if so) back to a GINA-style `.txt`.

### ② Spikes

Each flagged point: time, height as recorded → as bridged, and the region it falls in. Ticked =
excluded; **untick to keep it** (the point comes back, everywhere). **Threshold** (default 5 σ):
lower finds more, higher fewer — the list and the plot follow as you slide. **More**: the
moving-median window and the widest run of points that can be a spike.

### ③ Background

What lies under the peaks: the detector's background count rate.

- **Mean outside the regions** (default): the mean of every point no region holds, leaving out
  any point 4 σ above it (a peak no region holds yet).
- **Mean of a stretch**: click **Drag on the plot**, then drag across a stretch with no peak.
- **Follows a drift** (SNIP or arPLS): for a trace whose background drifts. A radio-detector's
  is flat; use it only when it really is not.

### ④ Peaks

**Find peaks** proposes regions for the peaks no region holds yet (it never moves yours).
**Apply to all** copies this run's regions to every other run, each edge moved to that run's own
valley (replacing its regions). **Clear** removes them all. **Selected region**: its name,
what its net counts are above (**the background**, or **a straight line between its ends** —
for a peak on another's tail), a note (why it was drawn or moved, if it matters), its colour.

### Drawing regions

- **Draw**: press at a peak's left foot, drag to its right foot, release. The status line shows
  the net counts while you drag. Each edge lands on the lowest point within 3 points of where
  you let go — the valley — so a rough drag gives the region you meant. **Hold Alt** to place
  the edges exactly.
- **Adjust**: over an edge the cursor turns ↔; drag it. **← →** move the last-touched edge one
  point. Two regions that touch share their edge (a perpendicular drop at the valley): moving it
  moves both. Regions never overlap: a drag across a neighbour stops at its edge.
- **Select** a region with a click (or its row); **Del** removes it.
- How each was placed is kept and reported: *auto* (Find peaks), *drawn*, *moved* (found, then
  adjusted), *copied* (Apply to all).

## Figure

**Figure…** (or ⚙ above the plot) opens what Copy and Export make. Left: a **preset** (article
80 × 40 mm 7 pt, half page, slide 160 × 90 mm 14 pt), what it **shows** (regions, their labels —
name and/or %, the background line, excluded spikes, the trace as recorded, a legend), its
**size** in mm, margins, legend and axes (title, limits, ticks, fonts, grid). Right: the figure
as it will be written (wheel to zoom; the checkerboard is transparency). **Copy** puts it on the
clipboard at its real size (a PNG carries its resolution, so it pastes into PowerPoint or Word
at its size in mm); **Export…** writes PNG (600 dpi) or SVG. Its settings are saved with the
session.

Labels: a region with a name of its own shows it; every region shows its % of total; regions
below the quantification limit carry no label (they are in the results).

## Report

**Report** opens its own window. Left: the **format** (PDF; `.odt`, opens in Word and
LibreOffice; Excel, a sheet per table and the figure; Markdown, the figure saved beside it; web
page) and the **sections**: the **figure**; the **runs** (file and its SHA-256, run date,
isotope, molecule, method, conditions); the **processing** (the spike rule and how many were
excluded, the area of each region holding an excluded spike *with it kept* beside its result,
the background and how it was taken, decay correction); the **spikes** (each one: time, as
recorded, as bridged, region, excluded or kept); the **results** (the columns ticked
underneath). Right: the report as it will be written. **Save report…** (Ctrl+S) writes it;
**Copy** puts its text and tables on the clipboard. Your choices are kept for next time.

## Options

**Options** opens its own window, topics on the left. **Figure** — PNG and copy resolution,
copy as PNG or SVG, what shows behind the preview. **Isotopes** — the Isotope list, half-lives,
and a tick per isotope for **decay correction** (all off at first). **Methods** — region names
by retention time, per HPLC method: a row per region (method, name, Rt from, Rt to). **Log** —
times in its copy. Every change is saved at once, to `spikeless_options.json` beside
`Spikeless.bat`; **Export… / Import…** carry them to another computer, **Reset to defaults**
starts over.

## Sessions

**Save…** writes the runs — their data, spikes (and those put back), background, regions with
their names and notes — and the figure's settings to one `.spikeless` file. **Open…** or a drop
opens it; if something is open, Spikeless asks before replacing it (Ctrl+Z brings it back). The
GINA files are not needed again. Session files from 2026.10.14 open too: each dataset becomes a
run, its spikes are found again, the peaks of its last processed curve become regions.

## How the numbers are made

### Spikes

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

An excluded point is bridged by the straight line between its two neighbours. The file is never
changed: the trace results use is computed from it each time, so a spike put back is back.

### The trace

The recorded count rate (cps), spikes bridged, then — when the run's isotope is ticked in
Options › Isotopes — each point corrected to the run start, × e^(λ t). Within a 15-min run that
is 0.1 % for ¹⁷⁷Lu, 3 % for ⁹⁹ᵐTc, 17 % for ⁶⁸Ga.

### Net counts, ± and % of total

A region's **net counts** are the counts of the trace above what lies under it — the
background, or a straight line between its ends — integrated by trapezoids (count rate × time).
**±** is 1 σ of counting statistics, √(gross + background counts). **% of total** is of all the
net counts of the run (the trace minus the background, over the whole run): the radiochemical
purity as Ph. Eur. defines it, relative to all the activity of the radionuclide. What no region
holds is the **Outside the regions** row, so the regions and it add to 100 %. **% of regions**
is of the regions only.

### Detection and quantification limits

From the background counts *B* under a region (Currie 1968): **L_D** = 2.71 + 4.65 √B and
**L_Q** = 50 (1 + √(1 + B/12.5)) — where its relative uncertainty falls to 10 %. Below L_D a
region is **n.d.** (no % given); between L_D and L_Q it is flagged **< LOQ**. A run whose total
net counts are below its own detection limit has no activity above background: no % at all.

### Find peaks

Maxima of the trace's 5-point mean that stand 5 σ above their surroundings, σ the Poisson noise
of that mean at the background count rate; at least 10 s apart. Each becomes a region from its
feet (where the 5-point mean falls back within 2 σ of the background) or the valley it shares
with a neighbour; it is kept if its net counts exceed L_D. On the example runs: both peaks of
the HOPO run; the ¹⁷⁷Lu product at 7.90 min (97.7 %), the impurity at 2.55 min (2.2 %) and two
traces < LOQ of the Imathera2 run; nothing on a 120-min blank injection.

### System suitability (Ph. Eur. 2.2.46)

**w½** the width at half height; **symmetry** w₀.₀₅ / 2d (1 = symmetric, > 1 tailing);
**resolution** 1.18 (t₂ − t₁) / (w½₁ + w½₂) from the region before; **S/N** 2H / h, H the
height above background, h the range of the background (points outside every region) within
5 w½ of the region.

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
  interpolated point.

They differ only if the gap is handled otherwise, and the alternatives are worse. The one
example spike inside a peak — a 3 120 cps sample between 25 and 211 cps, on the rising edge of
a ¹⁷⁷Lu product peak — with the peak's counts summed point by point above the 7 cps background:

| How the spike is handled | Peak area (counts) | vs. bridging |
|---|---|---|
| Kept (no cleaning) | 18 489 | +19.4 % |
| **Excluded, gap bridged linearly** (= linear interpolation) | **15 487** | — |
| A smooth curve across the gap (PCHIP) | 15 448 | −0.25 % |
| Excluded, counts summed with that second missing | 15 376 | −0.7 % |
| Excluded, sum rescaled by the points kept | 15 889 | +2.6 % |

Summing without the point loses the counts of that second: little on a flank (here 118
counts), the local count rate × 1 s at an apex (~20 % of a peak). Rescaling assumes the missing
second was average for the peak, which a point on a flank is not. A smooth curve adds an
assumption for no gain (Spikeless no longer offers it). So: **exclude the point and bridge it
linearly**, and **say it that way** — excluded, not corrected.

### What makes it rigorous

1. **A rule fixed in advance**: the default threshold, or your procedure's — not moved run by
   run until a result looks right.
2. **Only isolated single points**: Max width 1. A wider event is real signal or another fault,
   and is reported as such.
3. **Raw data kept**: the GINA file is untouched, and its SHA-256 is in the report.
4. **Every exclusion listed**: Report › Spikes (time, as recorded, as bridged, region).
5. **Its effect shown when it matters**: Report › Processing gives the area of a region holding
   an excluded spike with the spike kept, beside its result.
6. **The figure says it**: in the caption, or show the excluded spikes on it (Figure › Shows).

### Methods text

With the default settings, adapt the numbers:

> Single-point spikes — isolated electronic artefacts of the flow radio-detector — were
> identified with a Hampel filter: a point was flagged when it exceeded the 7-point moving median
> by more than 5 robust standard deviations (median absolute deviation × 1.4826, at least the
> Poisson noise of the local count rate) and exceeded both adjacent points by the same margin;
> runs of more than one point were not flagged. Flagged points (n = …, … of them within
> integrated peaks) were excluded and their 1-s intervals bridged by linear interpolation
> between the adjacent points. Peaks were integrated above the mean background count rate
> (… cps, outside the integrated regions) and reported as net counts and % of the total net
> counts of the chromatogram; counting uncertainties are 1 σ, detection and quantification
> limits after Currie (1968). Processing: Spikeless <version> (github.com/jakubtoczek/spikeless).

### In a GMP or regulatory record

Spikeless is not a validated computerised system: no audit trail, no user accounts, no
electronic signatures. Where a result is a GMP record — batch release, a regulatory file — the
result of record comes from the validated chromatography data system, and excluding a point
follows the site's procedure there (justified, documented, the original kept). Spikeless can
show and document what was excluded, and why.

## When something looks wrong

- **A peak is not found.** Find peaks keeps what passes the detection limit; a peak below it is
  not distinguishable from background noise. Draw it by hand to see its counts (it will say
  n.d.).
- **A flagged point is not a spike.** Untick it in ② Spikes; or raise the **Threshold**.
- **A region's edge is in the wrong place.** Drag it (Alt for exactly where you let go), or ← →.
- **A small peak on another's tail.** Select it, set *Under it* to **a straight line between its
  ends**.
- **% does not match what you expect.** % of total counts everything above background,
  including what lies outside your regions (its own row). % of regions is the other column.
- **The background looks wrong.** Tick Background above the plot; pick a peak-free stretch
  (③ Mean of a stretch).
- **Can't see a small peak.** Zoom: wheel over it, Ctrl+wheel for the height.
- **The plot is lost.** Double-click it.

## Shortcuts

| Key | |
|---|---|
| Ctrl+O · Ctrl+S | open · save the session (in the Report window: save the report) |
| Ctrl+Z / Ctrl+Y | undo / redo every change to a run |
| Ctrl+C | copy the figure, the results table (when it has focus), or the selected text |
| Ctrl+V | paste columns as runs |
| Del | remove the selected region (plot or table), or run (run list) |
| ← → | move the last-touched region edge one point |
| wheel · Ctrl+wheel · right-drag · double-click | zoom time · zoom height · pan · whole run |
| drag · Alt+drag | draw a region · without snapping to the valleys |
