# scripts

Analysis code for the DUF62 fluoro project (finding naturally fluoroacetylated
plant metabolites by matching an in-silico suspect library to MS data).

## Architecture

**`main.py` is a Streamlit GUI** — the single entry point, handling only
navigation/layout. Each downstream module lives in its own folder with:
- a **logic file** (e.g. `scan_detector.py`) — plain Python, no Streamlit
  import, usable from the CLI or tests without a GUI running;
- a **`gui.py`** — the Streamlit page for that module (imports the logic file,
  renders widgets, calls back into it). Keeping GUI code out of the logic file
  is deliberate — the old Microfractionation GUIs mixed the two, which made the
  biggest ones (3000+ lines) hard to work with;
- local `data/` and `output/` subfolders (gitignored).

`main.py` imports each module's `gui.render()` and shows the selected one in
the main area behind a sidebar radio — one running app, not the old
one-window-per-step/subprocess model.

```
scripts/
├── main.py                 # Streamlit entry: sidebar nav, calls each module's gui.render()
├── common/
│   └── ui.py                #   shared GUI helpers (file discovery, page header) — no science logic
├── mzml_tools/              # open/read/query mzML files
│   ├── scan_detector.py     #   logic: find scans with a target m/z, file overview; export CSV
│   ├── gui.py                #   Streamlit page for the above
│   ├── data/                 #   input mzML (gitignored)
│   └── output/               #   CSV exports (gitignored, auto-created)
├── insilico_library/        # merge NP databases + acylation logic; build/inspect the suspect library (CLI + GUI)
└── comparison/               # match the suspect library against one or more mzML files (CLI + GUI)
```

Each module's `data/`/`output/` are gitignored; `output/` is auto-created at
runtime. The real project mzML data lives outside the repo, in the parent
`DUF_62/data/HRMS/` — `common/ui.py` looks there for files to list in the GUI's
file picker (falls back to manual path entry if that folder isn't present,
e.g. on a colleague's clone without the private data).

## Running the GUI

```bash
streamlit run scripts/main.py
```
(run from the repo root, so the dark theme in `.streamlit/config.toml` is
picked up — Streamlit reads that file relative to the current working
directory, not the script's location.)

## Running a module's logic directly (CLI / no GUI)

```bash
python scripts/mzml_tools/scan_detector.py <file.mzML> --overview
python scripts/mzml_tools/scan_detector.py <file.mzML> --mz 150.0 --tol 25 --unit ppm --min-rel-intensity 0.02 --ms-level 2

python scripts/insilico_library/db_loader.py --dnp <dnp.tsv> --lotus <lotus.sdf> --hmdb <hmdb.xml> -o data/unified_structures.parquet
python scripts/insilico_library/build_suspect_library.py --limit 200   # quick test run first

python scripts/comparison/run_match.py --limit 2000   # quick test run first
```
See each module's own README for details.

## Dependencies
See the repo-root `environment.yml` (recommended: `conda env create -f environment.yml`)
or `requirements.txt` (pip). Either way: `pyopenms`, `numpy`, `pandas`, `rdkit`,
`streamlit`, `plotly`. A pip `.venv` at the repo root already has these
installed (Python 3.14) for quick local testing.

_Status: all three modules (`mzml_tools`, `insilico_library`, `comparison`)
have both a tested logic file and a working `gui.py` page — see each module's
own README for details._
