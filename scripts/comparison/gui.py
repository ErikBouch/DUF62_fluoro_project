"""
comparison/gui.py — Streamlit page for matching the suspect library against
mzML data.

GUI only: all science logic lives in matcher.py so it stays testable and
usable from the CLI without Streamlit installed.
"""
from __future__ import annotations

import os
import sys
import time

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.run_log import append_run, render_run_log  # noqa: E402
from common.ui import (  # noqa: E402
    SHARED_CANDIDATE_TABLE_KEY, SHARED_SUSPECT_LIBRARY_KEY,
    awaiting_input, mount_key, notify_done, page_header, persist, pick_mzml_files,
    render_last_notification, resolved_shared_mzml_files, restore, status_button,
)
from comparison import plotting  # noqa: E402
from comparison.matcher import (  # noqa: E402
    collapse_to_features, filter_acetyl_cooccurring, format_summary, run_match_pipeline,
    scan_count_breakdown, summarize_candidate_table, top_structures_by_formula,
)
from comparison.ms2_confidence import DiagnosticTarget, find_ms2_support  # noqa: E402

# The suspect library is built to this fixed location by default by the
# In-silico Library page (`insilico_library/gui.py`), regardless of what raw
# library the user pointed it at -- a computed result, not input data, so it
# lives in that module's output/, not data/. The Setup page can point at a
# different suspect library entirely (see `_resolve_library_path`).
_DEFAULT_LIBRARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "insilico_library", "output", "suspect_library.parquet",
)
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
_DEFAULT_CANDIDATE_TABLE_PATH = os.path.join(_OUTPUT_DIR, "candidate_table.parquet")
_FIGURES_DIR = os.path.join(_OUTPUT_DIR, "figures")
# Separate run-log files per action, same reasoning as insilico_library/gui.py:
# each action's own natural columns, its own history table.
_MATCH_RUN_LOG = "match_run_log.csv"
_MS2_RUN_LOG = "ms2_run_log.csv"


def _resolve_library_path() -> str:
    """Whatever suspect library the Setup page points at, falling back to
    this module's own standard build location."""
    restore(SHARED_SUSPECT_LIBRARY_KEY, _DEFAULT_LIBRARY_PATH if os.path.isfile(_DEFAULT_LIBRARY_PATH) else "")
    return st.session_state.get(SHARED_SUSPECT_LIBRARY_KEY, "") or _DEFAULT_LIBRARY_PATH


# "Lock Calibration" (PARAMETERS sheet): a settings-review gate. Locking
# snapshots every current PARAMETERS-sheet value; if ANY of them change
# afterward, the lock auto-clears -- otherwise it's a checkbox with no
# teeth (reviewed-then-silently-stale). See `_calibration_snapshot` and the
# invalidation check in `render()`, right after the Optional Filters block.
_CALIBRATION_SNAPSHOT_KEYS = [
    "cmp_tolerance", "cmp_unit",
    "cmp_ms_level", "cmp_min_rel", "cmp_min_intensity", "cmp_min_consecutive_scans",
    "cmp_max_rt_gap", "cmp_check_acetyl", "cmp_acetyl_tolerance", "cmp_acetyl_unit",
    "cmp_acetyl_rt_window", "cmp_collapse_features", "cmp_check_ms2",
    "ms2_precursor_tolerance", "ms2_precursor_unit", "ms2_rt_window",
    "ms2_ion_tolerance", "ms2_ion_unit",
]


def _calibration_snapshot() -> dict:
    snap = {k: st.session_state.get(k) for k in _CALIBRATION_SNAPSHOT_KEYS}
    # diagnostic_targets lives on a DIFFERENT page (mzML Scan Detector) but
    # materially changes what the MS2 filter checks -- without this, editing
    # a target there would invalidate nothing, defeating the point.
    targets = st.session_state.get("diagnostic_targets", [])
    snap["_active_targets"] = sorted(
        (t["label"], round(t["target_mz"], 6)) for t in targets if t["use_in_filter"]
    )
    return snap


def calibrate_status() -> str:
    """'done' if match_calibration_locked is currently True (i.e. "currently
    locked," not "was ever locked" -- the lock auto-clears the moment any
    PARAMETERS-sheet value changes, see `_calibration_snapshot`); else
    'todo'. No 'failed' state. Pure, side-effect-free -- read by main.py's
    pipeline stepper on every rerun, regardless of which page is currently
    showing."""
    return "done" if st.session_state.get("match_calibration_locked") else "todo"


def execute_match_status() -> str:
    """'done' if cmp_candidate_table is in session_state and non-empty;
    'failed' if present and empty; else 'todo'. Pure, side-effect-free --
    read by main.py's pipeline stepper on every rerun, regardless of which
    page is currently showing."""
    table = st.session_state.get("cmp_candidate_table")
    if table is None:
        return "todo"
    return "failed" if table.empty else "done"


# Streamlit's websocket messages (including download_button payloads) are
# capped at 200 MB; stay well under that so the button itself doesn't crash
# the page on large result sets. Above this, the full table is written to
# disk instead and the path is shown rather than streamed to the browser.
_MAX_DOWNLOAD_BYTES = 80_000_000


@st.cache_data(show_spinner=False)
def _cached_library(path: str, mtime: float):
    # `mtime`, not a leading-underscore `_mtime`: Streamlit excludes any
    # leading-underscore argument from the cache key entirely, so a changed
    # file would otherwise silently keep returning the stale cached table.
    import pandas as pd

    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _cached_structures_grid_image(top_df):
    """Cached: Streamlit reruns this whole page on any widget interaction,
    so without caching every one of the top 10 RDKit structures gets redrawn
    from scratch on every unrelated click, not just when the result changes.
    `top_df` only has 10 rows, so hashing it for the cache key is cheap."""
    return plotting.build_top_structures_grid_image(top_df)


