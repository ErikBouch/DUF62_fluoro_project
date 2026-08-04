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
from common.ui import (  # noqa: E402
    awaiting_input, mount_key, page_header, persist, pick_mzml_files,
    resolved_shared_mzml_files, restore, status_button,
)
from mzml_tools.scan_detector import (  # noqa: E402
    extract_ion_chromatogram,
    find_scans_with_mz,
    get_file_overview,
)


@st.cache_data(show_spinner=False)
def _cached_overview(path: str, mtime: float):
    # `mtime`, not a leading-underscore `_mtime`: Streamlit excludes any
    # leading-underscore argument from the cache key entirely, so a changed
    # file would otherwise silently keep returning the stale cached overview.
    return get_file_overview(path)


@st.cache_data(show_spinner=False)
def _cached_search(path: str, mtime: float, target_mz, tol, unit, threshold, min_rel, ms_level):
    return find_scans_with_mz(path, target_mz, tol, unit, threshold, min_rel, ms_level)


def _pick_files() -> tuple[list[str], str | None]:
    """
    Multiple files can be picked at once (`pick_mzml_files`, shared with MS
    Matching); when more than one is picked, a second selector chooses which
    ONE is currently being explored below (file overview, single-target
    search, XIC) -- "switch between them" rather than only ever working with
    one file at a time. Returns (all picked paths, the currently active one).
    """
    file_paths = pick_mzml_files(key="scan_files", default=resolved_shared_mzml_files())
    if not file_paths:
        return [], None
    if len(file_paths) == 1:
        return file_paths, file_paths[0]

    labels = {path: os.path.basename(path) for path in file_paths}
    restore("scan_active_file", file_paths[0], valid_options=file_paths)
    active = st.selectbox(
        "Exploring", file_paths, format_func=lambda p: labels[p], key="scan_active_file",
    )
    persist("scan_active_file")
    return file_paths, active


def _render_diagnostic_targets(active_path: str, active_mtime: float):
    """
    A curated list of candidate diagnostic fragment-ion m/z values, shared
    with MS Matching's MS2 high-confidence filter. Persisted like every other
    setting (`restore`/`persist`) so it survives page navigation *and*
    saves/loads with a settings preset -- unlike a typical single-value
    widget, this one is a whole list that gets mutated in place (append/
    remove/per-item checkbox), so `persist()` is called again after every
    such mutation rather than once right after a single widget. Each target
    can be explored here individually (reuses the single-target search/XIC
    below, against whichever file is currently active) before deciding
    whether to actually use it in that filter -- adding a candidate ion to
    try out shouldn't silently commit it.
    """
    restore("diagnostic_targets", [])
    targets = st.session_state["diagnostic_targets"]
    restore("_diagnostic_target_next_id", 0)
    next_id = st.session_state["_diagnostic_target_next_id"]
    # A widget's own session_state entry can only be set *before* that widget
    # is instantiated in a given run -- so "clear the label/m/z fields after
    # adding" can't happen inline in the button handler below (its widgets
    # already rendered earlier in that same run). Defer it: the handler sets
    # this flag and reruns; the *next* run clears both fields here, first.
    if st.session_state.pop("_clear_new_target_fields", False):
        st.session_state["new_target_label"] = ""
        st.session_state["new_target_mz"] = 0.0

    with st.expander(
        f"Diagnostic ion targets ({len(targets)})", expanded=bool(targets),
        key="flap_ink_diagnostic_targets",
    ):
        st.caption(
            "Candidate fragment-ion m/z values to check for in MS2 spectra. Explore one "
            "against the currently active file above, then check \"use in filter\" to "
            "include it in MS Matching's MS2 high-confidence filter."
        )
        for target in list(targets):
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
            c1.markdown(f"**{target['label']}**")
            c2.markdown(f"m/z {target['target_mz']:.4f}")
            target["use_in_filter"] = c3.checkbox(
                "Use in filter", value=target["use_in_filter"], key=f"target_use_{target['id']}",
            )
            if c4.button("Explore", key=f"target_explore_{target['id']}"):
                st.session_state["scan_target_mz"] = target["target_mz"]
                tolerance = st.session_state.get("scan_tolerance", 25.0)
                unit = st.session_state.get("scan_unit", "ppm")
                threshold = st.session_state.get("scan_threshold", 0.0)
                min_rel_pct = st.session_state.get("scan_min_rel", 2)
                ms_level_choice = st.session_state.get("scan_ms_level", "2")
                ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
                with st.spinner(f"Searching for {target['label']}..."):
                    matches = _cached_search(
                        active_path, active_mtime, target["target_mz"], tolerance, unit,
                        threshold, min_rel_pct / 100.0, ms_level,
                    )
                st.session_state["scan_matches"] = matches
                st.session_state["scan_matches_mz"] = target["target_mz"]
            if c5.button("Remove", key=f"target_remove_{target['id']}"):
                targets.remove(target)
                persist("diagnostic_targets")
                st.rerun()

        # Persists every "use in filter" checkbox toggle from the loop above
        # in one call, not once per existing target on every single rerun.
        persist("diagnostic_targets")

        st.divider()
        col1, col2, col3 = st.columns([2, 2, 1])
        new_label = col1.text_input("Label", key="new_target_label")
        new_mz = col2.number_input("m/z", format="%.4f", key="new_target_mz")
        if col3.button("Add target") and new_label.strip():
            targets.append({
                "id": next_id, "label": new_label.strip(), "target_mz": new_mz, "use_in_filter": True,
            })
            st.session_state["_diagnostic_target_next_id"] = next_id + 1
            persist("_diagnostic_target_next_id")
            persist("diagnostic_targets")
            st.session_state["_clear_new_target_fields"] = True
            st.rerun()


