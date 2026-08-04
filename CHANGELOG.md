# Changelog

Notable changes to this repository, newest first. Dated by when the change
was committed (not necessarily the same day it's pushed).

## 2026-08-04 — mzML Scan Detector gets a status button; simpler file picker; In-silico Library split into two workflows

Sidebar width range narrowed to 10%-20% of screen width (was 14%-32%).

mzML Scan Detector's "Find scans" action now shows immediately when the
page opens (disabled/yellow with a reason until a file is picked), matching
every other module -- previously the whole page was hidden behind a "pick a
file first" gate with no visible action control at all.

The mzML file picker (`common.ui.pick_mzml_files`, shared by mzML Scan
Detector, MS Matching, and Setup) no longer offers a multiselect over files
auto-discovered under `data/mzml/` alongside a separate custom-paths box --
that discovery half went unused in practice, so it's now just the one text
area of full paths.

In-silico Library is now an explicit choice between two workflows: **Load
existing library** (just view whatever's already on disk, or wherever the
Setup page points) and **Generate a new library** (map a source and run
Normalize/Build). Stats for a step only appear in the "Generate" workflow
once *this session* has actually run it -- not just because a file happens
to already exist from an earlier session, which previously made it
impossible to tell a fresh result from stale leftovers, or to even choose
between the two.

## 2026-08-04 — Sidebar drag-resize fixed, redundant title removed, buttons generalized

The narrower sidebar from earlier today pinned an exact pixel width with
`!important`, which silently fought every drag-resize attempt (it looked
frozen). Replaced with a percentage-based `min-width`/`max-width` range only
-- the sidebar now actually scales with screen width and drags freely
between those bounds.

The app-level title/caption ("DUF62 Fluoro Project / Finding naturally
fluoroacetylated...") used to render above every single page's own title,
redundantly. Now shows only on the Setup landing page.

Molecule Explorer's color-coded button pattern (green = possible, yellow =
not yet, status line underneath) is now a shared helper
(`common.ui.status_button`) and applied to In-silico Library's Normalize/
Build buttons and to MS Matching's "reload saved result"/"view a saved
variant"/"Run match" actions. Not applied to mzML Scan Detector or Setup --
neither has an action that's ever actually "not possible" in the same way
once its own precondition (a file picked) is already met, so a colored
button there wouldn't carry real information.

## 2026-08-04 — Explanatory hints, a narrower sidebar, and Molecule Explorer's color-coded buttons

Added explanatory "?" hints to widgets where they genuinely clarify something
non-obvious -- not a blanket pass over every widget. Covers: the main match
tolerance and MS level selector on both mzML Scan Detector and MS Matching,
relative-intensity's per-scan (not global) meaning, the absolute-intensity
floor's relationship to that filter, the acetyl co-occurrence check's actual
purpose, and the acetyl tolerance's independence from the main one.

The sidebar is now a fixed, narrower width via CSS (no native Streamlit
setting controls this). Molecule Explorer's three data-loading buttons are
now large, color-coded (green when possible right now, yellow when not, with
the reason underneath), and laid out side by side across the page's full
width instead of stacked.

## 2026-08-03 — Fine-grained tolerances; Molecule Explorer's loader redesigned button-first

MS Matching's MS2 precursor/ion tolerance and the acetyl co-occurrence
tolerance/RT-window fields couldn't accept a value like 0.002 -- stuck at
0.01 steps, since they were missing the explicit `format=` the main
"Tolerance" field above them already had. All four now match that field's
precision.

Molecule Explorer's data-loading section (added earlier today) is now
button-first rather than always showing full text/inputs: each of the three
options is a single button with an automatically-computed status line right
under it saying whether that action is possible right now, and why not if it
isn't. The folder/file picker (previously always visible) is now hidden
behind its own toggle button, only appearing once requested.

## 2026-08-03 — Molecule Explorer can load its own data

Molecule Explorer previously had no way to get data onto the page besides
visiting MS Matching first (its auto-load populates the shared session state
Molecule Explorer reads) -- opening it directly in a fresh session showed a
dead end telling you to go run a match elsewhere. It now offers three ways to
get data, without leaving the page: load the already-computed default result;
point at any folder (offering a picker if it holds more than one saved filter
variant) or a specific file; or, if a suspect library and mzML file selection
already exist but no match has been run yet, run one directly.

The match-running logic itself was extracted out of MS Matching's "Run
match" button handler into a standalone function, reading its settings from
persisted state rather than page-local widget variables -- both the button
and Molecule Explorer's new "run whatever's missing" action call the same
function, so they can't drift apart.

## 2026-08-03 — Smoother progress bars; MS2 filter settings visible before running a match

`load_user_table` (In-silico Library's Normalize step) and `build_library`
(its Build step) used one `progress_every` value to drive both the
console/status-text print *and* the GUI's progress-bar percentage, defaulting
to 20,000 rows -- so the bar only moved every 20,000 rows, looking stalled in
between on a large library. Decoupled the two: the console/status-text print
interval is unchanged, but the progress-bar percentage now updates on its own,
much finer cadence, scaled to the table's size (roughly 300 updates total,
via a new `progress_fraction_every` parameter defaulting to `max(1, total //
300)`) -- smooth on a small table, and not hundreds of thousands of individual
bar-update calls on a huge one.

MS Matching's MS2 diagnostic-ion filter had its checkbox in Optional filters
(visible before running anything), but its actual settings -- precursor/RT/ion
tolerance, and the "no active target" warning -- only rendered after a match
result already existed, unlike the acetyl co-occurrence filter right above it,
whose settings are visible immediately. Split the settings out into their own
function, rendered right next to the checkbox, so they're visible and
adjustable pre-run now too; only the actual "Run MS2 cross-check" button and
its "missing column" check (which genuinely need a real result) still live
post-run.

## 2026-08-03 — Per-module run history (small CSV logs), replacing a slow live recount

Added `common/run_log.py`: a small shared helper that appends one summary row
(counts, timing, key parameters) to a plain CSV each time a pipeline action
actually finishes (Normalize, Build suspect library, Run match, MS2
cross-check), and renders that history as a table on the relevant page. Each
action gets its own log file (its own natural set of columns) rather than one
shared file.

This also removes a live recomputation that used to run on every single page
render of In-silico Library: how many normalized compounds have a reactive
functional group. That count is now recorded once, in the Build step's own
run history, generically labeled by whichever functional group that run
actually targeted -- not hardcoded as a permanent "primary amine" fixture of
the page (primary amine is currently the only implemented functional group,
chosen as the easiest benchmark case; others are expected later).

## 2026-08-03 — Code review pass: a real chemistry bug, a crash, several smaller fixes

A systematic read-through of every module, prompted by several rounds of
live-testing issues. Findings below, ordered roughly by severity.

### Fixed -- chemistry correctness
- `build_suspect_library.py` derived a compound's reactive-site count from
  `len(products)` (the deduplicated mono-acylation product list), not the
  actual number of reactive sites. For a symmetric multi-site molecule (two
  equivalent amines), both sites yield an identical product after
  deduplication, so the site count silently came out as 1 instead of 2 --
  meaning the degree-2 (both-ends-acylated) row was never added to the
  multidegree table for any symmetric multi-site compound in the library,
  even though `multi_degree_formulas()` computes it correctly whenever it's
  actually asked. Fixed to use `count_reactive_sites(mol)` directly.

### Fixed -- crashes
- MS Matching's "View a saved result from output/" crashed when loading any
  of the three `candidate_features*` variants: they're already a final,
  collapsed table and were stored directly as the page's "raw hits" table,
  but the summary/structure-grid code unconditionally expects raw-hit-shaped
  columns (`scan_index`, `product_smiles`, ...) that a collapsed features
  table never had. Now shown with a plain message instead of crashing;
  Molecule Explorer read the same session state and would have hit the
  identical crash.
- `mzml_tools/plotting.py`'s `save_xic_figure` crashed (`max()` on an empty
  sequence) if requested against an MS level with zero matching scans in the
  file. Guarded the same way its sibling function already guards the same
  situation.

