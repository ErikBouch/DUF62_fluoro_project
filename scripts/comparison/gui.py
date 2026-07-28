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
from comparison import plotting  # noqa: E402
from comparison.matcher import (  # noqa: E402
    collapse_to_features, filter_acetyl_cooccurring, format_summary, run_match_pipeline,
    scan_count_breakdown, summarize_candidate_table, top_structures_by_formula,
)

_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "insilico_library", "data", "suspect_library.parquet",
)
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
_FIGURES_DIR = os.path.join(_OUTPUT_DIR, "figures")

# Streamlit's websocket messages (including download_button payloads) are
# capped at 200 MB; stay well under that so the button itself doesn't crash
# the page on large result sets. Above this, the full table is written to
# disk instead and the path is shown rather than streamed to the browser.
_MAX_DOWNLOAD_BYTES = 80_000_000


@st.cache_data(show_spinner=False)
def _cached_library(path: str, _mtime: float):
    import pandas as pd

    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _cached_structures_grid_image(top_df):
    """Cached: Streamlit reruns this whole page on any widget interaction,
    so without caching every one of the top 10 RDKit structures gets redrawn
    from scratch on every unrelated click, not just when the result changes.
    `top_df` only has 10 rows, so hashing it for the cache key is cheap."""
    return plotting.build_top_structures_grid_image(top_df)


def _render_table_with_download(df, sort_col: str, file_stem: str):
    """Shared display+download logic for both the raw-hit and feature tables:
    caps the on-screen preview and, when the full CSV is too large to stream
    to the browser, saves it to `output/` instead of crashing on Streamlit's
    message size limit."""
    sorted_df = df.sort_values(sort_col, ascending=False)

    max_display_rows = 5000
    if len(sorted_df) > max_display_rows:
        st.caption(
            f"Showing the top {max_display_rows} of {len(sorted_df)} rows by {sort_col} "
            "(the full result set is too large to display in-browser). "
            "Download the CSV below for everything."
        )
    st.dataframe(sorted_df.head(max_display_rows), width="stretch")

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    if len(csv_bytes) <= _MAX_DOWNLOAD_BYTES:
        st.download_button(
            f"Download {file_stem} (CSV)",
            csv_bytes,
            file_name=f"{file_stem}.csv",
            mime="text/csv",
            key=f"dl_{file_stem}",
        )
    else:
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        csv_path = os.path.join(_OUTPUT_DIR, f"{file_stem}.csv")
        parquet_path = os.path.join(_OUTPUT_DIR, f"{file_stem}.parquet")
        df.to_csv(csv_path, index=False)
        df.to_parquet(parquet_path, index=False)
        st.info(
            f"Result table is too large ({len(csv_bytes) / 1e6:.0f} MB) to download "
            f"through the browser. Saved the full table to:\n\n"
            f"- `{csv_path}`\n- `{parquet_path}`"
        )


def _render_acetyl_cooccurring_export(df, sort_col: str, file_stem: str):
    """Additional, separate export of just the acetyl-co-occurring subset --
    alongside the full table, not instead of it."""
    if "acetyl_cooccurs" not in df.columns or not df["acetyl_cooccurs"].notna().any():
        return
    cooccurring = filter_acetyl_cooccurring(df)
    with st.expander(f"Acetyl co-occurring subset ({len(cooccurring)} of {len(df)} rows)"):
        if cooccurring.empty:
            st.caption("No rows have acetyl co-occurrence with these settings.")
            return
        _render_table_with_download(cooccurring, sort_col, f"{file_stem}_acetyl_cooccurring")


def _render_scan_count_bar(breakdown_df):
    """Bar chart of `matcher.scan_count_breakdown`'s output: how many features
    clear each minimum-consecutive-scans threshold -- the direct answer to
    "how many real candidates survive a stricter cut", no distribution or
    axis-reading required."""
    try:
        import plotly.express as px
    except ImportError:
        st.caption("(install `plotly` for a chart)")
        return

    plot_df = breakdown_df.assign(label=[f">= {t}" for t in breakdown_df["threshold"]])
    fig = px.bar(
        plot_df, x="label", y="count", text="count",
        labels={"label": "Minimum consecutive scans", "count": "Features"},
    )
    fig.update_traces(marker_color="#2dd4bf", textposition="outside")
    fig.update_layout(height=400)
    st.plotly_chart(fig, width="stretch")


