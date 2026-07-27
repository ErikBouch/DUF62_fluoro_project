# comparison

Match the in-silico suspect library (built in `insilico_library/`) against
real mzML data, producing a candidate table.

## `matcher.py` (logic — no Streamlit import)

`find_scans_with_multiple_mz` in `mzml_tools` checks every target against
every spectrum — fine for a handful of targets, far too slow once the target
list is a whole suspect library (tens of thousands of masses): that scales as
O(spectra × targets). `matcher.py` instead sorts the target masses once and,
for each spectrum, does a binary search per peak to find which targets (if
any) it matches — O(spectra × peaks × log(targets)), which stays fast even at
library scale since a spectrum's peak count is usually far smaller than the
target count.

```python
from comparison.matcher import load_experiment, match_experiment, run_match_pipeline

# one-off match against a single file:
exp = load_experiment("file.mzML")
matches = match_experiment(exp, targets, tolerance=0.002, unit="Da", ms_level=1,
                            min_relative_intensity=0.01)
# targets: list of (label, target_mz) -- can be tens of thousands of entries

# full pipeline (multiple files, fluoroacetyl/acetyl tolerances, optional
# acetyl co-occurrence check) -- this is what run_match.py and gui.py both call:
candidate_table = run_match_pipeline(
    library_df, ["file1.mzML", "file2.mzML"],
    fluoroacetyl_tolerance=0.002, fluoroacetyl_unit="Da",
    check_acetyl_cooccurrence=True, acetyl_tolerance=5.0, acetyl_unit="ppm",
)
```

Each mzML file is loaded once (`load_experiment`) and reused for polarity
detection and every target-list match against it (`match_experiment`), rather
than reloading the file per target list.

## `run_match.py` (CLI) / `gui.py` (Streamlit page)

Both are thin wrappers around `run_match_pipeline`: load the suspect library,
pick one or more local mzML files, and match the `reaction == "fluoroacetyl"`
rows (filtered to the appropriate adduct column for each file's dominant
polarity) against every file, joining hits back to the full suspect-library
row (parent/product formula, masses, reaction type) into one candidate table.
Everything is optional except the primary tolerance (default **0.002 Da**);
optionally also check whether each hit's acetyl analog co-occurs in the same
file (default **5 ppm**) as a chemistry sanity filter.

```bash
python run_match.py --limit 2000     # quick test run first
python run_match.py                   # full run
python run_match.py --check-acetyl-cooccurrence --acetyl-tolerance 5 --acetyl-unit ppm
```

The GUI page (`gui.py`) exposes the same options, supports selecting several
mzML files to match in one run, shows a real progress bar (per-file and
per-spectrum, not just a spinner), and caps the on-screen table (largest
result sets can't be streamed to the browser in full) while still writing
the complete result to `output/` when it's too large to offer as an
in-browser download. See "Result visualizations" below for what's shown
underneath the table.

## Result visualizations (`plotting.py` + `gui.py`)

Both the CLI (always) and the GUI (after every run) produce three figures,
built from two new aggregation functions in `matcher.py`:

- **`scan_count_breakdown`**: how many features clear each of a set of
  minimum-consecutive-scans thresholds (the currently-applied
  `--min-consecutive-scans` value plus 50/100/200/500) — rendered as a bar
  chart. Direct answer to "how many real candidates survive a stricter cut."
- **`top_structures_by_formula`**: the top 10 product formulas by total scan
  evidence (summed `n_raw_hits` across every feature sharing that formula --
  rewarding reproducibility over one broad peak in a single file),
  deduplicated so isomers/salt forms sharing a formula aren't shown
  redundantly. Rendered as an RDKit 2D structure grid (`product_smiles` is
  already a suspect-library column) -- a real structure reads faster than an
  InChIKey or a table row.
- The RT-vs-mass scatter ("feature map") from before is kept, but shown last
  -- it's a detail/exploration tool, not a summary.

Both aggregation functions accept either the raw `candidate_table` (they
collapse to features internally) or an already-computed `features_table` (to
avoid recomputing) — the scan count always means the same thing (a real
contiguous run) regardless of which view is currently selected.

Figures are written to `output/figures/` automatically on every run (small
PNGs, no reason to gate behind a button): `scan_count_breakdown.png`,
`top_structures.png`, `feature_map.png`. The GUI renders the bar chart with
Plotly (interactive) and the structure grid with `st.image` (inherently
static either way); `plotting.py` holds the matplotlib/RDKit static-export
versions of all three, following the same split already used in
`mzml_tools/plotting.py`.

**Note on raw output**: a match against a large candidate-mass list, at a
loose tolerance, is expected to include a lot of coincidental overlap with
background/isobaric ions — a raw hit alone is not a confirmed identification.
Narrowing tolerance, restricting MS level/relative or absolute intensity, the
minimum-consecutive-scans filter, and the RT-bound acetyl co-occurrence check
are the filters currently available to turn this into a meaningful shortlist;
isotope-pattern filters are not implemented yet.

**Acetyl co-occurrence is RT-bound** (`--acetyl-rt-window`, default **2.0**
minutes): the acetyl analog only counts as co-occurring if it's found within
that many minutes of the fluoroacetyl hit's own RT, not just anywhere in the
file. Structurally near-identical compounds (same skeleton, different acyl
group) should co-elute or nearly so, so a same-file-anywhere match isn't
real evidence on its own. `filter_acetyl_cooccurring` pulls out just that
subset; `run_match.py` (with `--check-acetyl-cooccurrence`) writes it
alongside the full table as `*_acetyl_cooccurring.parquet`/`.csv` (for both
the raw and, if `--collapse-to-features` is also set, the feature table);
the GUI shows the same subset in its own expander/download.

**Minimum signal filters** (`--min-intensity`, default **50,000** raw
instrument units; `--min-consecutive-scans`, default **3**): a hit only
counts if its peak intensity clears the absolute floor *and* it's part of a
run of at least that many scans in a row for the same file+product (RT within
`--max-rt-gap`, default 0.1 min, of each other — see `collapse_to_features`
for why RT rather than raw scan index defines "in a row"). Both cut out
transient, single-scan noise and weak coincidental overlaps; set either to
0/1 to disable.

**Note on duplicate products**: different parent compounds (e.g. a salt form
vs. the free base) can react to an identical product structure. The join back
to the library uses the library's own row index (not `product_inchikey`,
which is not guaranteed unique) so both candidates are surfaced rather than
one being silently dropped or the join exploding.

**Note on raw hit counts**: a raw hit row is one (file, MS1 scan, library
target) match -- a single real chromatographic peak typically contributes one
row per scan it spans, so the raw row count is not a compound count and is
expected to be much larger than the number of distinct products/parents
actually detected. `summarize_candidate_table`/`format_summary` (both called
automatically by `run_match.py` and the GUI) report that breakdown, and
`collapse_to_features` merges same-file/same-product hits whose retention
times are within a tolerance (`--max-rt-gap`, default 0.1 min) into one row
per elution event -- available via `run_match.py --collapse-to-features` or
the GUI's matching checkbox.

## Folders
- `data/` — module-local scratch input (gitignored); the suspect library it
  reads lives in `insilico_library/data/`, not here.
- `output/` — `candidate_table.parquet` / `.csv` land here (gitignored;
  auto-created at runtime); `output/figures/` holds the exported PNGs.

## Status
`matcher.py`, `run_match.py`, `gui.py`, and `plotting.py`: built and tested
against real mzML data, including at full library scale. **Not yet built**:
isotope-pattern confirmation filters.