### Fixed -- real, currently-masked bugs
- Several `@st.cache_data`-wrapped functions (added across today and
  earlier work) took their cache-busting mtime argument as `_mtime` --
  Streamlit excludes any leading-underscore argument from the cache key
  entirely, so a changed file would silently keep returning the *old*
  cached result instead of recomputing. Currently masked wherever this
  session's own code always calls `st.cache_data.clear()` right after
  writing, but not if the underlying file changes from outside the app
  (e.g. the merge notebook, a bare CLI run, or a file replaced while the app
  is open). Renamed to `mtime` (no leading underscore) everywhere this
  pattern appeared.
- The "save once per fresh dataset, not on every rerun" fix from earlier
  today (added to stop a large result table being rewritten to disk on
  every single page interaction) had its own bug: the early return added to
  skip a redundant disk write also skipped the download button/oversize
  notice on every rerun after the first. Decoupled: the write still happens
  at most once, but a working download control (or accurate size notice)
  now shows on every render.
- `build_suspect_library.py --limit` (documented as "for a quick test run")
  ran the expensive per-row RDKit primary-amine/mass computation over the
  *entire* input table before slicing to `--limit`, defeating its own
  purpose on a real, large library. Reordered so the slice happens first.

### Changed -- smaller fixes and cleanup
- Two places read a shared/cross-page `session_state` key directly instead
  of via `restore()` first, working today only because of the current call
  order within their own function -- the same class of bug fixed several
  times already today, hardened here before it recurs: `setup/gui.py`'s
  status metrics, and the mzML Scan Detector's per-target "Explore" button
  (read tolerance/unit/etc. before the page's own `restore()` calls for
  them had run yet this render).