def render():
    page_header(
        "mzML Scan Detector",
        "Find scans containing a target m/z (within tolerance, above an intensity filter) and export them to CSV.",
    )

    with st.container(key="sheet_scan_load"):
        _, path = _pick_files()
        ready = bool(path and os.path.isfile(path))
        mtime = os.path.getmtime(path) if ready else None

        if ready:
            with st.spinner("Reading file overview..."):
                overview = _cached_overview(path, mtime)

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

    # Restored here, before anything below reads these keys -- including
    # `_render_diagnostic_targets`'s "Explore" button, which reuses whatever
    # tolerance/unit/etc. are currently set, and reading them before they've
    # been restored this render would silently fall back to the hardcoded
    # defaults below instead of the user's actual saved settings -- same
    # class of bug as the shared mzML/library-path keys elsewhere in this
    # app. `restore()` is a no-op the second time it's called for an
    # already-set key, so the widgets further down are unaffected by
    # restoring these this early, and doing it before the `ready` gate below
    # (rather than only once a file exists) means the filter widgets and the
    # "Find scans" status button can render regardless of whether a file's
    # picked yet -- matching every other module's page, where the run
    # button and its own settings are always visible, not hidden behind a
    # precondition.
    restore("scan_target_mz", 100.0)
    restore("scan_tolerance", 25.0)
    restore("scan_unit", "ppm", valid_options=["ppm", "Da"])
    restore("scan_ms_level", "2", valid_options=["All", "1", "2"])
    restore("scan_min_rel", 2)
    restore("scan_threshold", 0.0)

    with st.container(key="sheet_scan_params"):
        col1, col2, col3 = st.columns(3)
        target_mz = col1.number_input("Target m/z", format="%.4f", key="scan_target_mz")
        tolerance = col2.number_input(
            "Tolerance", min_value=0.1, key="scan_tolerance",
            help="How far a scan's peak m/z may be from the target and still count as a match. "
                 "ppm scales with mass (wider window for a heavier ion); Da is a fixed window at "
                 "every mass.",
        )
        unit = col3.selectbox("Unit", ["ppm", "Da"], key="scan_unit")
        persist("scan_target_mz")
        persist("scan_tolerance")
        persist("scan_unit")

        col4, col5 = st.columns(2)
        ms_level_choice = col4.selectbox(
            "MS level", ["All", "1", "2"], key="scan_ms_level",
            help="MS1 = the instrument's regular full-scan spectra (an intact compound's own mass). "
                 "MS2 = fragment spectra recorded after selecting one precursor mass -- only "
                 "meaningful for a target that's actually a fragment ion, not a whole molecule.",
        )
        ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
        min_rel_pct = col5.slider(
            "Min. relative intensity (% of that scan's base peak)", 0, 100, key="scan_min_rel",
            help="Relative to each scan's own tallest peak, not one global maximum across the whole "
                 "file -- the same absolute intensity can pass in a quiet scan and fail in a busy one.",
        )
        min_rel = min_rel_pct / 100.0
        persist("scan_ms_level")
        persist("scan_min_rel")

        if ready:
            _render_diagnostic_targets(path, mtime)

        with st.expander("Advanced", key="flap_amber_scan_advanced"):
            threshold = st.number_input(
                "Min. absolute intensity (0 = off)", min_value=0.0, key="scan_threshold",
                help="Raw instrument units, applied in addition to the relative-intensity filter "
                     "above -- a peak below this never counts as a hit, however high its relative "
                     "intensity is; 0 disables it.",
            )
            persist("scan_threshold")

    with st.container(key="sheet_scan_run"):
        status = (
            "Possible -- ready to search." if ready
            else "Not possible yet -- pick or enter an mzML file above."
        )
        if status_button("Find scans", "scan_btn_find", ready, status):
            with st.spinner("Searching spectra..."):
                matches = _cached_search(
                    path, os.path.getmtime(path), target_mz, tolerance, unit, threshold, min_rel, ms_level,
                )
            st.session_state["scan_matches"] = matches
            st.session_state["scan_matches_mz"] = target_mz

    matches = st.session_state.get("scan_matches")
    analyze_key = (
        mount_key("sheet_scan_analyze", "scan_analyze_entered")
        if matches is not None else "sheet_scan_analyze"
    )
    with st.container(key=analyze_key):
        if matches is None:
            awaiting_input("Run Find scans above to see results.", key="await_scan_analyze")
        else:
            import pandas as pd

            df = pd.DataFrame([m.__dict__ for m in matches])
            st.divider()

            if df.empty:
                st.warning("No matching scans found with these settings.")
            else:
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
                restore("xic_ms_level", "1", valid_options=["1", "2"])
                xic_ms_level = st.selectbox("XIC MS level", ["1", "2"], key="xic_ms_level")
                persist("xic_ms_level")
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
