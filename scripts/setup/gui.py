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

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import (  # noqa: E402
    SHARED_CANDIDATE_TABLE_KEY, SHARED_LIBRARY_PATH_KEY, SHARED_MZML_KEY, SHARED_SUSPECT_LIBRARY_KEY,
    page_header, persist, pick_mzml_files, resolved_shared_mzml_files, restore,
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
    if library_path and not os.path.isfile(library_path):
        st.warning(f"No file found at `{library_path}`.")
    elif library_path:
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


def _render_status():
    # `restore()` first on both keys, same as `_render_result_path()` above
    # -- correct today only because that function happens to run earlier in
    # `render()`'s fixed call order and restores these same keys itself;
    # reading them directly here would silently come back empty if this
    # function were ever called before that one (e.g. a future reordering),
    # same class of bug as the shared mzML/library-path keys elsewhere.
    st.subheader("Status")
    n_files = len(resolved_shared_mzml_files())
    c1, c2, c3 = st.columns(3)
    c1.metric("mzML files selected", n_files)

    restore(SHARED_SUSPECT_LIBRARY_KEY, _DEFAULT_SUSPECT_LIBRARY_PATH if os.path.isfile(_DEFAULT_SUSPECT_LIBRARY_PATH) else "")
    library_path = st.session_state.get(SHARED_SUSPECT_LIBRARY_KEY, "")
    if library_path and os.path.isfile(library_path):
        c2.metric("Suspect library", "ready to auto-load")
    else:
        c2.metric("Suspect library", "not set")

    restore(SHARED_CANDIDATE_TABLE_KEY, _DEFAULT_CANDIDATE_TABLE_PATH if os.path.isfile(_DEFAULT_CANDIDATE_TABLE_PATH) else "")
    candidate_path = st.session_state.get(SHARED_CANDIDATE_TABLE_KEY, "")
    if candidate_path and os.path.isfile(candidate_path):
        c3.metric("MS Matching result", "ready to auto-load")
    else:
        c3.metric("MS Matching result", "not set")


def render():
    page_header(
        "Setup",
        "Start here: pick the mzML files and library you're working with, and see what each "
        "page does. Every other page starts from the same selection by default.",
    )
    _render_module_map()
    st.divider()
    _render_mzml_picker()
    st.divider()
    _render_library_picker()
    st.divider()
    _render_results()
    st.divider()
    _render_status()