- "Add target" (mzML Scan Detector) cleared the label field after adding
  but not the m/z field, leaving a stale value for the next entry -- now
  clears both.
- A stray "bonus" description of the MS2 filter survived on the Setup
  page's module list (missed in an earlier wording pass elsewhere).
- Removed a couple of small dead-code/inefficiency items found during the
  review: an unused return value in the mzML Scan Detector, a
  `persist()` call that ran once per existing diagnostic target on every
  render instead of once total, and a vestigial cleanup key in MS Matching
  that named a file nothing actually writes.

## 2026-08-03 — Fix two silent multi-minute slowdowns on every page rerun

### Fixed
- MS Matching re-saved the full raw-hit table (CSV *and* parquet, hundreds
  of MB for a real result) to `output/` on *every* page rerun -- including
  ones triggered by an unrelated interaction like toggling a checkbox -- not
  only once when the result was actually new. This made the rest of the
  page, and anything below the results table, visibly slow to appear after
  any click, easily read as the page being stuck. Now saves each result
  variant once per fresh dataset, tracked per file, not on every render.
- In-silico Library recomputed `has_primary_amine` (RDKit, one substructure
  match per row -- deliberately not stored as a column, see the schema note
  in `db_loader.py`) from scratch on every page rerun to show a single
  count metric. For a real library (hundreds of thousands of rows) this
  alone took ~6 minutes (measured: 359s for 463,329 rows), with nothing
  rendering below it and no visible feedback that anything was happening.
  Cached per normalized file
  (only reruns when the file actually changes) with a spinner shown while it
  computes the one time it does; the equivalent step in "Build suspect
  library" also now shows a spinner instead of no feedback at all.

## 2026-08-03 — MS2 filter: drop "bonus" framing, keep its settings visible

### Changed
- Stopped calling the MS2 diagnostic-ion filter a "bonus" filter (in its
  checkbox label, section heading, and docstrings/README) -- it's just
  another filter, not an optional extra.
- Its own settings (precursor/RT/ion tolerance) are no longer hidden when
  there's currently no active diagnostic target or the loaded result
  predates this filter -- those cases now show as plain warnings (with the
  "Run MS2 cross-check" button disabled) while the settings themselves stay
  visible, same as every other filter's settings once it's checked.

## 2026-08-03 — Actually show "task finished" messages

### Fixed
- Normalize/Build (In-silico Library) called `st.rerun()` immediately after
  `st.success(...)` -- the rerun discards that message before the browser
  ever renders it, so the completion banner was never actually seen. Removed
  the unnecessary rerun (the page already reflects the fresh result on the
  same run without it).
- Both `load_user_table` and `build_library` printed progress checkpoints
  every N rows but never a final "done" line -- watching the console alone
  gave no completion signal either. Both now print (and pass through their
  text callback) an explicit final summary when finished.

