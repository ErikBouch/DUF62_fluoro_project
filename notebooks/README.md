# notebooks

Jupyter notebooks for exploration, prototyping, and figure generation.
Reusable logic that graduates out of a notebook should be moved into
[`../scripts/`](../scripts/) so it can be imported and version-tracked cleanly.

- **`build_unified_library.ipynb`** — merges DNP/LOTUS/HMDB into
  `scripts/insilico_library/data/unified_structures.parquet` (+ `.csv`) via
  `scripts/insilico_library/db_loader.py`'s loaders. Documents the merge
  methodology with its saved cell outputs; the three source databases
  themselves are large and live outside the repo, so re-running it requires
  your own local copies (see the paths at the top of the notebook) — reading
  it doesn't.

Note: notebook checkpoints (`.ipynb_checkpoints/`) are gitignored.
