"""
common/ui.py — small shared helpers for the Streamlit GUI (not science logic).

Data lives outside the git repo, in the private parent project folder
(`DUF_62/data/...`), so this module locates it defensively: if a colleague
clones just the repo without that private data, file discovery simply comes
back empty and the GUI falls back to manual path entry.
"""
from __future__ import annotations

import os

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../DUF62_fluoro_project/scripts
REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)  # .../DUF62_fluoro_project
PROJECT_ROOT = os.path.dirname(REPO_ROOT)  # .../DUF_62 (private data hub, not the repo)
DEFAULT_HRMS_DIR = os.path.join(PROJECT_ROOT, "data", "HRMS")


def find_mzml_files(root: str = DEFAULT_HRMS_DIR) -> list[tuple[str, str]]:
    """
    Discover .mzML files under `root`. Returns a sorted list of
    (label, full_path) tuples; label is the path relative to `root`, using
    forward slashes, e.g. "some_subfolder/file.mzML".
    Returns [] if `root` doesn't exist (e.g. a fresh clone without private data).
    """
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.lower().endswith(".mzml"):
                full = os.path.join(dirpath, fname)
                label = os.path.relpath(full, root).replace(os.sep, "/")
                found.append((label, full))
    return sorted(found, key=lambda pair: pair[0])


def page_header(title: str, subtitle: str | None = None):
    """Consistent page title + optional subtitle, used at the top of each module page."""
    import streamlit as st

    st.title(title)
    if subtitle:
        st.caption(subtitle)


def coming_soon(title: str, description: str):
    """Placeholder page for a module that isn't built yet."""
    import streamlit as st

    page_header(title, "Coming soon")
    st.info(description)