### Added
- `common.ui.notify_done`/`render_last_notification`: a two-part completion
  signal for every long-running action (Normalize, Build suspect library,
  Run match, MS2 cross-check) -- an `st.toast` for an immediate, hard-to-miss
  alert, plus a persistent success banner that (unlike a one-time message
  inside a button's own `if` block) survives page reruns and stays visible
  until that same action next completes, in case the toast itself is missed.

## 2026-08-03 — Browse any saved MS Matching result from output/

### Added
- "View a saved result from output/": every filter combination MS Matching
  can produce (raw hits, acetyl-co-occurring subset, collapsed features,
  collapsed + acetyl-co-occurring, MS2-confident subset) is discovered
  directly from what's actually present under `output/` and can be loaded
  and viewed on demand, instead of only ever seeing the one most-recently-
  computed result. A persistent "Currently viewing: ..." banner names
  exactly which result (full/unfiltered, or which specific saved subset) is
  on screen at all times.

### Fixed
- Every result table (raw hits, its acetyl-co-occurring subset, collapsed
  features, its own acetyl-co-occurring subset) is now always saved to
  `output/` the moment it's computed, not only when it happened to be too
  large to offer as a direct in-browser download -- a smaller/more-filtered
  result (e.g. after a stricter run) previously vanished the moment the
  session ended, with nothing on disk to load back later.
- Viewing a saved result variant no longer re-saves it under a different
  file's canonical name (which would have silently overwritten that other
  file's content, e.g. viewing the MS2-confident subset overwriting plain
  `candidate_features.parquet`).

## 2026-08-03 — MS2 confidence filter moved next to the other filters

### Changed
- The MS2 diagnostic-ion high-confidence filter is now a checkbox in
  "Optional filters", same as acetyl co-occurrence and feature collapsing,
  instead of its own separate section a user had to scroll past the whole
  page (including the feature map) to find. Its results now render inline
  right after the main summary, and the filter's own caption now states
  explicitly that matching any one active diagnostic ion is enough for an
  MS2 scan to count (a scan/feature-level OR across targets, not an AND).

## 2026-08-02 — Real progress bar while normalizing a library

### Added
- "Normalize library" now shows an actual progress bar, not just a status
  line -- a full real-world library (hundreds of thousands of rows) can take
  tens of minutes to parse via RDKit, and with only a status line updating
  every 20,000 rows it wasn't obvious the app was still working rather than
  stuck. `load_user_table` gained a `progress_fraction_callback`, the same
  pattern `build_library`'s progress bar already used.

## 2026-08-02 — Accept InChI/SMILES independently; fix two persistence bugs

### Changed
- In-silico Library's column mapping no longer forces one combined
  "structure column": map an InChI column, a SMILES column, or both
  independently (either is sufficient on its own; if both are mapped, InChI
  is tried first per row, falling back to SMILES only where the InChI value
  is missing or unparseable). There's still no InChIKey column to map -- it's
  a one-way hash with no structure to recover from it alone.
- Removed the editable "Source label" field from that same page; the
  `source_db` bookkeeping value is still recorded, just derived silently from
  the file name instead of exposed as a control, since the app doesn't
  actually support merging more than one normalized library in a single run
  (the caption describing that use case was aspirational, not real).

### Fixed
- The mzML Scan Detector's diagnostic ion target list wasn't wired into the
  settings-persistence system at all, so it never saved with a settings
  preset regardless of which page was active. MS Matching's own read of that
  list also needed a `restore()` first, same reasoning as other shared keys
  -- reading it directly worked only while the Scan Detector page itself was
  the one currently mounted.
- Computing `has_primary_amine`/`exact_mass` from a stored InChI crashed if
  that InChI failed to re-parse (an `AttributeError`, since RDKit returns
  `None` rather than raising) or wasn't a string at all (a `NaN` value slips
  past a bare truthiness check, since `NaN` is truthy in Python) -- both are
  now treated as "no structure" instead of crashing.

## 2026-08-02 — Merged structure table no longer bakes in computed columns

