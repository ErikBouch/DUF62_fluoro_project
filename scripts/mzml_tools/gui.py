"""
mzml_tools/gui.py — Streamlit page for the mzML scan detector.

GUI only: all science logic lives in scan_detector.py so it stays testable
and usable from the CLI without Streamlit installed.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import find_mzml_files, page_header  # noqa: E402
from mzml_tools.scan_detector import (  # noqa: E402
    extract_ion_chromatogram,
    find_scans_with_mz,
    get_file_overview,
)


@st.cache_data(show_spinner=False)
def _cached_overview(path: str, _mtime: float):
    return get_file_overview(path)


@st.cache_data(show_spinner=False)
def _cached_search(path: str, _mtime: float, target_mz, tol, unit, threshold, min_rel, ms_level):
    return find_scans_with_mz(path, target_mz, tol, unit, threshold, min_rel, ms_level)


def _pick_file() -> str | None:
    discovered = find_mzml_files()
    options = ["-- choose a file --"] + [label for label, _ in discovered] + ["Custom path..."]
    choice = st.selectbox("mzML file", options, key="scan_file_choice")

    if choice == "-- choose a file --":
        return None
    if choice == "Custom path...":
        return st.text_input("Full path to an .mzML file", key="scan_custom_path") or None
    return dict(discovered)[choice]


def render():
    page_header(
        "mzML Scan Detector",
        "Find scans containing a target m/z (within tolerance, above an intensity filter) and export them to CSV.",
    )

    path = _pick_file()
    if not path or not os.path.isfile(path):
        st.info("Pick or enter an .mzML file to begin.")
        return

    mtime = os.path.getmtime(path)
    with st.spinner("Reading file overview..."):
        overview = _cached_overview(path, mtime)

    with st.expander("File overview", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Spectra", overview.n_spectra)
        c2.metric("Polarity", "/".join(overview.polarity_counts))
        c3.metric(
            "RT range",
            f"{overview.rt_range_minutes[0]:.1f}-{overview.rt_range_minutes[1]:.1f} min",
        )
        st.caption("MS levels: " + ", ".join(f"MS{k}: {v} scans" for k, v in sorted(overview.ms_level_counts.items())))
        for lvl, (lo, hi) in sorted(overview.mz_range_by_level.items()):
            st.caption(f"MS{lvl} observed m/z range: {lo:.3f} - {hi:.3f}")
        st.caption(
            "On some instruments/methods, the MS1 scan range doesn't extend down to very "
            "low m/z, so small fragment ions may only be observable as MS2 product ions."
        )

    if "scan_target_mz" not in st.session_state:
        st.session_state["scan_target_mz"] = 100.0

    col1, col2, col3 = st.columns(3)
    target_mz = col1.number_input("Target m/z", format="%.4f", key="scan_target_mz")
    tolerance = col2.number_input("Tolerance", value=25.0, min_value=0.1, key="scan_tolerance")
    unit = col3.selectbox("Unit", ["ppm", "Da"], key="scan_unit")

    col4, col5 = st.columns(2)
    ms_level_choice = col4.selectbox("MS level", ["All", "1", "2"], index=2, key="scan_ms_level")
    ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
    min_rel_pct = col5.slider("Min. relative intensity (% of that scan's base peak)", 0, 100, 2, key="scan_min_rel")
    min_rel = min_rel_pct / 100.0

    with st.expander("Advanced"):
        threshold = st.number_input("Min. absolute intensity (0 = off)", value=0.0, min_value=0.0, key="scan_threshold")

    if st.button("Find scans", type="primary"):
        with st.spinner("Searching spectra..."):
            matches = _cached_search(path, mtime, target_mz, tolerance, unit, threshold, min_rel, ms_level)
        st.session_state["scan_matches"] = matches
        st.session_state["scan_matches_mz"] = target_mz

    matches = st.session_state.get("scan_matches")
    if matches is None:
        return

    import pandas as pd

    df = pd.DataFrame([m.__dict__ for m in matches])
    st.divider()

    if df.empty:
        st.warning("No matching scans found with these settings.")
        return

    n_distinct_precursors = df["precursor_mz"].dropna().round(2).nunique() if "precursor_mz" in df else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Matching scans", len(df))
    c2.metric("Distinct precursor masses", n_distinct_precursors)
    c3.metric("Max relative intensity", f"{df['relative_intensity'].max():.0%}")

    st.dataframe(df.sort_values("intensity", ascending=False), width="stretch")

    st.download_button(
        "Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{os.path.splitext(os.path.basename(path))[0]}_mz{st.session_state['scan_matches_mz']:g}.csv",
        mime="text/csv",
    )

    try:
        import plotly.express as px

        fig = px.scatter(
            df, x="rt_minutes", y="relative_intensity",
            size="intensity", color="ms_level",
            hover_data=["matched_mz", "precursor_mz", "native_id"],
            labels={"rt_minutes": "RT (min)", "relative_intensity": "Relative intensity"},
        )
        st.plotly_chart(fig, width="stretch")
    except ImportError:
        st.caption("(install `plotly` for an interactive RT/intensity plot)")

    st.divider()
    st.subheader("Extracted ion chromatogram (XIC)")
    st.caption(
        "A continuous intensity-vs-RT trace for the target m/z (every scan, not just "
        "above-threshold hits) -- the standard way to see whether there's a real "
        "chromatographic peak. Most meaningful at MS1 for an intact compound's own mass; "
        "MS2 fragment traces are noisier since many precursors share scan cycles."
    )
    xic_ms_level = st.selectbox("XIC MS level", ["1", "2"], key="xic_ms_level")
    if st.button("Compute XIC"):
        with st.spinner("Building chromatogram..."):
            points = extract_ion_chromatogram(path, target_mz, tolerance, unit, int(xic_ms_level))
        import plotly.graph_objects as go

        rt = [p.rt_minutes for p in points]
        inten = [p.intensity for p in points]
        fig = go.Figure(go.Scatter(x=rt, y=inten, mode="lines", fill="tozeroy", line=dict(color="#2dd4bf")))
        fig.update_layout(xaxis_title="RT (min)", yaxis_title="Intensity")
        st.plotly_chart(fig, width="stretch")
        if inten:
            apex = max(points, key=lambda p: p.intensity)
            st.caption(f"Apex: RT {apex.rt_minutes:.2f} min, intensity {apex.intensity:.3e}")
