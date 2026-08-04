"""
setup/gui.py — Streamlit page: a landing page that orients a new user and
holds the shared mzML file selection, library file path, and already-computed
result paths that every other page's own picker/loader seeds its default
from (see `common.ui.pick_mzml_files`'s `default` param and `restore`, used
the same way for the result paths below). Picking files/a library/a result
path here doesn't lock downstream pages to them -- each page keeps its own
independent, still-editable value -- it just saves re-picking the common
case, and lets a page auto-populate from disk instead of requiring an
explicit "load" click every session.

GUI only: no science logic of its own.
"""
from __future__ import annotations

import importlib
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import (  # noqa: E402
    PIPELINE_ORDER, SHARED_CANDIDATE_TABLE_KEY, SHARED_LIBRARY_PATH_KEY, SHARED_MZML_KEY,
    SHARED_SUSPECT_LIBRARY_KEY, STAGE_GLYPH, STAGE_LABELS, STATUS_COLOR_VAR,
    mount_key, page_header, persist, pick_mzml_files, resolved_shared_mzml_files, restore,
)

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_SUSPECT_LIBRARY_PATH = os.path.join(_SCRIPTS_DIR, "insilico_library", "output", "suspect_library.parquet")
_DEFAULT_CANDIDATE_TABLE_PATH = os.path.join(_SCRIPTS_DIR, "comparison", "output", "candidate_table.parquet")

_MODULES = [
    ("mzML Scan Detector", "Explore one mzML file directly: search for a target m/z, check a "
     "file's overview (MS levels, RT range, polarity), and manage a list of candidate diagnostic "
     "fragment-ion targets for MS Matching's MS2 filter."),
    ("In-silico Library", "Point at a library of candidate compounds (any table with a structure "
     "column), map its columns, and build the acetyl/fluoroacetyl suspect library used for matching."),
    ("MS Matching", "Match the suspect library against one or more mzML files -- the main "
     "pipeline: raw hits, feature collapsing, acetyl co-occurrence, and the MS2 confidence filter."),
    ("Molecule Explorer", "Browse the compound structures surviving a MS Matching run as a "
     "sortable, paginated gallery."),
]

# The other 4 modules' own pure pipeline-stage status functions, keyed by the
# stage they own. Looked up lazily (module name + attribute name, not a
# direct import) because those modules are being migrated onto this same
# visual system in parallel, right now, in separate files -- see
# `_stage_status_and_text()`.
_EXTERNAL_STATUS_FUNCS = {
    "lib_normalize": ("insilico_library.gui", "normalize_status"),
    "lib_build_suspects": ("insilico_library.gui", "build_status"),
    "calibrate_match": ("comparison.gui", "calibrate_status"),
    "execute_match": ("comparison.gui", "execute_match_status"),
    "review_output": ("explorer.gui", "review_output_status"),
}


def _render_module_map():
    st.subheader("What each page does")
    for name, desc in _MODULES:
        st.markdown(f"**{name}** — {desc}")


def _render_mzml_picker():
    st.subheader("mzML files")
    st.caption(
        "Picked here as the default for every other page -- each page still has its own "
        "independent selection, so choosing a different file on e.g. the Scan Detector page "
        "later won't change what MS Matching uses."
    )
    pick_mzml_files(key=SHARED_MZML_KEY)


def _library_file_status(path: str) -> str:
    """
    Single source of truth for a library path's status -- 'todo' if no path
    is set at all, 'failed' if a path is set but no file exists there, 'done'
    if it points at a real file. Shared by `_render_library_picker`'s inline
    warning/success and the pure `link_library_status()` pipeline check below,
    so the "does this path exist" rule is defined exactly once.
    """
    if not path:
        return "todo"
    return "done" if os.path.isfile(path) else "failed"


def _render_library_picker():
    st.subheader("Library")
    st.caption(
        "Any table (CSV or Parquet) with at least one column holding each compound's structure "
        "as **InChI or SMILES**. Everything else this pipeline needs -- formula, exact mass, "
        "InChIKey, and whether a compound has a primary amine (what actually gets acylated) -- "
        "is computed for you from that structure; you don't need to provide or map those columns "
        "even if your table already has them. A name and an organism/source column are optional. "
        "Column mapping itself happens on the In-silico Library page, once a path is set here."
    )
    restore(SHARED_LIBRARY_PATH_KEY, "")
    st.text_input("Path to your library file (.csv or .parquet)", key=SHARED_LIBRARY_PATH_KEY)
    persist(SHARED_LIBRARY_PATH_KEY)

    library_path = st.session_state.get(SHARED_LIBRARY_PATH_KEY, "")
    status = _library_file_status(library_path)
    if status == "failed":
        st.warning(f"No file found at `{library_path}`.")
    elif status == "done":
        st.success(f"Found `{library_path}` — map its columns on the In-silico Library page.")