### Changed
- `db_loader.py`'s merged structure table (`inchi`/`inchikey`/`smiles`/
  `formula`/`name`/`organism`/`source_db`) no longer includes
  `has_primary_amine` or `exact_mass`. Neither is something any source
  database actually supplies, and the project will classify reactive sites
  beyond just primary amines over time -- that kind of task-specific
  chemistry belongs downstream, not baked into a general-purpose merged
  structure table. Both are computed fresh, right where they're needed
  (`build_suspect_library.py`, the In-silico Library page's "Build" step),
  via new `has_primary_amine`/`compute_primary_amine_flags`/
  `compute_exact_mass_series` helpers.
- The DNP/LOTUS/HMDB merge that produces `data/unified_structures.parquet`
  now lives in `notebooks/build_unified_library.ipynb` (calling the same
  `db_loader.py` loaders) instead of only being reachable via a bare CLI
  call -- the merge process is now visible on GitHub with its real saved
  output. The three source databases are outside the repository regardless,
  so re-running it needs your own local copies; reading it doesn't.

## 2026-08-02 — Guard the In-silico Library page against a bad column mapping

### Fixed
- Normalizing a library whose structure-column mapping pointed at something
  unparseable (e.g. an InChIKey, which is a one-way hash) silently produced
  an empty, columnless result file; opening the page again then crashed with
  a raw `KeyError` instead of showing anything useful. A normalize run that
  parses zero rows now shows a clear message instead of writing that file,
  and the page also checks any already-written result for the columns it
  expects, offering to delete a stale/broken one instead of crashing on it.
- The structure-column mapping no longer defaults to blindly picking the
  first column in the table -- it prefers an obviously-named one
  (`inchi`/`smiles`/`structure`/`canonical_smiles`) when present, since a
  table listing its hash column first was exactly how the above got
  triggered in practice.

## 2026-08-02 — Auto-load results; fix a real setting-sharing bug

### Added
- Setup page: optional paths to an already-built suspect library and an
  already-saved MS Matching result, defaulting to each module's standard
  output location. In-silico Library and MS Matching now auto-populate from
  disk the moment you open them, instead of requiring a manual "load" click
  every session.
- mzML file discovery now looks under `<repo root>/data/mzml/` instead of a
  path outside the repository -- a convention any clone can use.

### Fixed
- The Setup page's shared mzML selection silently dropped any file entered
  as a custom path (rather than picked from the discovered-files list) --
  it displayed correctly on the Setup page itself, but never reached any
  other page's default selection. Every reader now goes through one
  function that correctly combines both halves of that picker.
- Loading a settings preset wiped out any setting the preset predated
  (added since it was saved), instead of only touching the settings it
  actually specifies.

### Changed
- Hid the top-right "running" indicator's icon (not configurable through
  Streamlit itself); the "Stop" button next to it still works as before.

## 2026-08-02 — Add a Setup page; accept any user-supplied library

### Added
- New Setup page (first in the sidebar): explains what each other page does,
  and holds one shared mzML file selection + library file path that every
  other page's own picker now seeds its default from -- pick files/a library
  once, still change them per page if needed.
- In-silico Library no longer requires the specific DNP/LOTUS/HMDB merge: it
  reads whatever library file path is set on the Setup page (any CSV or
  Parquet), lets you map which column holds each compound's structure
  (InChI or SMILES) plus optional name/organism columns, and computes
  everything else (formula, exact mass, InChIKey, whether a compound has a
  primary amine) from that structure. `db_loader.py` gained
  `load_user_table` for this; the existing DNP/LOTUS/HMDB-specific loaders
  are unchanged.

### Changed
- The suspect library (and its new normalized-input intermediate) now write
  to `output/`, not `data/` -- both are computed results, not input data;
  only an example raw structure table stays in `data/`.
- `common.ui.pick_mzml_files` gained a `default` parameter so a page's file
  picker can start pre-selected from another page's choice without becoming
  the same, always-in-sync widget.

## 2026-07-31 — Add an MS2 diagnostic-ion high-confidence filter

### Added
- mzML Scan Detector: multiple files can now be picked at once, with a
  selector for which one is currently active, plus a curated list of
  diagnostic fragment-ion targets (add/remove, explore each one
  individually, and mark whether it should be used downstream).
- `comparison/ms2_confidence.py`: associates an MS Matching feature with a
  supporting MS2 scan by precursor mass and RT proximity to the feature's
  apex, then checks that scan's peaks against the diagnostic ion targets. A
  new "MS2 diagnostic-ion high-confidence filter" section on the MS Matching
  page runs this as a bonus, more-filtered view on top of the existing result.
- `collapse_to_features` now also records each feature's observed mass at
  its apex scan (needed for the precursor association above).

## 2026-07-31 — Switch navigation, add settings persistence and presets

### Changed
- `main.py` navigation is now `st.navigation` (a sidebar page list) instead
  of `st.tabs`: tabs executed every page's code on every single rerun no
  matter which tab was visible, so a heavy page kept slowing down clicks
  made entirely on a different, unrelated page. Only the active page's code
  runs now.

### Added
- `common/ui.py`: `restore`/`persist`, a small pattern every module's
  filters and selections now use so they survive switching pages (the
  navigation change above otherwise clears a widget's value whenever its
  page is unmounted).
