"""
comparison/gui.py — Streamlit page for matching the suspect library against
mzML data.

GUI only: all science logic lives in matcher.py so it stays testable and
usable from the CLI without Streamlit installed.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import page_header, pick_mzml_files  # noqa: E402
from comparison.matcher import run_match_pipeline  # noqa: E402

_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "insilico_library", "data", "suspect_library.parquet",
)
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Streamlit's websocket messages (including download_button payloads) are
# capped at 200 MB; stay well under that so the button itself doesn't crash
# the page on large result sets. Above this, the full table is written to
# disk instead and the path is shown rather than streamed to the browser.
_MAX_DOWNLOAD_BYTES = 80_000_000


@st.cache_data(show_spinner=False)
def _cached_library(path: str, _mtime: float):
    import pandas as pd

    return pd.read_parquet(path)


def render():
    page_header(
        "MS Matching",
        "Match the in-silico suspect library against one or more mzML files.",
    )

    if not os.path.isfile(_LIBRARY_PATH):
        st.warning(
            "No suspect library found. Build it first with "
            "`insilico_library/build_suspect_library.py`."
        )
        return

    mtime = os.path.getmtime(_LIBRARY_PATH)
    library = _cached_library(_LIBRARY_PATH, mtime)
    n_fluoro = (library["reaction"] == "fluoroacetyl").sum()
    n_acetyl = (library["reaction"] == "acetyl").sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Library rows", len(library))
    c2.metric("Fluoroacetyl products", n_fluoro)
    c3.metric("Acetyl products", n_acetyl)

    st.divider()
    st.subheader("Files")
    file_paths = pick_mzml_files(key="comparison_files")

    st.divider()
    st.subheader("Filters")
    st.caption("Tolerance is required; everything else is optional.")

    col1, col2 = st.columns(2)
    tolerance = col1.number_input("Tolerance", value=0.002, min_value=0.0, format="%.4f", key="cmp_tolerance")
    unit = col2.selectbox("Unit", ["Da", "ppm"], key="cmp_unit")

    with st.expander("Optional filters"):
        col3, col4 = st.columns(2)
        ms_level_choice = col3.selectbox("MS level", ["1", "2", "All"], index=0, key="cmp_ms_level")
        ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
        min_rel_pct = col4.slider("Min. relative intensity (%)", 0, 100, 0, key="cmp_min_rel")
        min_rel = min_rel_pct / 100.0

        check_acetyl = st.checkbox(
            "Require checking the acetyl analog too (co-occurrence)",
            value=False, key="cmp_check_acetyl",
        )
        acetyl_tolerance, acetyl_unit = 5.0, "ppm"
        if check_acetyl:
            col5, col6 = st.columns(2)
            acetyl_tolerance = col5.number_input("Acetyl tolerance", value=5.0, min_value=0.0, key="cmp_acetyl_tolerance")
            acetyl_unit = col6.selectbox("Acetyl unit", ["ppm", "Da"], key="cmp_acetyl_unit")

    st.divider()

    if not file_paths:
        st.info("Pick at least one mzML file to run a match.")
        return

    if st.button("Run match", type="primary"):
        status = st.empty()
        with st.spinner("Matching..."):
            candidate_table = run_match_pipeline(
                library, file_paths,
                fluoroacetyl_tolerance=tolerance, fluoroacetyl_unit=unit,
                ms_level=ms_level, min_relative_intensity=min_rel,
                check_acetyl_cooccurrence=check_acetyl,
                acetyl_tolerance=acetyl_tolerance, acetyl_unit=acetyl_unit,
                progress_callback=status.text,
            )
        status.empty()
        st.session_state["cmp_candidate_table"] = candidate_table

    candidate_table = st.session_state.get("cmp_candidate_table")
    if candidate_table is None:
        return

    st.divider()
    if candidate_table.empty:
        st.warning("No matches found with these settings.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Total hits", len(candidate_table))
    c2.metric("Distinct products", candidate_table["product_inchikey"].nunique())
    c3.metric("Distinct parent compounds", candidate_table["parent_inchikey"].nunique())
    if "acetyl_cooccurs" in candidate_table and candidate_table["acetyl_cooccurs"].notna().any():
        st.metric("Hits with acetyl co-occurrence", int(candidate_table["acetyl_cooccurs"].sum()))

    sorted_table = candidate_table.sort_values("relative_intensity", ascending=False)

    _MAX_DISPLAY_ROWS = 5000
    if len(sorted_table) > _MAX_DISPLAY_ROWS:
        st.caption(
            f"Showing the top {_MAX_DISPLAY_ROWS} of {len(sorted_table)} hits by relative "
            "intensity (the full result set is too large to display in-browser). "
            "Download the CSV below for everything."
        )
    st.dataframe(sorted_table.head(_MAX_DISPLAY_ROWS), width="stretch")

    csv_bytes = candidate_table.to_csv(index=False).encode("utf-8")
    if len(csv_bytes) <= _MAX_DOWNLOAD_BYTES:
        st.download_button(
            "Download candidate table (CSV)",
            csv_bytes,
            file_name="candidate_table.csv",
            mime="text/csv",
        )
    else:
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        csv_path = os.path.join(_OUTPUT_DIR, "candidate_table.csv")
        parquet_path = os.path.join(_OUTPUT_DIR, "candidate_table.parquet")
        candidate_table.to_csv(csv_path, index=False)
        candidate_table.to_parquet(parquet_path, index=False)
        st.info(
            f"Result table is too large ({len(csv_bytes) / 1e6:.0f} MB) to download "
            f"through the browser. Saved the full table to:\n\n"
            f"- `{csv_path}`\n- `{parquet_path}`"
        )
