# Spikeless — user guide

Everything the window does, how the numbers are made, and how to report them. For installing,
see the [README](README.md).

## A run, step by step

1. **Load.** Drop a GINA X `.txt` export on the window, or **Open…** (Ctrl+O). Several files:
   several runs, overlaid. Or copy columns in Excel or Prism (time, then count rate) — or a
   whole GINA export, Spikeless's own included — and press **Ctrl+V**; the log says what it
   assumed about units and layout.
2. **Spikes** are found and excluded at once: red marks on the plot, a line each in
   **Spikes** (time, height as recorded → as bridged). Click one to see it; untick one that
   is not a spike.
3. **Background** — nothing to do for a radio-detector: its step shows it (≈ 7 cps here), dashed
   on the plot.
4. **Regions.** **Find regions**, or **Draw region** and drag across a peak on the
   plot. Adjust an edge by dragging it. The results table under the plot gives each region's
   net counts, ± and **% of total** — the radiochemical purity.
5. **Name them** once for all runs of an HPLC method: Options › Methods (e.g. *free ¹⁷⁷Lu*
   2.3–2.8 min, *product* 7.5–8.5 min), then pick the run's method in **Runs** (show its Method
   in Options › Runs). Or type a name in the
   table.
6. **Report** (toolbar): tick sections and columns, check the preview, **Save report…** as PDF,
   `.odt`, Excel, Markdown or web page.
7. **Save…** (Ctrl+S) keeps the whole analysis in a `.json` file.

Ctrl+Z / Ctrl+Y undo and redo every change to a run; the log names each. Every field reads and
writes decimals with a dot, whatever Windows' region says.

## The window

The **plot** in the middle, the **Results** under it (the **Log** in the tab beside), the
**steps** on the right — Runs, Spikes, Background, Regions. The steps act on the **selected
run**; with none selected they say *select a run* and wait. Each step's ticks say what it
draws on the plot (for the selected run, or every run when none is); hover anything for what it
does. Drag the bar under a list (runs, spikes, regions: 5 rows at first) to make it taller.

### The plot

What the buttons do is set in Options › Chromatogram; by default:

- **Left click**: a **reading line** there — the time, the point (e.g. 554 / 1772), the count
  rate in the axis shown and the background excluded from it (a spike excluded there, too) —
  and a zoomed view slides to centre on it. A click in a region selects it. **← →** move the
  line a point at a time; a **right click** (or Esc) takes it away.
- **Left drag**: zoom to that span, the height fitted to it. **Right- or middle-drag**: pan.
- **Wheel**: zoom the time around the cursor (the height too, if unlocked in the options).
  **Ctrl+wheel**: zoom the height (to see a small peak beside a large one).
  **Double-click**: the whole run.