- A "save/load a settings preset" control (sidebar): the current values of
  every persisted setting, across every module, can be saved to and loaded
  from a named local file.
- MS Matching: a "load previously processed data" option that reads a
  previously saved result straight from disk instead of re-running the
  matching pipeline.

## 2026-07-31 — Fix Molecule Explorer pagination

### Fixed
- "Load more" in the Molecule Explorer appeared to do nothing. The result
  table it reads was being recomputed into a new object on every rerun
  (not just when a match actually ran), which made the gallery's pagination
  cache think the data had changed and reset back to the first page on every
  interaction, including the one caused by the "Load more" click itself. The
  result is now only recomputed when a match completes.

## 2026-07-27 — Speed up the Molecule Explorer

### Fixed
- Structure images (main grid and the isomer dialog) are now cached, keyed
  on the molecule -- Streamlit reruns the whole page on any interaction
  anywhere, so without caching every already-shown structure was being
  redrawn from scratch every time, not just newly-shown ones.
- The isomer drill-down dialog rendered one structure per widget (image +
  several text elements); a formula pooling dozens of isomers turned into
  hundreds of individual elements, which was far more expensive to
  transmit/render than the actual structure drawing. Replaced with one
  composed grid image (same approach as the top-10 structure grid) plus a
  compact table for exact numbers.

## 2026-07-27 — Degrade gracefully when RDKit's Draw module is unavailable

### Fixed
- A broken `rdkit.Chem.Draw` install (e.g. a DLL load failure) crashed the
  whole MS Matching / Molecule Explorer page. Structure rendering now fails
  gracefully with a one-time warning instead -- everything else on the page
  (tables, charts, filters) still works.

## 2026-07-27 — Add a Molecule Explorer tab

