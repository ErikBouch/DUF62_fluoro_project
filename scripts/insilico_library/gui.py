"""
insilico_library/gui.py — Streamlit page for building/inspecting the suspect
library.

GUI only: all science logic lives in db_loader.py / acylation.py /
build_suspect_library.py so it stays testable and usable from the CLI without
Streamlit installed.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import page_header  # noqa: E402

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_UNIFIED_PATH = os.path.join(_DATA_DIR, "unified_structures.parquet")
_SUSPECT_MONO_PATH = os.path.join(_DATA_DIR, "suspect_library.parquet")
_SUSPECT_MULTI_PATH = os.path.join(_DATA_DIR, "suspect_library_multidegree.parquet")


@st.cache_data(show_spinner=False)
def _cached_parquet(path: str, _mtime: float):
    import pandas as pd

    return pd.read_parquet(path)


def render():
    page_header(
        "In-silico Library",
        "Merged natural-product structure table, and the acetyl/fluoroacetyl "
        "suspect library built from it.",
    )

    if not os.path.isfile(_UNIFIED_PATH):
        st.warning(
            "No merged structure table found. Build it first with "
            "`insilico_library/db_loader.py` (see that module's README)."
        )
        return

    unified = _cached_parquet(_UNIFIED_PATH, os.path.getmtime(_UNIFIED_PATH))
    n_amine = int(unified["has_primary_amine"].sum())

    st.subheader("Merged structure table")
    c1, c2, c3 = st.columns(3)
    c1.metric("Unique structures", len(unified))
    c2.metric("With a primary amine", n_amine)
    c3.metric("Sources", unified["source_db"].str.split(",").explode().nunique())

    st.divider()
    st.subheader("Suspect library (acylation products)")

    if os.path.isfile(_SUSPECT_MONO_PATH):
        mono = _cached_parquet(_SUSPECT_MONO_PATH, os.path.getmtime(_SUSPECT_MONO_PATH))
        c1, c2, c3 = st.columns(3)
        c1.metric("Product rows", len(mono))
        c2.metric("Fluoroacetyl", int((mono["reaction"] == "fluoroacetyl").sum()))
        c3.metric("Acetyl", int((mono["reaction"] == "acetyl").sum()))
        st.dataframe(mono.head(50), width="stretch")
    else:
        st.info("Suspect library not built yet.")

    if st.button("(Re)build suspect library from the merged table", type="primary"):
        from insilico_library.acylation import REACTIONS, acylate  # noqa: F401  (loaded lazily, heavy)
        from insilico_library.build_suspect_library import build_library

        primary_amine_df = unified[unified["has_primary_amine"]].reset_index(drop=True)
        status = st.empty()
        progress_bar = st.progress(0.0)
        status.text(f"Processing {len(primary_amine_df)} primary-amine compounds...")
        mono_rows, multi_rows, n_processed, n_multisite, n_errors = build_library(
            primary_amine_df, progress_every=1000, progress_callback=status.text,
            progress_fraction_callback=progress_bar.progress,
        )
        status.empty()
        progress_bar.empty()

        import pandas as pd

        mono_df = pd.DataFrame(mono_rows)
        multi_df = pd.DataFrame(multi_rows)
        mono_df.to_parquet(_SUSPECT_MONO_PATH, index=False)
        multi_df.to_parquet(_SUSPECT_MULTI_PATH, index=False)

        st.success(
            f"Done: {n_processed} compounds processed, {len(mono_df)} product rows "
            f"({n_multisite} with >1 reactive site), {n_errors} errors."
        )
        st.cache_data.clear()
        st.rerun()