def _render_table_with_download(df, sort_col: str, file_stem: str, save: bool = True):
    """Shared display+download logic for both the raw-hit and feature tables:
    caps the on-screen preview and, when `save` (the default), saves the full
    table to `output/` under `file_stem` -- not only when it's too large for
    an in-browser download. Every filter combination this produces (raw hits,
    acetyl-co-occurring subset, collapsed features, MS2-confident subset, ...)
    needs a real file on disk so it can be picked from later
    (`_discover_output_variants`/the "View a saved result" selector below),
    regardless of whether this particular run happened to be small enough to
    also offer as a direct download.

    The *disk write* happens at most once per `file_stem` per fresh dataset,
    tracked via `cmp_saved_stems` (cleared whenever genuinely new data
    arrives -- see `_populate_result_session_state`/the MS2 cross-check
    button) -- not on every page rerun. This page renders its whole results
    view on every interaction (including ones with nothing to do with this
    table, e.g. toggling an unrelated checkbox), and a real hit was found in
    practice: re-serializing and rewriting a 240 MB CSV *and* its parquet
    copy on every single one of those reruns made the rest of the page --
    including anything below this table -- visibly slow to appear, easily
    mistaken for the page being stuck.

    The download control itself still shows on *every* render, not only the
    one where the write happened -- an earlier version of this fix returned
    right after the "already saved" caption, which also skipped the download
    button/oversize-notice entirely on every subsequent rerun, a real
    regression from the fix's intent. Once already saved, a small file is
    read back from disk for the download button (cheap -- it's small by
    definition) rather than re-encoded from `df`; a large one just gets a
    static info message pointing at its path, no disk access at all.

    `save=False` when merely *viewing* a variant already loaded from disk via
    that same selector -- writing under `file_stem` would silently overwrite
    a *different* file's canonical name with this variant's content (e.g.
    viewing the MS2-confident subset would otherwise clobber plain
    `candidate_features.parquet`)."""
    sorted_df = df.sort_values(sort_col, ascending=False)

    max_display_rows = 5000
    if len(sorted_df) > max_display_rows:
        st.caption(
            f"Showing the top {max_display_rows} of {len(sorted_df)} rows by {sort_col} "
            "(the full result set is too large to display in-browser)."
            + (" Download the CSV below for everything." if save else "")
        )
    st.dataframe(sorted_df.head(max_display_rows), width="stretch")

    if not save:
        return

    csv_path = os.path.join(_OUTPUT_DIR, f"{file_stem}.csv")
    parquet_path = os.path.join(_OUTPUT_DIR, f"{file_stem}.parquet")
    saved_stems = st.session_state.setdefault("cmp_saved_stems", set())

    if file_stem not in saved_stems:
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        with open(csv_path, "wb") as f:
            f.write(csv_bytes)
        df.to_parquet(parquet_path, index=False)
        saved_stems.add(file_stem)
    else:
        csv_bytes = None  # not re-encoded; read back below only if actually small

    csv_size = len(csv_bytes) if csv_bytes is not None else os.path.getsize(csv_path)
    if csv_size <= _MAX_DOWNLOAD_BYTES:
        if csv_bytes is None:
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
        st.download_button(
            f"Download {file_stem} (CSV)",
            csv_bytes,
            file_name=f"{file_stem}.csv",
            mime="text/csv",
            key=f"dl_{file_stem}",
        )
    else:
        st.info(
            f"Result table is too large ({csv_size / 1e6:.0f} MB) to download "
            f"through the browser. Saved the full table to:\n\n"
            f"- `{csv_path}`\n- `{parquet_path}`"
        )


def _render_acetyl_cooccurring_export(df, sort_col: str, file_stem: str, save: bool = True):
    """Additional, separate export of just the acetyl-co-occurring subset --
    alongside the full table, not instead of it."""
    if "acetyl_cooccurs" not in df.columns or not df["acetyl_cooccurs"].notna().any():
        return
    cooccurring = filter_acetyl_cooccurring(df)
    with st.expander(f"Acetyl co-occurring subset ({len(cooccurring)} of {len(df)} rows)"):
        if cooccurring.empty:
            st.caption("No rows have acetyl co-occurrence with these settings.")
            return
        _render_table_with_download(cooccurring, sort_col, f"{file_stem}_acetyl_cooccurring", save=save)


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


def _populate_result_session_state(candidate_table, max_rt_gap, collapse_features, features_for_viz=None):
    """
    Compute and store every session_state entry the rest of this page (and
    the Molecule Explorer tab) reads. Shared by both a fresh "Run match" and
    loading a previously saved result from disk, so the two paths can't
    silently drift apart.

    `cmp_features_for_summary` is set exactly once here (not recomputed on
    every unrelated rerun) -- see the 2026-07-31 "Load more" bug fix: a
    fresh object identity on every rerun broke Molecule Explorer's id()-keyed
    pagination cache.

    Also resets the "viewing a saved output/ variant" state
    (`_load_output_variant`) back to its default -- a fresh "Run match" or
    loading the default saved result is always the full, unfiltered result,
    so any leftover "you're viewing the acetyl-only subset" label from an
    earlier variant-browser pick must not persist onto it.

    Also resets Molecule Explorer's own `explorer_reviewed`/
    `explorer_last_result_empty` flags -- both belong to whatever result was
    loaded before, not this one, and would otherwise stay stuck reporting a
    stale previous result forever.
    """
    st.session_state["cmp_active_variant_label"] = None
    st.session_state["cmp_variant_raw_hits_available"] = True
    st.session_state["cmp_saved_stems"] = set()
    st.session_state["explorer_reviewed"] = False
    st.session_state["explorer_last_result_empty"] = False
    if features_for_viz is None:
        if not candidate_table.empty:
            features_for_viz = collapse_to_features(candidate_table, max_rt_gap_minutes=max_rt_gap)
        else:
            features_for_viz = candidate_table
    st.session_state["cmp_candidate_table"] = candidate_table
    st.session_state["cmp_features_for_viz"] = features_for_viz
    # Only keep a separately-collapsed features table for the main view
    # toggle if the user actually asked for it -- features_for_viz above
    # always exists (for the summary charts) regardless of this choice.
    st.session_state["cmp_features_table"] = features_for_viz if collapse_features else None
    if not features_for_viz.empty and features_for_viz["acetyl_cooccurs"].notna().any():
        st.session_state["cmp_features_for_summary"] = filter_acetyl_cooccurring(features_for_viz)
    else:
        st.session_state["cmp_features_for_summary"] = features_for_viz
    # A previous MS2 cross-check result belongs to the previous data -- drop
    # it rather than let it display next to a new/different result set.
    st.session_state.pop("cmp_ms2_result", None)


