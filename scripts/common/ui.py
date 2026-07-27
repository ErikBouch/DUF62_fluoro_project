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


def pick_mzml_files(root: str = DEFAULT_HRMS_DIR, key: str = "mzml_multiselect") -> list[str]:
    """
    Multi-file picker: a multiselect over discovered local mzML files, plus an
    optional text area for additional custom paths (one per line). Starts with
    nothing selected -- the caller always has to choose explicitly.

    Returns a list of full paths (discovered + custom, order not guaranteed).
    """
    import streamlit as st

    discovered = find_mzml_files(root)
    labels = [label for label, _ in discovered]
    by_label = dict(discovered)

    chosen_labels = st.multiselect("mzML files", labels, default=[], key=key)
    with st.expander("Add custom file paths (one per line)"):
        custom_text = st.text_area("Custom paths", value="", key=f"{key}_custom", label_visibility="collapsed")
    custom_paths = [line.strip() for line in custom_text.splitlines() if line.strip()]

    return [by_label[label] for label in chosen_labels] + custom_paths


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