### Added
- New `explorer` module: a sortable, paginated gallery of the compound
  structures from a MS Matching run (3 cards per row, 24 at a time, "load
  more"). Each card shows the formula, scan count, and isomer count, with a
  hover overlay for more detail and a click-through modal listing every
  individual structure pooled into a formula with more than one.
- `comparison/matcher.py`: `structures_by_formula` (every formula, not just
  the top 10 -- vectorized, no per-formula loop) and `isomers_for_formula`
  (drill-down for one formula's individual structures).
- `comparison/plotting.py`: `mol_image_data_uri`, for embedding a structure
  directly in an HTML card.

### Fixed
- A missing `parent_name` is `NaN` (truthy in Python), not `None` -- code
  checking it with a bare `if`/`or` let it through and then crashed
  formatting it. Fixed everywhere it's checked.

## 2026-07-27 — Fix summary figures, sharpen the structure grid

### Fixed
- The scan-count bar chart and structure grid were built from all features,
  not the acetyl-co-occurring subset when that check was enabled -- now
  built from the final, most-filtered result.
- `top_structures_by_formula` now reports how many distinct structures each
  formula bucket pools together (`n_isomers`), shown on the structure grid,
  since only one representative is ever drawn per formula.
- The structure grid's resolution was too low to read the legend text at
  normal zoom; roughly quadrupled (larger sub-image size, larger legend font).

## 2026-07-27 — Tab navigation, real progress bars, richer result visuals

### Changed
- `main.py` navigation is now tabs, not a sidebar radio: every module stays
  mounted and its widget state stays intact no matter which tab is currently
  visible.
- The MS Matching and In-silico Library "run" buttons now show a real
  progress bar (per-file and per-spectrum for matching; per-checkpoint for
  library building), not just an indeterminate spinner.

### Added
- `comparison/matcher.py`: `scan_count_breakdown` (feature counts against a
  set of minimum-consecutive-scans thresholds) and `top_structures_by_formula`
  (top 10 product formulas by total scan evidence, deduplicated by formula).
- `comparison/plotting.py`: static (matplotlib/RDKit) figure export for the
  above plus the existing RT-vs-mass scatter, written to `output/figures/`
  automatically on every run (CLI and GUI).
- MS Matching GUI page: a "Summary" section with a bar chart (scan-count
  breakdown) and an RDKit 2D-structure grid (top compounds by scan evidence)
  above the existing feature-map scatter, which is now the last, most
  detail-oriented view rather than the only one.

## 2026-07-27 — RT-bound acetyl co-occurrence, co-occurring export, result visualization

### Changed
- Acetyl co-occurrence now requires the acetyl analog to be found within an
  RT window of the fluoroacetyl hit's own retention time
  (`--acetyl-rt-window`, default 2.0 min), not just anywhere in the file.

### Added
- `matcher.filter_acetyl_cooccurring` and matching CLI/GUI exports: the
  acetyl-co-occurring subset is now also written on its own
  (`*_acetyl_cooccurring.parquet`/`.csv`), alongside the full table, for both
  the raw-hit and (if enabled) collapsed-feature tables.
- MS Matching GUI page: an RT-vs-mass scatter plot of the result set (sized
  by intensity, colored by acetyl co-occurrence when available) underneath
  the results table.

## 2026-07-27 — Add minimum-intensity and minimum-consecutive-scans filters

### Added
- `run_match_pipeline` (and `run_match.py --min-intensity`/
  `--min-consecutive-scans`, and matching GUI inputs): a hit now only counts
  if its peak clears an absolute intensity floor (default 50,000) and is
  part of a run of at least N scans in a row for the same file/product
  (default 3, same RT-proximity contiguity as feature collapsing). Both
  default on, both can be disabled (0 / 1 respectively).
- `matcher.filter_min_consecutive_scans`, and a shared `_assign_run_ids`
  helper factored out of `collapse_to_features` so both use the same
  contiguity definition.

## 2026-07-27 — Collapse per-scan match hits into elution-level features

### Added
- `comparison/matcher.py`: `summarize_candidate_table` / `format_summary`
  explain what a raw hit count actually represents (one row per scan a
  feature spans, not one row per compound) — printed by `run_match.py` and
  shown in the GUI, and written alongside the candidate table as
  `candidate_table_summary.txt`.
- `collapse_to_features`: merges raw per-scan hits for the same file/product
  into one row per contiguous elution event (grouped by retention-time
  proximity, not raw scan index, since MS1/MS2 scans can interleave).
  Available via `run_match.py --collapse-to-features [--max-rt-gap MINUTES]`
  and a matching checkbox in the GUI, which can then toggle between the raw
  and collapsed views.

## 2026-07-27 — Run the suspect-library/mzML matching pipeline from the GUI

### Added
- `insilico_library` and `comparison` now have working Streamlit pages
  (`gui.py`) instead of placeholders: building/inspecting the suspect
  library, and matching it against one or more mzML files, without leaving
  the app.
- Multi-file mzML picker: match against several files in one run; nothing is
  pre-selected, so a run always starts from an explicit choice.
- Optional match filters: MS level, minimum relative intensity, and an
  acetyl-co-occurrence sanity check (does a hit's non-fluorinated acetyl
  analog also appear in the same file?).

### Changed
- `comparison/matcher.py` now loads each mzML file once and reuses it across
  every target list matched against it, instead of reloading the file per match.
- Default matching tolerance for the primary fluoroacetyl search is now
  **0.002 Da absolute** (ppm still available as an option); the acetyl
  co-occurrence check defaults to **5 ppm**.

### Fixed
- The full-library match pipeline crashed (`ValueError` on a length mismatch)
  because it joined hits back to the library on `product_inchikey`, which is
  not guaranteed unique (different parent compounds can react to an
  identical product structure). Now joins on the library's own row index.
- The GUI could crash on large result sets, exceeding Streamlit's browser
  message size limit. Large tables are now capped on-screen and, when too
  large to send as an in-browser download, saved directly to `comparison/output/`.

## 2026-07-27 — List CHANGELOG.md in the README's directory tree

### Fixed
- Top-level `README.md` directory tree didn't mention `CHANGELOG.md`.

## 2026-07-27 — Add changelog

### Added
- This file.

## 2026-07-27 — Initial commit

### Added
- Streamlit GUI (`main.py`) with sidebar navigation across modules; dark theme.
- `mzml_tools`: scan detection against a target m/z, extracted-ion-chromatogram
  (XIC) computation, and static figure export for mzML files.
- `insilico_library`: merges multiple natural-product/metabolite databases
  into one deduplicated structure table (InChIKey-keyed); adds acetyl/
  fluoroacetyl groups to primary amines via real cheminformatics reactions
  (not formula string-hacking); includes a 20-amino-acid validation benchmark
  and a full-library build script.
- `comparison`: efficient matching of a large in-silico mass library against
  mzML data (binary search on sorted target masses), producing a candidate table.
- Conda (`environment.yml`) and pip (`requirements.txt`) dependency files;
  per-module READMEs.