def _find_saved_result():
    """
    Locate a previously saved candidate table (+ an optional collapsed
    features table), written either by `run_match.py` or by this page itself
    (when a result was too large to stream as a browser download -- see
    `_render_table_with_download`). The path is whatever the Setup page
    points at, falling back to this module's own standard output location.
    Returns None if nothing is there yet.
    """
    restore(SHARED_CANDIDATE_TABLE_KEY, _DEFAULT_CANDIDATE_TABLE_PATH if os.path.isfile(_DEFAULT_CANDIDATE_TABLE_PATH) else "")
    table_path = st.session_state.get(SHARED_CANDIDATE_TABLE_KEY, "") or _DEFAULT_CANDIDATE_TABLE_PATH
    if not os.path.isfile(table_path):
        return None
    features_path = os.path.join(os.path.dirname(table_path), "candidate_features.parquet")
    return {
        "table_path": table_path,
        "table_mtime": os.path.getmtime(table_path),
        "features_path": features_path if os.path.isfile(features_path) else None,
    }


def _load_saved_result(saved):
    import pandas as pd

    candidate_table = pd.read_parquet(saved["table_path"])
    features_for_viz = pd.read_parquet(saved["features_path"]) if saved["features_path"] else None
    _populate_result_session_state(
        candidate_table,
        st.session_state.get("cmp_max_rt_gap", 0.1),
        st.session_state.get("cmp_collapse_features", False),
        features_for_viz=features_for_viz,
    )
    return candidate_table


def _auto_load_saved_result_once():
    """
    Open this page and see the result already there -- no click required.
    Only runs when nothing is loaded *this session* yet (`cmp_candidate_table`
    entirely absent): a fresh "Run match" or an explicit reload from the
    expander below always wins and is never silently overwritten by this.
    """
    if "cmp_candidate_table" in st.session_state:
        return
    saved = _find_saved_result()
    if saved is None:
        return
    _load_saved_result(saved)


def _render_load_saved_result():
    """
    Manually (re)load a saved match result straight from disk into the same
    session_state a fresh "Run match" populates -- `_auto_load_saved_result_once`
    already does this automatically on first visit; this is for reloading
    after the Setup page's path changes, or after the file's been updated
    externally, without a full "Run match".
    """
    saved = _find_saved_result()
    ready = saved is not None
    if ready:
        import datetime

        saved_when = datetime.datetime.fromtimestamp(saved["table_mtime"]).strftime("%Y-%m-%d %H:%M")
        status = f"Possible -- found a result saved {saved_when} (already loaded automatically)."
    else:
        status = f"Not possible yet -- no saved result found at the default location (`{_OUTPUT_DIR}`)."

    if status_button("Reload saved result", "cmp_btn_reload_saved", ready, status):
        with st.spinner("Loading saved result from disk..."):
            candidate_table = _load_saved_result(saved)
        st.success(f"Loaded {len(candidate_table)} raw hits from disk.")
        st.rerun()


# Every filter combination this page can produce ends up saved under
# `output/` with its own distinct filename (`_render_table_with_download`
# now always persists, not only when a result is too large to download --
# see that function's docstring). So "which molecules am I looking at" has a
# direct answer: whichever *file* is currently loaded -- no separate combined
# filter-selection UI needed, just pick from what's actually on disk.
_OUTPUT_VARIANT_LABELS = {
    "candidate_table.parquet": "Raw hits -- every match, no filtering",
    "candidate_table_acetyl_cooccurring.parquet": "Raw hits -- acetyl co-occurring only",
    "candidate_features.parquet": "Collapsed features -- one row per elution event",
    "candidate_features_acetyl_cooccurring.parquet": "Collapsed features -- acetyl co-occurring only",
    "candidate_features_ms2_confident.parquet": "Collapsed features -- MS2 diagnostic-ion confirmed",
}


def _discover_output_variants(folder: str = _OUTPUT_DIR) -> dict:
    """{full path: human label} for every known result variant currently
    present under `folder` -- only what's actually there, nothing implied.
    Defaults to this module's own standard `output/`, but takes any folder
    so other pages (Molecule Explorer, pointed at an arbitrary saved-results
    folder) can reuse the same discovery logic rather than duplicating it."""
    variants = {}
    for filename, label in _OUTPUT_VARIANT_LABELS.items():
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            variants[path] = label
    return variants


