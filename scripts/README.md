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

`main.py` uses `st.navigation` (a sidebar page list) to show one module at a
time — one running app, not the old one-window-per-step/subprocess model.
`st.navigation` only runs the current page's code, unlike `st.tabs` (tried
first), which re-executed every tab's code on every single rerun no matter
which tab was visible — a real cost once any one page has heavy content.
The tradeoff: a page's widgets lose their values when its page is unmounted.
Every module works around that with `common.ui.restore`/`persist`, which
mirror a widget's value into a plain session_state entry that navigation
does *not* clear — so filters and selections still survive switching pages.
That same store backs a "save/load a settings preset" control (sidebar):
the whole app's current settings can be saved to and loaded from a named
local file under `configs/` (gitignored).

**`setup/` is the landing page** (first in the nav): explains what each other
page does, and holds the one shared mzML file selection + library file path
every other page seeds its own picker's default from
(`common.ui.SHARED_MZML_KEY`/`SHARED_LIBRARY_PATH_KEY`) -- pick files/a
library once there, and mzML Scan Detector/MS Matching/In-silico Library all
start from the same place, while still letting each page diverge from it
independently.

```
scripts/
├── main.py                 # Streamlit entry: st.navigation, calls each module's gui.render()
├── common/
│   └── ui.py                #   shared GUI helpers (file discovery, page header, settings
│   │                              persistence/presets) — no science logic
├── setup/                   # landing page: module map + shared mzML/library selection
├── mzml_tools/              # open/read/query mzML files
│   ├── scan_detector.py     #   logic: find scans with a target m/z, file overview; export CSV
│   ├── gui.py                #   Streamlit page for the above
│   ├── data/                 #   input mzML (gitignored)
│   └── output/               #   CSV exports (gitignored, auto-created)
├── insilico_library/        # turn a user-supplied library (column-mapped) into the suspect library (CLI + GUI)
├── comparison/               # match the suspect library against one or more mzML files (CLI + GUI)
└── explorer/                 # gallery view of a match's compound structures (sort, paginate, isomer drill-down)
```

Each module's `data/`/`output/` are gitignored; `output/` is auto-created at
runtime. **mzML files go in `<repo root>/data/mzml/`** (also gitignored) --
a real, repo-relative convention any clone can use, not a path that only
makes sense on one specific machine. `common/ui.py` looks there for files to
list in the GUI's file picker, and falls back to manual path entry if it's
empty or missing (e.g. a fresh clone before you've added your own data, or
before running anything at all).

## Running the GUI

```bash
streamlit run scripts/main.py
```
(run from the repo root, so the dark theme in `.streamlit/config.toml` is
picked up — Streamlit reads that file relative to the current working
directory, not the script's location.)

## Running a module's logic directly (CLI / no GUI)

```bash
python mzml_tools/scan_detector.py <file.mzML> --overview
python mzml_tools/scan_detector.py <file.mzML> --mz 150.0 --tol 25 --unit ppm --min-rel-intensity 0.02 --ms-level 2

python insilico_library/db_loader.py --dnp <dnp.tsv> --lotus <lotus.sdf> --hmdb <hmdb.xml> -o data/unified_structures.parquet
python insilico_library/build_suspect_library.py --input data/unified_structures.parquet --limit 200   # quick test run first

python comparison/run_match.py --limit 2000   # quick test run first
```
See each module's own README for details.

## Dependencies
See the repo-root `environment.yml` (recommended: `conda env create -f environment.yml`)
or `requirements.txt` (pip). Either way: `pyopenms`, `numpy`, `pandas`, `rdkit`,
`streamlit`, `plotly`. A pip `.venv` at the repo root already has these
installed (Python 3.14) for quick local testing.

_Status: all four modules (`mzml_tools`, `insilico_library`, `comparison`,
`explorer`) have both a tested logic file and a working `gui.py` page — see
each module's own README for details._