def _render_result_path(key: str, default_path: str, label: str, help_text: str, built_verb: str):
    """
    One already-computed-result path: defaults to the module's standard
    output location when a file is already there (so a fresh clone -- no
    file yet -- doesn't show a confusing path to nothing), but is fully
    user-editable, e.g. to point at a result saved somewhere else.
    """
    restore(key, default_path if os.path.isfile(default_path) else "")
    st.text_input(label, key=key, help=help_text)
    persist(key)

    path = st.session_state.get(key, "")
    if not path:
        st.caption(f"Not set -- {built_verb} not built yet, or leave blank until it is.")
        return
    if not os.path.isfile(path):
        st.warning(f"No file found at `{path}`.")
        return
    import datetime

    when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    st.success(f"Found `{path}` (saved {when}) -- opening its page will load this automatically.")


def _render_results():
    st.subheader("Results (optional)")
    st.caption(
        "Already have a suspect library or a match result from a previous run? Point at them here "
        "and the relevant page will load them automatically when you open it, instead of you having "
        "to click a \"load\" button there every session. Defaults to the standard location when a "
        "file is already there; change it to load a result saved somewhere else, or clear it to "
        "start fresh."
    )
    _render_result_path(
        SHARED_SUSPECT_LIBRARY_KEY, _DEFAULT_SUSPECT_LIBRARY_PATH,
        "Suspect library path (.parquet)", "Read automatically by In-silico Library and MS Matching.",
        "suspect library",
    )
    _render_result_path(
        SHARED_CANDIDATE_TABLE_KEY, _DEFAULT_CANDIDATE_TABLE_PATH,
        "MS Matching result path (candidate_table.parquet)",
        "Read automatically by MS Matching (and, once loaded there, Molecule Explorer).",
        "MS Matching result",
    )


def acquire_data_status() -> str:
    """'done' if resolved_shared_mzml_files() is non-empty, else 'todo'. Pure,
    side-effect-free -- read by main.py's pipeline stepper on every rerun,
    regardless of which page is currently showing."""
    return "done" if resolved_shared_mzml_files() else "todo"


def link_library_status() -> str:
    """'done' if the shared library path is set and os.path.isfile() is True,
    'failed' if a path is set but the file doesn't exist, else 'todo'. Pure,
    side-effect-free -- read by main.py's pipeline stepper on every rerun,
    regardless of which page is currently showing."""
    return _library_file_status(st.session_state.get(SHARED_LIBRARY_PATH_KEY, ""))


def _stage_status_and_text() -> tuple[dict[str, str], dict[str, str]]:
    """
    Live status (+ any display-text override) for all 7 pipeline stages, for
    the STATUS sheet's ledger. `acquire_data`/`link_library` are this
    module's own; the other 5 belong to the other 4 modules, which are being
    migrated onto this same visual system in parallel right now -- looked up
    lazily and wrapped in try/except so a status function that doesn't exist
    yet (AttributeError) or a module that doesn't import cleanly yet
    (ImportError) shows as a "PENDING MIGRATION" placeholder row here instead
    of crashing this page. Left in as permanent belt-and-suspenders rather
    than torn out once every module has landed: at that point the try simply
    always succeeds, so this stays harmless instead of turning into dead code
    that needs removing.
    """
    status = {"acquire_data": acquire_data_status(), "link_library": link_library_status()}
    text_overrides: dict[str, str] = {}
    for stage_key, (module_name, func_name) in _EXTERNAL_STATUS_FUNCS.items():
        try:
            module = importlib.import_module(module_name)
            status[stage_key] = getattr(module, func_name)()
        except (ImportError, AttributeError):
            status[stage_key] = "todo"
            text_overrides[stage_key] = "PENDING MIGRATION"
    return status, text_overrides


def _render_status():
    st.subheader("Status")
    status, text_overrides = _stage_status_and_text()
    rows = []
    for stage_key in PIPELINE_ORDER:
        stage_status = status[stage_key]
        color = STATUS_COLOR_VAR[stage_status]
        glyph = STAGE_GLYPH[stage_status]
        status_text = text_overrides.get(stage_key, stage_status.upper())
        rows.append(
            '<div class="status-row">'
            f'<span class="status-glyph" style="color:{color}">{glyph}</span>'
            f'<span class="status-label">{STAGE_LABELS[stage_key]}</span>'
            f'<span class="status-text" style="color:{color}">{status_text}</span>'
            "</div>"
        )
    st.html("\n".join(rows))


def render():
    page_header(
        "Setup",
        "Start here: pick the mzML files and library you're working with, and see what each "
        "page does. Every other page starts from the same selection by default.",
    )
    _render_module_map()

    with st.container(key=mount_key("sheet_setup_files", "sheet_setup_files_entered")):
        _render_mzml_picker()

    with st.container(key=mount_key("sheet_setup_library", "sheet_setup_library_entered")):
        _render_library_picker()

    with st.container(key=mount_key("sheet_setup_results", "sheet_setup_results_entered")):
        _render_results()

    with st.container(key=mount_key("sheet_setup_status", "sheet_setup_status_entered")):
        _render_status()