def _load_output_variant(path: str, label: str):
    """
    Load one saved variant as the page's active result. "candidate_features*"
    files are already a final, collapsed, possibly-pre-filtered view -- shown
    as-is with the raw-hits view disabled (there's no matching raw-hit table
    to fall back to). "candidate_table*" files are raw hits -- collapsed
    fresh with the current max-RT-gap setting, same as loading the default
    saved result.
    """
    import pandas as pd

    df = pd.read_parquet(path)
    is_features_variant = os.path.basename(path).startswith("candidate_features")

    if is_features_variant:
        st.session_state["cmp_candidate_table"] = df
        st.session_state["cmp_features_for_viz"] = df
        st.session_state["cmp_features_table"] = df
        st.session_state["cmp_features_for_summary"] = df
        st.session_state["cmp_variant_raw_hits_available"] = False
        # This *is* new data (a different variant than whatever was loaded
        # before) -- reset the same way `_populate_result_session_state`
        # does for the other branch, so the save-once tracking in
        # `_render_table_with_download` doesn't inherit stale "already
        # saved" state from a previous, unrelated dataset. Currently inert
        # in practice (this branch always sets `cmp_active_variant_label`,
        # which forces `save_exports=False` downstream regardless), but
        # relying on that instead of resetting directly is a fragile
        # invariant, not a real guarantee.
        st.session_state["cmp_saved_stems"] = set()
    else:
        _populate_result_session_state(
            df, st.session_state.get("cmp_max_rt_gap", 0.1),
            st.session_state.get("cmp_collapse_features", False),
        )
        st.session_state["cmp_variant_raw_hits_available"] = True

    st.session_state["cmp_active_variant_label"] = f"{label} (`{os.path.basename(path)}`)"


def _render_output_variant_browser():
    """
    Pick any saved result variant from `output/` and view it directly -- no
    need to re-run a match (or guess which filter is "currently active")
    just to look at a specific already-computed subset. The button toggles
    the actual selector open rather than loading anything itself (there's a
    follow-up choice to make first), same pattern as Molecule Explorer's
    "Load from a folder or file" -- always "possible" as long as at least
    one variant exists on disk at all.
    """
    variants = _discover_output_variants()
    ready = bool(variants)
    status = (
        f"Possible -- {len(variants)} saved result variant(s) found."
        if ready else f"Not possible yet -- no saved result variants found under `{_OUTPUT_DIR}`."
    )
    if status_button("View a saved result variant", "cmp_btn_variant_toggle", ready, status):
        st.session_state["cmp_show_variant_picker"] = not st.session_state.get(
            "cmp_show_variant_picker", False,
        )

    if ready and st.session_state.get("cmp_show_variant_picker", False):
        st.caption(
            "Every filter combination this page produces is saved as its own file under "
            "`output/` the moment it's computed -- pick one to load and view it directly."
        )
        paths = list(variants.keys())
        restore("cmp_output_variant_choice", paths[0], valid_options=paths)
        choice = st.selectbox(
            "Which result to view", paths,
            format_func=lambda p: variants[p], key="cmp_output_variant_choice",
        )
        persist("cmp_output_variant_choice")
        if st.button("Load this result", key="cmp_load_variant"):
            _load_output_variant(choice, variants[choice])
            st.rerun()


def _run_match(library, file_paths):
    """
    Actually run the match pipeline against `library`/`file_paths`, using
    whatever filter settings are currently persisted (`cmp_*` keys, via
    `restore()` -- not the local variables `render()`'s own Optional filters
    block computes, since this is also called from Molecule Explorer's
    "run whatever's missing" action, which never renders those widgets at
    all). Populates session state and the run-log exactly the same way
    either caller reaches this, so the two paths can't drift out of sync.
    """
    restore("cmp_tolerance", 0.002)
    restore("cmp_unit", "Da", valid_options=["Da", "ppm"])
    restore("cmp_ms_level", "1", valid_options=["1", "2", "All"])
    restore("cmp_min_rel", 0)
    restore("cmp_min_intensity", 50_000.0)
    restore("cmp_min_consecutive_scans", 3)
    restore("cmp_max_rt_gap", 0.1)
    restore("cmp_check_acetyl", False)
    restore("cmp_acetyl_tolerance", 5.0)
    restore("cmp_acetyl_unit", "ppm", valid_options=["ppm", "Da"])
    restore("cmp_acetyl_rt_window", 2.0)
    restore("cmp_collapse_features", False)
    restore("cmp_check_ms2", False)

    tolerance = st.session_state["cmp_tolerance"]
    unit = st.session_state["cmp_unit"]
    ms_level_choice = st.session_state["cmp_ms_level"]
    ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
    min_rel = st.session_state["cmp_min_rel"] / 100.0
    min_intensity = st.session_state["cmp_min_intensity"]
    min_consecutive_scans = st.session_state["cmp_min_consecutive_scans"]
    max_rt_gap = st.session_state["cmp_max_rt_gap"]
    check_acetyl = st.session_state["cmp_check_acetyl"]
    acetyl_tolerance = st.session_state["cmp_acetyl_tolerance"]
    acetyl_unit = st.session_state["cmp_acetyl_unit"]
    acetyl_rt_window = st.session_state["cmp_acetyl_rt_window"]
    collapse_features = st.session_state["cmp_collapse_features"]

    t0 = time.time()
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
    status.empty()
    progress_bar.empty()
    _populate_result_session_state(candidate_table, max_rt_gap, collapse_features)
    append_run(_OUTPUT_DIR, {
        "n_mzml_files": len(file_paths),
        "n_library_rows": len(library),
        "tolerance": tolerance,
        "tolerance_unit": unit,
        "ms_level": ms_level_choice,
        "check_acetyl_cooccurrence": check_acetyl,
        "check_ms2": st.session_state["cmp_check_ms2"],
        "n_raw_hits": len(candidate_table),
        "n_distinct_products": candidate_table["product_inchikey"].nunique() if not candidate_table.empty else 0,
        "duration_seconds": round(time.time() - t0, 1),
    }, filename=_MATCH_RUN_LOG)
    return candidate_table


