# Changelog

Notable changes to this repository, newest first. Dated by when the change
was committed (not necessarily the same day it's pushed).

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
