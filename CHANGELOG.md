# Changelog

Notable changes to this repository, newest first. Dated by when the change
was committed (not necessarily the same day it's pushed).

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