def render():
    page_header(
        "MS Matching",
        "Match the in-silico suspect library against one or more mzML files.",
    )

    st.session_state.setdefault("match_calibration_locked", False)

    library_path = _resolve_library_path()
    library_missing = not os.path.isfile(library_path)

    # Hard stop, reskinned: with no suspect library at all, only the LOAD
    # sheet renders (via `awaiting_input`) -- PARAMETERS/RUN/ANALYZE never
    # get instantiated, same as the original bare `st.warning(...); return`.
    with st.container(key=mount_key("sheet_match_load", "sheet_match_load_entered")):
        if library_missing:
            awaiting_input(
                "No suspect library found. Build it first with "
                "`insilico_library/build_suspect_library.py`.",
                key="await_match_load",
            )
            return

        mtime = os.path.getmtime(library_path)
        library = _cached_library(library_path, mtime)
        n_fluoro = (library["reaction"] == "fluoroacetyl").sum()
        n_acetyl = (library["reaction"] == "acetyl").sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Library rows", len(library))
        c2.metric("Fluoroacetyl products", n_fluoro)
        c3.metric("Acetyl products", n_acetyl)

        _auto_load_saved_result_once()
        load_col1, load_col2 = st.columns(2)
        with load_col1:
            _render_load_saved_result()
        with load_col2:
            _render_output_variant_browser()

        st.divider()
        st.subheader("Files")
        file_paths = pick_mzml_files(key="comparison_files", default=resolved_shared_mzml_files())

    with st.container(key=mount_key("sheet_match_params", "sheet_match_params_entered")):
        st.caption(
            "CALIBRATION: LOCKED" if st.session_state.get("match_calibration_locked")
            else "CALIBRATION: NOT LOCKED"
        )
        st.subheader("Filters")
        st.caption("Tolerance is required; everything else is optional.")

        restore("cmp_tolerance", 0.002)
        restore("cmp_unit", "Da", valid_options=["Da", "ppm"])
        col1, col2 = st.columns(2)
        tolerance = col1.number_input(
            "Tolerance", min_value=0.0, format="%.4f", key="cmp_tolerance",
            help="How close an observed m/z must be to one of the suspect library's target masses "
                 "to count as a match. Da is a fixed window at every mass; ppm scales with mass "
                 "(wider window for a heavier ion).",
        )
        unit = col2.selectbox("Unit", ["Da", "ppm"], key="cmp_unit")
        persist("cmp_tolerance")
        persist("cmp_unit")

        with st.expander("OPTIONAL FILTERS", key="flap_amber_match_optional"):
            st.html('<div class="sub-header">CORE FILTERS</div>')
            restore("cmp_ms_level", "1", valid_options=["1", "2", "All"])
            restore("cmp_min_rel", 0)
            col3, col4 = st.columns(2)
            ms_level_choice = col3.selectbox(
                "MS level", ["1", "2", "All"], key="cmp_ms_level",
                help="MS1 = the instrument's regular full-scan spectra -- match against this for an "
                     "intact compound's own mass, which is what the suspect library's target masses "
                     "are. MS2 (fragment spectra from a selected precursor) is only meaningful here "
                     "if a target mass happens to also be a known fragment.",
            )
            ms_level = None if ms_level_choice == "All" else int(ms_level_choice)
            min_rel_pct = col4.slider(
                "Min. relative intensity (%)", 0, 100, key="cmp_min_rel",
                help="Relative to each scan's own tallest peak, not one global maximum across the "
                     "file -- the same absolute intensity can pass in a quiet scan and fail in a "
                     "busy one.",
            )
            min_rel = min_rel_pct / 100.0
            persist("cmp_ms_level")
            persist("cmp_min_rel")

            st.html('<div class="sub-header">SCAN &amp; RT</div>')
            restore("cmp_min_intensity", 50_000.0)
            restore("cmp_min_consecutive_scans", 3)
            col_int, col_scans = st.columns(2)
            min_intensity = col_int.number_input(
                "Min. absolute intensity", min_value=0.0, key="cmp_min_intensity",
                help="Raw instrument units. A peak below this is never counted as a hit; 0 disables.",
            )
            min_consecutive_scans = col_scans.number_input(
                "Min. consecutive scans", min_value=1, step=1, key="cmp_min_consecutive_scans",
                help="A hit only counts if it's part of a run of at least this many scans "
                     "in a row (within the RT gap below); 1 disables.",
            )
            persist("cmp_min_intensity")
            persist("cmp_min_consecutive_scans")

            restore("cmp_max_rt_gap", 0.1)
            max_rt_gap = st.number_input(
                "Max. RT gap defining \"consecutive\" (minutes)", min_value=0.0,
                format="%.3f", key="cmp_max_rt_gap",
                help="Used both by the min. consecutive scans filter and by feature collapsing below.",
            )
            persist("cmp_max_rt_gap")

            st.html('<div class="sub-header">ACETYL CO-OCCURRENCE</div>')
            restore("cmp_check_acetyl", False)
            check_acetyl = st.checkbox(
                "Require checking the acetyl analog too (co-occurrence)",
                key="cmp_check_acetyl",
                help="Also looks for the same parent compound's acetyl (non-fluorinated) analog "
                     "nearby -- a fluoroacetylated hit is more credible when its ordinary "
                     "acetylated counterpart is also present, since both would come from the same "
                     "underlying acylation chemistry.",
            )
            persist("cmp_check_acetyl")
            acetyl_tolerance, acetyl_unit, acetyl_rt_window = 5.0, "ppm", 2.0
            if check_acetyl:
                restore("cmp_acetyl_tolerance", 5.0)
                restore("cmp_acetyl_unit", "ppm", valid_options=["ppm", "Da"])
                restore("cmp_acetyl_rt_window", 2.0)
                col5, col6 = st.columns(2)
                acetyl_tolerance = col5.number_input(
                    "Acetyl tolerance", min_value=0.0, format="%.4f", key="cmp_acetyl_tolerance",
                    help="Independent from the main match tolerance above -- the acetyl analog can "
                         "reasonably need a looser or tighter window of its own.",
                )
                acetyl_unit = col6.selectbox("Acetyl unit", ["ppm", "Da"], key="cmp_acetyl_unit")
                acetyl_rt_window = st.number_input(
                    "Acetyl RT window (minutes)", min_value=0.0, format="%.3f", key="cmp_acetyl_rt_window",
                    help="The acetyl analog only counts as co-occurring if found within this many "
                         "minutes of the fluoroacetyl hit's own RT.",
                )
                persist("cmp_acetyl_tolerance")
                persist("cmp_acetyl_unit")
                persist("cmp_acetyl_rt_window")

            st.html('<div class="sub-header">COLLAPSE TO FEATURES</div>')
            restore("cmp_collapse_features", False)
            collapse_features = st.checkbox(
                "Collapse to features (one row per contiguous elution event, instead "
                "of one row per scan)",
                key="cmp_collapse_features",
            )
            persist("cmp_collapse_features")

            st.html('<div class="sub-header">MS2 DIAGNOSTIC-ION FILTER</div>')
            restore("cmp_check_ms2", False)
            check_ms2 = st.checkbox(
                "Also require a diagnostic-ion MS2 scan (targets managed on the mzML Scan Detector page)",
                key="cmp_check_ms2",
            )
            persist("cmp_check_ms2")
            if check_ms2:
                _render_ms2_filter_settings()

        # Lock Calibration: a settings-review gate, checked unconditionally
        # on every render, after the Optional Filters block above (so
        # `.get()` reads this run's just-instantiated widget values) and
        # before the lock button/caption themselves.
        current_snapshot = _calibration_snapshot()
        if st.session_state.get("match_calibration_locked") and \
           st.session_state.get("match_calibration_snapshot") != current_snapshot:
            st.session_state["match_calibration_locked"] = False
            st.session_state.pop("match_calibration_snapshot", None)

        if st.button("LOCK CALIBRATION", key="lock_calibration_btn"):
            st.session_state["match_calibration_locked"] = True
            st.session_state["match_calibration_snapshot"] = current_snapshot
            st.rerun()

        st.caption(
            ":green[Calibration locked for this session.]"
            if st.session_state.get("match_calibration_locked")
            else "Not locked — lock before running to confirm current settings."
        )

    with st.container(key=mount_key("sheet_match_run", "sheet_match_run_entered")):
        run_ready = bool(file_paths)
        run_status = (
            f"Possible -- {len(file_paths)} mzML file(s) selected." if run_ready
            else "Not possible yet -- pick at least one mzML file above."
        )
        if status_button("Run match", "cmp_btn_run_match", run_ready, run_status):
            candidate_table = _run_match(library, file_paths)
            notify_done("comparison_run_match", f"Match finished -- {len(candidate_table)} raw hits across {len(file_paths)} file(s).")

        render_last_notification("comparison_run_match")
        render_run_log(_OUTPUT_DIR, title="Run match history", filename=_MATCH_RUN_LOG)

    # Not gated on `file_paths` -- a result loaded via "Load previously
    # processed data" above should display regardless of whether any mzML
    # file is currently selected for a fresh run.
    candidate_table = st.session_state.get("cmp_candidate_table")
    if candidate_table is None:
        return

    # ANALYZE is a thin, purely additive wrapper around the existing render
    # logic below -- same call order, same `_render_table_with_download`
    # call sites/frequency (its save-once tracking is load-bearing for perf,
    # see that function's own docstring), just indented one level into this
    # sheet's container and broken up with sub-header dividers.
    with st.container(key=mount_key("sheet_match_analyze", "match_analyze_entered")):
        st.html('<div class="sub-header">OVERVIEW</div>')
        if candidate_table.empty:
            st.warning("No matches found with these settings.")
            return

        active_variant_label = st.session_state.get("cmp_active_variant_label")
        # A loaded "candidate_features*" variant is already a final, collapsed
        # table -- it never had (and can't reconstruct) the original raw-hit
        # rows, so anything that needs `candidate_table` in its raw shape
        # (`summarize_candidate_table`, `top_structures_by_formula`'s SMILES/name
        # lookup -- both index straight into it regardless of `features_table`)
        # would `KeyError` on a features-shaped table's columns. Gate on this
        # flag rather than trying to fake a raw-hit shape that was never saved.
        raw_hits_available = st.session_state.get("cmp_variant_raw_hits_available", True)
        if active_variant_label:
            st.info(f"**Currently viewing:** {active_variant_label}")
        else:
            st.info(f"**Currently viewing:** Full match result -- {len(candidate_table)} raw hits, no filter applied.")

        if raw_hits_available:
            st.code(format_summary(summarize_candidate_table(candidate_table)), language=None)
        else:
            st.caption(
                "Raw-hit-level summary isn't available for this saved variant -- it's already a "
                "collapsed features table, which never included the original per-scan rows."
            )

        features_for_viz = st.session_state["cmp_features_for_viz"]
        features_for_summary = st.session_state["cmp_features_for_summary"]

        st.divider()
        st.subheader("Summary")
        if not features_for_viz.empty and features_for_viz["acetyl_cooccurs"].notna().any():
            st.caption(
                f"Based on the {len(features_for_summary)} of {len(features_for_viz)} features with acetyl "
                "co-occurrence -- the final, most-filtered result set, not the raw pre-acetyl-check hits."
            )
        else:
            st.caption(f"Based on all {len(features_for_viz)} features (acetyl co-occurrence wasn't checked).")

        if check_ms2:
            st.html('<div class="sub-header">MS2 DIAGNOSTIC-ION FILTER</div>')
            _render_ms2_confidence_filter(features_for_summary)

        st.html('<div class="sub-header">CHARTS</div>')
        thresholds = tuple(sorted({min_consecutive_scans, 50, 100, 200, 500}))
        breakdown = scan_count_breakdown(candidate_table, thresholds=thresholds, features_table=features_for_summary)
        _render_scan_count_bar(breakdown)

        os.makedirs(_FIGURES_DIR, exist_ok=True)
        plotting.save_scan_count_breakdown_figure(breakdown, os.path.join(_FIGURES_DIR, "scan_count_breakdown.png"))

        if raw_hits_available:
            top_structures = top_structures_by_formula(candidate_table, top_n=10, features_table=features_for_summary)
            st.caption(
                "Top 10 product formulas by total scan evidence (deduplicated -- isomers/salts sharing a formula "
                "count once; a formula can bundle several distinct structures, see \"1 of N structures\" below)."
            )
            grid_image = _render_structure_grid(top_structures)
            plotting.save_top_structures_grid(grid_image, os.path.join(_FIGURES_DIR, "top_structures.png"))
        else:
            st.caption(
                "Structure grid isn't available for this saved variant -- it needs the original raw-hit "
                "table's product SMILES/names, which a collapsed features table never included."
            )

        st.html('<div class="sub-header">RESULTS TABLE</div>')
        features_table = st.session_state.get("cmp_features_table")
        # `save=False` while viewing a specific loaded output/ variant: it's
        # already on disk under its own name, so re-running the "always save"
        # behavior here would overwrite a *different* file's canonical name with
        # this variant's content instead (see `_render_table_with_download`).
        save_exports = not active_variant_label
        if features_table is not None and raw_hits_available:
            view = st.radio(
                "View", ["Features (collapsed)", "Raw hits"], horizontal=True, key="cmp_view",
            )
        elif features_table is not None:
            view = "Features (collapsed)"
        else:
            view = "Raw hits"

        if view == "Features (collapsed)":
            st.metric("Features", len(features_table))
            _render_table_with_download(features_table, "apex_relative_intensity", "candidate_features", save=save_exports)
            _render_acetyl_cooccurring_export(features_table, "apex_relative_intensity", "candidate_features", save=save_exports)
            rt_col, mass_col, intensity_col = "apex_rt_minutes", "product_exact_mass", "apex_intensity"
            feature_map_df = features_table
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Total hits", len(candidate_table))
            c2.metric("Distinct products", candidate_table["product_inchikey"].nunique())
            c3.metric("Distinct parent compounds", candidate_table["parent_inchikey"].nunique())
            if "acetyl_cooccurs" in candidate_table and candidate_table["acetyl_cooccurs"].notna().any():
                st.metric("Hits with acetyl co-occurrence", int(candidate_table["acetyl_cooccurs"].sum()))
            _render_table_with_download(candidate_table, "relative_intensity", "candidate_table", save=save_exports)
            _render_acetyl_cooccurring_export(candidate_table, "relative_intensity", "candidate_table", save=save_exports)
            rt_col, mass_col, intensity_col = "rt_minutes", "matched_mz", "intensity"
            feature_map_df = candidate_table

        st.html('<div class="sub-header">FEATURE MAP</div>')
        st.divider()
        st.subheader("Feature map")
        _render_feature_map(feature_map_df, rt_col, mass_col, intensity_col)
        plotting.save_feature_map_figure(feature_map_df, rt_col, mass_col, intensity_col,
                                          os.path.join(_FIGURES_DIR, "feature_map.png"))
        st.caption(f"Figures saved to `{_FIGURES_DIR}`")