def _render_structure_grid(top_df):
    """Top-10-by-scan-evidence product structures (deduplicated by formula),
    drawn with RDKit -- a real structure is far more immediately meaningful to
    a chemist than an InChIKey or a table row."""
    if top_df.empty:
        st.caption("No products to show yet.")
        return None

    error = plotting.structure_rendering_error()
    if error:
        st.warning(
            "Structure rendering isn't available in this Python environment "
            f"(`rdkit.Chem.Draw` failed to import: {error}). Everything else "
            "on this page still works; this usually means rdkit needs "
            "reinstalling in this environment."
        )
        return None

    image = _cached_structures_grid_image(top_df)
    if image is None:
        st.caption("No parseable structures among the top candidates.")
        return None

    st.image(image, width="stretch")
    return image


def _render_feature_map(df, rt_col: str, mass_col: str, intensity_col: str):
    """RT-vs-mass scatter -- useful for exploring individual hits, but a
    detail/power-user tool rather than a summary, so it's shown after the
    bar chart and structure grid above: sized by intensity, colored by acetyl
    co-occurrence (if that check was run) or by file otherwise."""
    if df.empty:
        return

    try:
        import plotly.express as px
    except ImportError:
        st.caption("(install `plotly` for a visual RT/mass overview)")
        return

    color_col = "polarity"
    if "acetyl_cooccurs" in df.columns and df["acetyl_cooccurs"].notna().any():
        color_col = "acetyl_cooccurs"

    hover_cols = [c for c in ["product_formula", "parent_organism", "reaction"] if c in df.columns]
    plot_df = df if len(df) <= 20_000 else df.nlargest(20_000, intensity_col)
    if len(df) > 20_000:
        st.caption(f"Plotting the top 20,000 of {len(df)} rows by {intensity_col} for responsiveness.")

    fig = px.scatter(
        plot_df, x=rt_col, y=mass_col, size=intensity_col, color=color_col,
        hover_data=hover_cols,
        labels={rt_col: "RT (min)", mass_col: "m/z", intensity_col: "Intensity"},
    )
    fig.update_layout(height=500)
    st.plotly_chart(fig, width="stretch")


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

        col_int, col_scans = st.columns(2)
        min_intensity = col_int.number_input(
            "Min. absolute intensity", value=50_000.0, min_value=0.0, key="cmp_min_intensity",
            help="Raw instrument units. A peak below this is never counted as a hit; 0 disables.",
        )
        min_consecutive_scans = col_scans.number_input(
            "Min. consecutive scans", value=3, min_value=1, step=1, key="cmp_min_consecutive_scans",
            help="A hit only counts if it's part of a run of at least this many scans "
                 "in a row (within the RT gap below); 1 disables.",
        )
        max_rt_gap = st.number_input(
            "Max. RT gap defining \"consecutive\" (minutes)", value=0.1, min_value=0.0,
            format="%.3f", key="cmp_max_rt_gap",
            help="Used both by the min. consecutive scans filter and by feature collapsing below.",
        )

        check_acetyl = st.checkbox(
            "Require checking the acetyl analog too (co-occurrence)",
            value=False, key="cmp_check_acetyl",
        )
        acetyl_tolerance, acetyl_unit, acetyl_rt_window = 5.0, "ppm", 2.0
        if check_acetyl:
            col5, col6 = st.columns(2)
            acetyl_tolerance = col5.number_input("Acetyl tolerance", value=5.0, min_value=0.0, key="cmp_acetyl_tolerance")
            acetyl_unit = col6.selectbox("Acetyl unit", ["ppm", "Da"], key="cmp_acetyl_unit")
            acetyl_rt_window = st.number_input(
                "Acetyl RT window (minutes)", value=2.0, min_value=0.0, key="cmp_acetyl_rt_window",
                help="The acetyl analog only counts as co-occurring if found within this many "
                     "minutes of the fluoroacetyl hit's own RT.",
            )

        collapse_features = st.checkbox(
            "Collapse to features (one row per contiguous elution event, instead "
            "of one row per scan)",
            value=False, key="cmp_collapse_features",
        )

    st.divider()

    if not file_paths:
        st.info("Pick at least one mzML file to run a match.")
        return

    if st.button("Run match", type="primary"):
        status = st.empty()
        progress_bar = st.progress(0.0)
        candidate_table = run_match_pipeline(
            library, file_paths,
            fluoroacetyl_tolerance=tolerance, fluoroacetyl_unit=unit,
            ms_level=ms_level, min_relative_intensity=min_rel,
            min_absolute_intensity=min_intensity or None,
            min_consecutive_scans=min_consecutive_scans, max_rt_gap_minutes=max_rt_gap,
            check_acetyl_cooccurrence=check_acetyl,
            acetyl_tolerance=acetyl_tolerance, acetyl_unit=acetyl_unit,
            acetyl_rt_window_minutes=acetyl_rt_window,
            progress_callback=status.text,
            progress_fraction_callback=progress_bar.progress,
        )
        if not candidate_table.empty:
            status.text("Collapsing to features for the summary visuals...")
            features_for_viz = collapse_to_features(candidate_table, max_rt_gap_minutes=max_rt_gap)
        else:
            features_for_viz = candidate_table
        status.empty()
        progress_bar.empty()
        st.session_state["cmp_candidate_table"] = candidate_table
        st.session_state["cmp_features_for_viz"] = features_for_viz
        # Only keep a separately-collapsed features table for the main view
        # toggle if the user actually asked for it -- features_for_viz above
        # always exists (for the summary charts) regardless of this choice.
        st.session_state["cmp_features_table"] = features_for_viz if collapse_features else None

    candidate_table = st.session_state.get("cmp_candidate_table")
    if candidate_table is None:
        return

    st.divider()
    if candidate_table.empty:
        st.warning("No matches found with these settings.")
        return

    st.code(format_summary(summarize_candidate_table(candidate_table)), language=None)

    features_for_viz = st.session_state["cmp_features_for_viz"]

    st.divider()
    st.subheader("Summary")
    if not features_for_viz.empty and features_for_viz["acetyl_cooccurs"].notna().any():
        features_for_summary = filter_acetyl_cooccurring(features_for_viz)
        st.caption(
            f"Based on the {len(features_for_summary)} of {len(features_for_viz)} features with acetyl "
            "co-occurrence -- the final, most-filtered result set, not the raw pre-acetyl-check hits."
        )
    else:
        features_for_summary = features_for_viz
        st.caption(f"Based on all {len(features_for_viz)} features (acetyl co-occurrence wasn't checked).")

    # Shared with the Molecule Explorer tab, so it browses the exact same
    # final-filtered result rather than recomputing the acetyl filter itself.
    st.session_state["cmp_features_for_summary"] = features_for_summary

    thresholds = tuple(sorted({min_consecutive_scans, 50, 100, 200, 500}))
    breakdown = scan_count_breakdown(candidate_table, thresholds=thresholds, features_table=features_for_summary)
    _render_scan_count_bar(breakdown)

    top_structures = top_structures_by_formula(candidate_table, top_n=10, features_table=features_for_summary)
    st.caption(
        "Top 10 product formulas by total scan evidence (deduplicated -- isomers/salts sharing a formula "
        "count once; a formula can bundle several distinct structures, see \"1 of N structures\" below)."
    )
    grid_image = _render_structure_grid(top_structures)

    os.makedirs(_FIGURES_DIR, exist_ok=True)
    plotting.save_scan_count_breakdown_figure(breakdown, os.path.join(_FIGURES_DIR, "scan_count_breakdown.png"))
    plotting.save_top_structures_grid(grid_image, os.path.join(_FIGURES_DIR, "top_structures.png"))

    features_table = st.session_state.get("cmp_features_table")
    if features_table is not None:
        view = st.radio(
            "View", ["Features (collapsed)", "Raw hits"], horizontal=True, key="cmp_view",
        )
    else:
        view = "Raw hits"

    if view == "Features (collapsed)":
        st.metric("Features", len(features_table))
        _render_table_with_download(features_table, "apex_relative_intensity", "candidate_features")
        _render_acetyl_cooccurring_export(features_table, "apex_relative_intensity", "candidate_features")
        rt_col, mass_col, intensity_col = "apex_rt_minutes", "product_exact_mass", "apex_intensity"
        feature_map_df = features_table
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total hits", len(candidate_table))
        c2.metric("Distinct products", candidate_table["product_inchikey"].nunique())
        c3.metric("Distinct parent compounds", candidate_table["parent_inchikey"].nunique())
        if "acetyl_cooccurs" in candidate_table and candidate_table["acetyl_cooccurs"].notna().any():
            st.metric("Hits with acetyl co-occurrence", int(candidate_table["acetyl_cooccurs"].sum()))
        _render_table_with_download(candidate_table, "relative_intensity", "candidate_table")
        _render_acetyl_cooccurring_export(candidate_table, "relative_intensity", "candidate_table")
        rt_col, mass_col, intensity_col = "rt_minutes", "matched_mz", "intensity"
        feature_map_df = candidate_table

    st.divider()
    st.subheader("Feature map")
    _render_feature_map(feature_map_df, rt_col, mass_col, intensity_col)
    plotting.save_feature_map_figure(feature_map_df, rt_col, mass_col, intensity_col,
                                      os.path.join(_FIGURES_DIR, "feature_map.png"))
    st.caption(f"Figures saved to `{_FIGURES_DIR}`")
