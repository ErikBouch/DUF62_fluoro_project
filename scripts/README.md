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

**Navigation is a hand-rolled top nav bar, not `st.navigation`** (switched in
the visual redesign; `st.navigation`'s own sidebar page list is gone).
`main.py` holds `st.session_state["page"]` and dispatches to exactly one
module's `render()` via a plain if/elif-equivalent lookup (`PAGE_RENDERERS`)
— the same real property `st.navigation` was originally chosen for over
`st.tabs` (only the active page's code runs; the other four never execute
that rerun) still holds, it's just achieved by a lookup table instead of a
Streamlit-native API. The switch was needed because the new top nav +
pipeline stepper (below) needed full layout control `st.navigation`'s fixed
sidebar-list UI couldn't offer, not because the old mechanism was broken.

The tradeoff `st.navigation` had — a page's widgets lose their values the
moment its page stops being the active one — still applies, just for a more
general reason: **any** Streamlit script drops a widget's session_state the
moment a rerun doesn't re-instantiate it, regardless of *why* that page
didn't render (page unmounted by `st.navigation`, or simply a different
`if` branch taken this run, as here). Every module still works around this
with `common.ui.restore`/`persist`, which mirror a widget's value into a
plain session_state entry that survives regardless — so filters and
selections still survive switching pages. That same store backs a
"save/load a settings preset" control (sidebar, still used for this one
utility, not for page switching anymore): the whole app's current settings
can be saved to and loaded from a named local file under `configs/`
(gitignored).

**A 7-stage pipeline stepper** sits under the top nav on every page, showing
at a glance which of the seven pipeline stages (acquire mzML data, link a
library, normalize it, build the suspect library, calibrate MS Matching,
run the match, review the output) are done, still to-do, or failed — each
stage is a real, always-clickable button that jumps straight to the page
that stage lives on. Its colors/glyph (yellow circle = to-do, green check =
done, red cross = failed) come from each module's own small, pure status
function (e.g. `setup.gui.acquire_data_status`, `comparison.gui.calibrate_status`)
— `main.py` only assembles the 7-entry dict from those, it never computes
pipeline status itself. The stepper's own render is deliberately *deferred*
until after the current page's `render()` has already run (filled into a
`st.container()` reserved before dispatch) — computing and rendering it
*before* dispatch, as an earlier version briefly did, only self-corrected
because every action handler happened to call `st.rerun()` afterward, which
is a convention, not a guarantee; deferring the render removes the
dependency on that convention entirely.

**Every page (except Setup and Molecule Explorer) is built from bordered
"sheets"** — LOAD / PARAMETERS / RUN / ANALYZE, in that order, each a plain
`st.container(key="sheet_<name>")` — a shared CSS layer in `common/ui.py`
turns that key into a bordered panel with a "SHEET N — TITLE" tab, purely
via a static `SHEET_TITLES` registry and generated CSS, no per-page styling
code needed. A rarely-touched settings group (e.g. an "Advanced" section)
is a native `st.expander(..., key="flap_amber_...")` or
`key="flap_ink_..."` — restyled by that same CSS layer into an amber
("optional, safe to skip") or neutral-ink ("a primary feature, just
collapsed") flap, with zero change to the expander's own contents. A
4-mode color palette (blue/green/white/black, top-left "INK" selector) and a
one-time-per-session boot animation round out the shared visual system —
all in `common/ui.py`, ported from a separate Streamlit design-exploration
round (13 mockups, narrowed and refined twice) that lives outside this
repository.

**A real gotcha worth knowing before touching `common/ui.py`'s `STATIC_CSS`
or any of the `build_*_css` functions**: `st.html()` sanitizes its *entire*
input as HTML before any of it is treated as inert CSS text — a single
tag-shaped substring anywhere in that multi-thousand-character string, even
inside what looks to a human like an ordinary CSS comment, silently drops
the whole combined stylesheet with no exception and nothing in any log.
This happened for real during the redesign (a comment describing what
`st.expander` renders internally, phrased with literal angle brackets) and
took real effort to isolate, since every other symptom looked like a
routine widget-rendering issue rather than a poisoned style string. Never
write a literal `<tag>`-shaped sequence anywhere in that combined string,
comments included.

**`setup/` is the landing page** (first in the nav): explains what each other
page does, and holds the one shared mzML file selection + library file path
every other page seeds its own picker's default from
(`common.ui.SHARED_MZML_KEY`/`SHARED_LIBRARY_PATH_KEY`) -- pick files/a
library once there, and mzML Scan Detector/MS Matching/In-silico Library all
start from the same place, while still letting each page diverge from it
independently.

```
scripts/
├── main.py                 # Streamlit entry: top nav + pipeline stepper, dispatches to one module's gui.render()
├── common/
│   └── ui.py                #   shared GUI helpers (file discovery, page header, settings
│   │                              persistence/presets, palette/boot/sheet/stepper CSS) — no science logic
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