def _render_ms2_filter_settings():
    """
    MS2 diagnostic-ion filter's own settings (precursor/RT/ion tolerance),
    rendered in Optional filters right next to its checkbox -- same placement
    as acetyl co-occurrence's own tolerance/unit/RT-window settings just
    above. Previously these lived inside `_render_ms2_confidence_filter`,
    which is only reachable from the Summary section *after* a match result
    already exists -- unlike acetyl, whose settings were always visible
    before running anything. Split out here since neither these widgets nor
    the "no active target" warning below actually need any match data to
    render; only the real cross-check (needs `features_for_summary`) and its
    `missing_column` check (needs that table's actual columns) still require
    a result to exist, so those two stay in `_render_ms2_confidence_filter`.

    Reads the persisted `diagnostic_targets` list directly (no separate
    "apply" step -- each target's own "use in filter" checkbox there is the
    single source of truth) so the two pages can't drift out of sync.
    `restore()` first since this is that *other* page's own widget-backed
    key -- its session_state entry is cleared whenever the Scan Detector page
    itself isn't the one currently mounted (same reason
    `resolved_shared_mzml_files()` exists); reading `st.session_state`
    directly here would silently come back empty on a fresh visit straight
    to this page, even with saved targets sitting in a loaded preset.
    """
    restore("ms2_precursor_tolerance", 0.5)
    restore("ms2_precursor_unit", "Da", valid_options=["Da", "ppm"])
    restore("ms2_rt_window", 0.5)
    restore("ms2_ion_tolerance", 25.0)
    restore("ms2_ion_unit", "ppm", valid_options=["ppm", "Da"])

    # `format=` on every one of these: without it, Streamlit's default float
    # step/display precision is too coarse to enter a value like 0.002 Da
    # (stuck at 0.01 steps). The main "Tolerance" field above already gets
    # this right (`format="%.4f"`); these three didn't.
    col1, col2, col3 = st.columns(3)
    with col1:
        st.number_input(
            "Precursor tolerance", min_value=0.0, format="%.4f", key="ms2_precursor_tolerance",
            help="How close an MS2 scan's own precursor m/z must be to the feature's observed "
                 "mass to be considered its MS2 scan.",
        )
        st.selectbox("Precursor unit", ["Da", "ppm"], key="ms2_precursor_unit")
    with col2:
        st.number_input(
            "RT window (minutes)", min_value=0.0, format="%.3f", key="ms2_rt_window",
            help="How close (in RT) an MS2 scan must be to the feature's apex to count as "
                 "belonging to it -- DDA precursor selection happens on or very near the "
                 "triggering MS1 scan.",
        )
    with col3:
        st.number_input("Ion tolerance", min_value=0.0, format="%.4f", key="ms2_ion_tolerance")
        st.selectbox("Ion unit", ["ppm", "Da"], key="ms2_ion_unit")
    persist("ms2_precursor_tolerance")
    persist("ms2_precursor_unit")
    persist("ms2_rt_window")
    persist("ms2_ion_tolerance")
    persist("ms2_ion_unit")

    restore("diagnostic_targets", [])
    active_targets = [t for t in st.session_state.get("diagnostic_targets", []) if t["use_in_filter"]]
    if not active_targets:
        st.warning(
            "No diagnostic ion targets are marked \"use in filter\" yet -- add and explore "
            "some on the mzML Scan Detector page first."
        )
    else:
        st.caption("Using: " + ", ".join(f"{t['label']} ({t['target_mz']:.4f})" for t in active_targets))


