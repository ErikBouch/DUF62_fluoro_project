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
from comparison.matcher import match_library_to_file
matches = match_library_to_file("file.mzML", targets, tolerance_ppm=25.0, ms_level=1,
                                  min_relative_intensity=0.01)
# targets: list of (label, target_mz) -- can be tens of thousands of entries
```

## `run_match.py`

Loads the suspect library, discovers local mzML files (same mechanism as
`mzml_tools`), matches the appropriate adduct column (positive or negative,
based on each file's dominant polarity) against every file, and joins the hits
back to the full suspect-library row (parent/product formula, masses, reaction
type) into one candidate table.

```bash
python run_match.py --limit 2000     # quick test run first
python run_match.py                   # full run
```

**Note on raw output**: a match against a large candidate-mass list, at a
loose tolerance, is expected to include a lot of coincidental overlap with
background/isobaric ions — a raw hit alone is not a confirmed identification.
The additional filters mentioned in the GUI placeholder (RT window,
fluoro/parent/acetyl co-occurrence, isotope pattern) are what turn this into a
meaningful shortlist; they are not implemented yet.

## Folders
- `data/` — module-local scratch input (gitignored); the suspect library it
  reads lives in `insilico_library/data/`, not here.
- `output/` — `candidate_table.parquet` / `.csv` land here (gitignored;
  auto-created at runtime).

## Status
`matcher.py` + `run_match.py`: built and tested against real mzML data.
**Not yet built**: the additional confirmation filters, and this module's own
`gui.py` page (currently a placeholder).