- Around the plot: **white**, its axes in dark grey, as the figure is (Options › Chromatogram:
  or the app's dark grey).
- The view is **elastic**: dragged past the start or the end of the run, or zoomed out past
  all of it, it springs back. Its edges stay put as the zoom changes the labels.
- On an **edge** of the selected run's regions, or of its background stretch, the cursor turns
  ↔: drag it (see [Drawing regions](#drawing-regions)).
- Above it: **Stack** (runs one above the other, background subtracted) and **Y**: the
  **count rate**; or each run, its background subtracted, as **% of max** (of its highest
  point) or **% of total** (each point's counts as % of all the run's net counts: the points add
  up to 100 %, so a peak's points add up to its % of total). Both apply to the figure too.
- **⧉ Copy** (or Ctrl+C): the plot as it is on screen, to the clipboard. The figure for a paper
  is the Figure window's.

### Results

A row per region of the selected run, then **Outside the regions** and **Total**. The columns
are chosen in Options › Results (the report picks its own): region, start, end, Rt, **net
counts**, **±**, **% of total**, % of regions, height, w½, symmetry, resolution, S/N, flags —
each explained there, and when hovering its header. Click a row to select the region;
**right-click**: rename, edit, remove; **Del** removes the selected rows (Ctrl+Z brings them
back). **⧉** (or Ctrl+C) copies the table, to paste into Word or Excel. **⤢** opens every
measure of each region, whatever the columns, with its **colour** (click the swatch), whether
the figure **labels** it, and its **note**.

The line above the table says how the numbers were made: background and how it was taken, the
run's total net counts, spikes excluded, decay correction.

### Runs

The runs loaded: **tick** to show, **click** to work on one, **click it again** (or F2) to
rename it, **double-click**: the plot shows it whole (the height stays that of every run).
**Right-click**: rename, export the **spikeless trace** (spikes excluded, decay-corrected if
so) or the trace **as recorded**, as a GINA-style `.txt`, remove. **Del** removes it (Ctrl+Z
brings it back). A click below the runs, or elsewhere on the panel away from the steps, or
**Esc**, selects none. For the selected run, as Options › Runs chooses: **Molecule**,
**Conditions** (one per line), **Colour**, and its details (original name if renamed, file,
run date, points, SHA-256); **Isotope** (its half-life and decay correction: Options ›
Isotopes) and **Method** (names the regions and gives the report its conditions: Options ›
Methods) are hidden at first — a hidden field keeps its value.

**Run names** (the green **▤** beside Runs, or Figure › Legend › Labels): a run keeps the name
it came with — its file's, *Clipboard 2* — and has two of its own: its **name**, what the app
and the report call it, and its **legend**, what the figure says. Grey: as it follows (the name
the original, the legend the name); white: set by hand. Clear a cell to make it follow again.
The original column is hidden unless asked for; the report gives the original beside a renamed
run.

### Spikes

**Show**: the spikes (red, from the bridged point to their height; a ring on one put back), the
trace as recorded — their colour and line: Options › Chromatogram. **Find spikes** flags them
with the rule beside it: **Threshold** (default 5 σ; lower finds more, higher fewer) and **⚙**
(the moving-median window, the widest run of points that can be a spike). **⟳** (on, green, at
first): found on their own — when a run is loaded, and as the threshold moves; off, only Find
spikes finds them. Each flagged point: time, height as recorded → as bridged, and the region it
falls in. **Click** one: the plot zooms on it, its reading line on it. Ticked = excluded;
**untick to keep it** (the point comes back, everywhere). A new run starts with Options ›
Spikes, where ⟳ is set too.

### Background

What lies under the peaks: the detector's background count rate (in the step's title). Each
way has its own **line** tick (its line on the plot, dashed; its style: Options ›
Chromatogram):

- **None**: nothing subtracted — the counts as recorded.
- **Mean outside the regions** (default): the mean of every point no region holds, leaving out
  any point 4 σ above it (a peak no region holds yet).
- **Mean of a stretch**: a peak-free stretch, **stretch** ticked to shade it on the plot: drag
  its edges there, type them (**from … to** min), or **Draw** and drag across one (or click its
  two edges).
- **Follows a drift** (SNIP or arPLS): for a trace whose background drifts. A radio-detector's
  is flat, so it is not offered at first.

Which ways are offered, and a new run's: Options › Background.

### Regions

A region is a span integrated as one: a peak, or a peak's shoulder. **Find regions** proposes
them for the peaks no region holds; **Threshold** (default 5 σ) and **⚙** (apexes at least 10 s
apart, on a 5-point moving mean, feet at 2 σ) say how. **⟳** (off at first): found on their
own, on load and as the threshold moves. Finding again, a region found and left untouched is
found again; one you named, moved, coloured or noted stays. A new run starts with Options ›
Regions, where ⟳ is set too. **Draw region**: see
below. The **list**: name, Rt, % of total. Click one to select it; double-click: the plot shows
it; **right-click**: **Rename** (or F2, or click it again), **Edit…**, **Remove** (or Del, the
selected ones). **Edit…** opens the region on its own, following the selection: its name, what
its net counts are above (**the background**, or **a straight line between its ends** — for a
peak on another's tail), a note (why it was drawn or moved, if it matters), its colour, whether
the figure labels it.

### Drawing regions

- **Draw**: push **Draw region** (it stays pushed in; the cursor turns to an open cross), then
  drag from a peak's left foot to its right foot — or click each foot. A right click or Esc
  cancels. The status line shows the net counts while you drag. Each edge lands on the lowest
  point within a few pixels of where you let go (3 points either side at most) — the valley —
  so a rough drag gives the region you meant; zoomed in until the points are that far apart, it
  lands on the nearest point. The line shown while dragging is where it will land. **Hold Alt**
  to place the edges exactly.
- **Adjust**: over an edge the cursor turns ↔; drag it (it lands as when drawn). **← →** move
  the last-touched edge one point. Two regions that touch share their edge (a perpendicular drop at the valley): moving it
  moves both. Regions never overlap: a drag across a neighbour stops at its edge.
- **Select** a region with a click (or its row, or its line in Regions); **Del** removes it.
- How each was placed is kept and reported: *auto* (Find regions), *drawn*, *moved* (found,
  then adjusted); *copied* in a session from before 2026.10.15.

## Figure

**Figure…** (toolbar) opens what its Copy and Export make. Left, each section folded until
opened (the ones you open stay open):

- a **preset** — journals' single columns are 80–90 mm wide, their double columns 170–190 mm:
  **Panel, 80 mm** (fits any single column, and two side by side fit any double column),
  **Panel, ⅓ of a 2-column figure, 55 mm** (three side by side), **the full 2-column width,
  170 mm**, all 7 pt (the two panels' region labels 6 pt); **Slide** (plot 160 × 90 mm, 14 pt).
  A panel's width is the whole of it, labels included;
- **Size**: the plot area in mm; the whole figure's width and height (Auto: the plot area plus
  its labels; fixed, the plot area is what is left);
- **Text**: one font for every text of the figure;
- **Traces**: line width, the background line, excluded spikes, the trace as recorded;
- **Regions**: shaded, their labels — **Name**, **% of total**, **Rt**, each ticked or not, a
  line each —, label size, opacity, and each
  region's colour, label and note (**edit ⤢**);
- **Legend**: shown (unticked and greyed while the figure has one run), where, an offset, its
  size, what it calls each run (**edit ▤**);
- **Backgrounds**: of the plot area and around it, and their opacity;
- **X axis**, **Y axis**: the **title** (text, size, gap to the labels); the **range** (from,
  to) and the axis line; the **major ticks** (every, first, last, in / out / across, length,
  thickness, labels size and gap); the **minor ticks** (shown — Auto, or on, or off —, how many
  per major interval, length, thickness); the **grid** at the major and at the minor ticks
  (line, colour, width).

Right: the figure as it will be written (wheel to zoom; the checkerboard is transparency).
**Copy** puts it on the clipboard at its real size (a PNG carries its resolution, so it pastes
into PowerPoint or Word at its size in mm); **Export…** writes PNG (600 dpi) or SVG. Its
settings are saved with the session.

**Legend**: **Auto** puts it inside, upper right or left, where it covers no trace — else
outside, to the right. Or pick one: inside (upper left, centre or right; centre right; lower
right, centre or left) or outside (above, left to right; right, top to bottom; below), then move
it by an offset in mm. Outside the plot the figure grows to hold it, the plot area keeping its
size (with the whole size fixed, the plot area shrinks instead). On screen the legend stays
inside.

Axes: the time starts at 0; the count rate a little below 0 (by default 3 % of its top,
Options › Figure), so the baseline clears the x axis. Auto ticks: on the count rate, 2 values
at least above 0, and no more than fit 8 mm apart (4 on a 32 mm high plot, 5 on 40 mm), every
1, 2, 2.5 or 5 × 10ⁿ; on the time, the minor ticks shown when they mark whole minutes, 4
between two majors (majors every 5 or 10 min). On a figure 80 mm wide or less, count rates of
3 digits or more are labelled in 6 pt (Y axis › *6 pt for counts ≥ 100*: untick to keep the
size set). Labels: a region with a name of its own
shows it; every region shows its % of total; regions below the quantification limit carry no
label (they are in the results).

## Report

**Report** opens its own window. Left: the **format** (PDF; `.odt`, opens in Word and
LibreOffice; Excel, a sheet per table and the figure; Markdown, the figure saved beside it; web
page) and the **sections**: the **figure**; the **runs** (the original name of a renamed run,
the file and its SHA-256, run date, isotope, molecule, the method and its conditions — column,
mobile phases, gradient, flow rate… from Options › Methods —, the run's conditions); the
**processing** (the spike rule and how many were excluded, the area of each region holding an
excluded spike *with it kept* beside its result, the background and how it was taken, how the
regions were found — threshold, spacing, feet — and how many were placed by hand, decay
correction); the **spikes** (each one: time, as
recorded, as bridged, region, excluded or kept); the **results** (the columns ticked
underneath). Right: the report as it will be written. **Save report…** (Ctrl+S) writes it;
**Copy** puts its text and tables on the clipboard. Your choices are kept for next time.

## Options

**⚙ Options** opens its own window, topics on the left. **Chromatogram** — what a left drag, a
right drag and a left click do on the plot, whether the wheel zooms the height too, white or
dark around the plot, and the colour and line of the trace as recorded, the excluded spikes and
the background line. **Figure** — how far below 0 the count rate starts, PNG and copy
resolution, copy as PNG or SVG, what shows behind the preview. **Runs** — what the Runs panel
shows (isotope and method hidden at first). **Spikes**, **Background**, **Regions** — what a new
run starts with: the spike rule, and whether spikes are found on their own (⟳, on at first);
the background, and which ways the step offers (none, mean outside the regions, mean of a
stretch — not one that follows a drift, at first); how regions are found, and whether on their
own (off at first). **Results** — the columns of the table under the plot, each explained.
**Isotopes** — the Isotope list, half-lives, and a tick per isotope for **decay correction**
(all off at first). **Methods** — region names by retention time, per HPLC method: a row per
region (method, name, Rt from, Rt to); and the method's **conditions** for the report, a row per
field (**＋ The usual fields** adds the column, mobile phases, gradient, flow rate,
temperature, injection volume, detectors to fill in). **Log** — times in its copy. Every change
is saved at once, to `spikeless_options.json` beside `Spikeless.bat`; **Export… / Import…**
carry them to another computer, **Reset to defaults** starts over.

## Sessions

**Save…** writes the runs — their data, spikes (and those put back), background, regions with
their names and notes, their names and legends — and the figure's settings to one `.json`
file (plain JSON, which other tools read too). **Open…** or a drop opens it; if something is open, Spikeless asks before replacing it (Ctrl+Z brings it back). The
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
**% of total** is of all the net counts of the run (the trace minus the background, over the
whole run): the radiochemical purity as Ph. Eur. defines it, relative to all the activity of the
radionuclide. What no region holds is the **Outside the regions** row, so the regions and it add
to 100 %. **% of regions** is of the regions only.

**±** is the 1 σ uncertainty of the net counts from counting statistics. The net counts are a
difference, N = G − B: G every count recorded across the region, B the background's counts under
it. Each is a Poisson count, whose variance is the count itself, so σ(N) = √(G + B). For the
¹⁷⁷Lu product of the example run, 109 778 ± 333 counts: 0.3 %. For a trace at 2.05 min, 92 ± 16:
17 % — under the quantification limit, where σ falls to 10 % of N, hence its *< LOQ*. The true
value lies within ± 1 σ about 2 times in 3, within ± 2 σ 19 times in 20; the % of total carries
the same relative uncertainty (σ/N × its %). It holds because a GINA export's value is the
count of one interval, as is: its detectors count the events per interval and pass that count to
GINA, and the example files bear it out — whole numbers only, and a background whose variance
is its mean (7.2 cps, variance 8.0; 6.5 cps, 6.6), as Poisson counts have; a sliding average or a
factor would leave fractions and shrink the variance. GINA's offset, factor and graphic smoothing
(its manual) should then be off for the exports read. Two things to know: B is taken as if counted over
the region alone, though it is the mean of far more points — so ± errs on the safe side; and
counting is all it holds — not the injection, the sampling, the detector's efficiency. It is the
floor of the uncertainty, not all of it.

**On the plot**, *% of total* shows each point's counts as % of the run's net counts: the points
add up to 100 %, a peak's points to its % of total. No standard sets a normalized axis for a
radio-chromatogram (Ph. Eur. 2.2.66 and 0125 define the purity as a ratio of areas, which the
results give); a figure usually shows the count rate, or % of max to compare runs' shapes.

### Detection and quantification limits

From the background counts *B* under a region (Currie 1968): **L_D** = 2.71 + 4.65 √B and
**L_Q** = 50 (1 + √(1 + B/12.5)) — where its relative uncertainty falls to 10 %. Below L_D a
region is **n.d.** (no % given); between L_D and L_Q it is flagged **< LOQ**. A run whose total
net counts are below its own detection limit has no activity above background: no % at all.

### Find regions

Maxima of the trace's 5-point mean that stand 5 σ above their surroundings, σ the Poisson noise
of that mean at the background count rate; at least 10 s apart. Each becomes a region from its
feet (where the 5-point mean falls back within 2 σ of the background) or the valley it shares
with a neighbour; it is kept if its net counts exceed L_D. (Those numbers are the defaults:
Regions › Threshold and More, Options › Regions.) On the example runs: both peaks of
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

- **A peak is not found.** Lower the threshold (Regions). Find regions keeps what passes the
  detection limit; a peak below it is not distinguishable from background noise. Draw it by
  hand to see its counts (it will say n.d.).
- **A flagged point is not a spike.** Untick it in Spikes; or raise the **Threshold**.
- **A region's edge is in the wrong place.** Drag it — zoom in to place it on a given point —
  (Alt for exactly where you let go), or ← →.
- **A small peak on another's tail.** Select it, set *Under it* to **a straight line between its
  ends**.
- **% does not match what you expect.** % of total counts everything above background,
  including what lies outside your regions (its own row). % of regions is the other column.
- **The background looks wrong.** Tick Background above the plot; pick a peak-free stretch
  (Background › Mean of a stretch).
- **Can't see a small peak.** Zoom: drag across it, or the wheel over it; Ctrl+wheel for the
  height.
- **The plot is lost.** Double-click it.
- **The steps say *select a run*.** Click a run in Runs.

## Shortcuts

| Key | |
|---|---|
| Ctrl+O · Ctrl+S | open · save the session (in the Report window: save the report) |
| Ctrl+Z / Ctrl+Y | undo / redo every change to a run |
| Ctrl+C | copy the plot as on screen, the results table (when it has focus), or the selected text; in the Figure window, the figure |
| Ctrl+V | paste columns, or a GINA export, as runs |
| Del | remove the selected regions (plot, results, Regions list), or run (run list) |
| F2 · Esc | rename the selected run or region · select none (run list); cancel drawing, clear the reading line (plot) |
| ← → · right click | the reading line a point along (or the last-dragged edge) · cancel drawing, or take the line away |
| ← → | move the last-touched region (or stretch) edge one point |
| click · drag · right-drag · double-click | reading line · zoom to the span · pan · whole run (Options › Chromatogram) |
| wheel · Ctrl+wheel | zoom the time (and the height, if unlocked) · zoom the height |
| Draw region, then drag or two clicks · Alt | draw a region · without snapping to the valleys |
