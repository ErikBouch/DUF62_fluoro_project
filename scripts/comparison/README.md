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
mzML files to match in one run, and caps the on-screen table (largest result
sets can't be streamed to the browser in full) while still writing the
complete result to `output/` when it's too large to offer as an in-browser
download.

**Note on raw output**: a match against a large candidate-mass list, at a
loose tolerance, is expected to include a lot of coincidental overlap with
background/isobaric ions — a raw hit alone is not a confirmed identification.
Narrowing tolerance, restricting MS level/relative intensity, and the acetyl
co-occurrence check are the filters currently available to turn this into a
meaningful shortlist; RT-window and isotope-pattern filters are not
implemented yet.

**Note on duplicate products**: different parent compounds (e.g. a salt form
vs. the free base) can react to an identical product structure. The join back
to the library uses the library's own row index (not `product_inchikey`,
which is not guaranteed unique) so both candidates are surfaced rather than
one being silently dropped or the join exploding.

## Folders
- `data/` — module-local scratch input (gitignored); the suspect library it
  reads lives in `insilico_library/data/`, not here.
- `output/` — `candidate_table.parquet` / `.csv` land here (gitignored;
  auto-created at runtime).

## Status
`matcher.py`, `run_match.py`, and `gui.py`: built and tested against real
mzML data, including at full library scale. **Not yet built**: RT-window and
isotope-pattern confirmation filters.
