# Changelog

Notable changes to this repository, newest first. Dated by when the change
was committed (not necessarily the same day it's pushed).

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