def _render_ms2_confidence_filter(features_for_summary):
    """
    Does a feature also have an MS2 scan -- matched by precursor mass + RT
    proximity to its own apex, see `ms2_confidence.py` -- containing one of
    the diagnostic ion targets curated on the mzML Scan Detector page? Only
    called at all when the "Also require a diagnostic-ion MS2 scan" checkbox
    in Optional filters is checked -- same discoverability as every other
    filter, rather than being a whole separate section a user has to scroll
    past everything else to find.

    Its own settings and the "no active target" warning are rendered earlier
    in Optional filters (`_render_ms2_filter_settings`, called right after
    the checkbox, before this page even runs a match) -- neither needs a
    match result to exist. Only what genuinely does needs one lives here:
    whether `features_for_summary` actually has the column this filter
    needs, and the real "Run MS2 cross-check" button + its results.

    Reads back the settings `_render_ms2_filter_settings` just wrote to
    session_state earlier in this same rerun (Optional filters always
    renders before Summary in `render()`'s call order) rather than
    re-rendering them.
    """
    st.subheader("MS2 diagnostic-ion filter")
    st.caption(
        "Does each feature also have a nearby MS2 scan containing one of the diagnostic ion "
        "targets managed on the mzML Scan Detector page? Matching *any one* of your active "
        "targets in a scan is enough for that scan to count."
    )

    precursor_tolerance = st.session_state["ms2_precursor_tolerance"]
    precursor_unit = st.session_state["ms2_precursor_unit"]
    rt_window = st.session_state["ms2_rt_window"]
    ion_tolerance = st.session_state["ms2_ion_tolerance"]
    ion_unit = st.session_state["ms2_ion_unit"]

    missing_column = "apex_matched_mz" not in features_for_summary.columns
    if missing_column:
        st.warning(
            "This result was collapsed to features before the MS2 cross-check existed, so it's "
            "missing the column it needs (the feature's own observed mass). Re-run the match "
            "(or reload it without a saved `candidate_features.parquet`, which forces a fresh "
            "collapse) to pick it up."
        )

    all_targets = st.session_state.get("diagnostic_targets", [])
    active_targets = [t for t in all_targets if t["use_in_filter"]]

    if st.button("Run MS2 cross-check", type="primary", disabled=missing_column or not active_targets):
        t0 = time.time()
        targets = [DiagnosticTarget(label=t["label"], target_mz=t["target_mz"]) for t in active_targets]
        status = st.empty()
        with st.spinner("Cross-checking MS2 spectra..."):
            result = find_ms2_support(
                features_for_summary, targets,
                precursor_tolerance=precursor_tolerance, precursor_unit=precursor_unit,
                rt_window_minutes=rt_window, ion_tolerance=ion_tolerance, ion_unit=ion_unit,
                progress_callback=status.text,
            )
        status.empty()
        st.session_state["cmp_ms2_result"] = result
        # A fresh cross-check is new data -- make sure its own save-once
        # tracking (see `_render_table_with_download`) treats it as such,
        # not as "already saved" from a previous run's settings.
        st.session_state.setdefault("cmp_saved_stems", set()).discard("candidate_features_ms2_confident")
        n_confident_now = int(result["has_diagnostic_ms2"].sum())
        append_run(_OUTPUT_DIR, {
            "n_features_checked": len(result),
            "n_diagnostic_targets_used": len(targets),
            "diagnostic_targets": ", ".join(t.label for t in targets),
            "precursor_tolerance": precursor_tolerance,
            "precursor_unit": precursor_unit,
            "rt_window_minutes": rt_window,
            "n_with_ms2": int((result["n_ms2_associated"] > 0).sum()),
            "n_high_confidence": n_confident_now,
            "duration_seconds": round(time.time() - t0, 1),
        }, filename=_MS2_RUN_LOG)
        notify_done("comparison_ms2_check", f"MS2 cross-check finished -- {n_confident_now}/{len(result)} features confirmed.")

    render_last_notification("comparison_ms2_check")
    render_run_log(_OUTPUT_DIR, title="MS2 cross-check history", filename=_MS2_RUN_LOG)

    ms2_result = st.session_state.get("cmp_ms2_result")
    if ms2_result is None:
        return

    n_with_ms2 = int((ms2_result["n_ms2_associated"] > 0).sum())
    n_confident = int(ms2_result["has_diagnostic_ms2"].sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Features checked", len(ms2_result))
    c2.metric("Have a nearby MS2 scan", n_with_ms2)
    c3.metric("High-confidence (diagnostic ion found)", n_confident)

    confident = ms2_result[ms2_result["has_diagnostic_ms2"]].sort_values(
        "n_ms2_with_diagnostic_ion", ascending=False,
    )
    if confident.empty:
        st.caption("No features had a diagnostic ion in an associated MS2 scan with these settings.")
    else:
        _render_table_with_download(confident, "n_ms2_with_diagnostic_ion", "candidate_features_ms2_confident")
