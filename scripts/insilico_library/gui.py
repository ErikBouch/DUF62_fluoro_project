"""
insilico_library/gui.py — Streamlit page for turning a user-supplied library
of candidate compounds into the acetyl/fluoroacetyl suspect library used for
matching.

GUI only: all science logic lives in db_loader.py / acylation.py /
build_suspect_library.py so it stays testable and usable from the CLI without
Streamlit installed.

Two stages, matching the two on-disk artifacts under output/ (both computed
results, not input data):
1. Normalize -- read the raw library (any table with a structure column,
   mapped by the user below), compute inchikey/formula for every row via
   RDKit (never trusted from the source file -- see db_loader.py's
   `load_user_table`) -> output/normalized_library.parquet. Deliberately
   NOT computed/stored here: has_primary_amine and exact_mass -- neither is
   something a source database supplies, so (like db_loader.py's own merged
   table) this stays a plain structure table; both are computed fresh, right
   where they're actually used, below.
2. Build -- compute has_primary_amine for that normalized table, run the
   acylation reactions over the compounds that have one -> output/
   suspect_library.parquet (+ multidegree).
"""
from __future__ import annotations

import os
import sys
import time

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.run_log import append_run, render_run_log  # noqa: E402
from common.ui import (  # noqa: E402
    SHARED_LIBRARY_PATH_KEY, SHARED_SUSPECT_LIBRARY_KEY,
    notify_done, page_header, persist, render_last_notification, restore,
)

_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
_NORMALIZED_PATH = os.path.join(_OUTPUT_DIR, "normalized_library.parquet")
_SUSPECT_MONO_PATH = os.path.join(_OUTPUT_DIR, "suspect_library.parquet")
_SUSPECT_MULTI_PATH = os.path.join(_OUTPUT_DIR, "suspect_library_multidegree.parquet")
# Separate run-log files per action (not one shared log for both) so each
# keeps its own natural set of columns and its own history table, shown right
# under that action's own section rather than one mixed table further down.
_NORMALIZE_RUN_LOG = "normalize_run_log.csv"
_BUILD_RUN_LOG = "build_run_log.csv"


@st.cache_data(show_spinner=False)
def _cached_parquet(path: str, mtime: float):
    import pandas as pd

    return pd.read_parquet(path)




@st.cache_data(show_spinner=False)
def _cached_raw_table(path: str, mtime: float):
    import pandas as pd

    if path.lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_parquet(path)


def _guess_column(columns: list[str], target_name: str, none_option: str) -> str:
    """Exact (case-insensitive) column-name match only -- e.g. never lets "inchikey" match a guess for "inchi"."""
    lower = {c.lower(): c for c in columns}
    return lower.get(target_name, none_option)


def _render_source_and_mapping():
    """
    Stage 1's input: the raw library path (set on the Setup page) and its
    column mapping. Returns (raw_df, inchi_col, smiles_col, name_col,
    organism_col, source_label), or None if there's nothing usable yet.
    """
    # `SHARED_LIBRARY_PATH_KEY` is a widget key on the Setup page -- its own
    # session_state entry is cleared when that page unmounts, same as any
    # other widget. `restore` pulls the persisted value back in (this page
    # never instantiates that widget itself, so there's nothing to `persist`
    # back afterward -- reading only).
    restore(SHARED_LIBRARY_PATH_KEY, "")
    library_path = st.session_state.get(SHARED_LIBRARY_PATH_KEY, "")
    if not library_path or not os.path.isfile(library_path):
        st.info("Set a library file path on the Setup page first.")
        return None

    raw = _cached_raw_table(library_path, os.path.getmtime(library_path))
    st.caption(f"Loaded `{library_path}` — {len(raw)} rows, {len(raw.columns)} columns.")
    st.dataframe(raw.head(10), width="stretch")

    columns = list(raw.columns)
    none_option = "(none)"
    column_options = [none_option] + columns

    st.subheader("Column mapping")
    st.caption(
        "Map either an InChI column, a SMILES column, or both -- at least one is required. If "
        "both are mapped, InChI is tried first per row, falling back to SMILES only for rows "
        "where the InChI value is missing or fails to parse. Formula and InChIKey are always "
        "computed from whichever structure is found and don't need mapping, even if your table "
        "already has them. There's no InChIKey column to map: it's a one-way hash, so a row that "
        "only has one gives RDKit no structure to recover -- InChI or SMILES is the only valid "
        "structure input."
    )
    col1, col2 = st.columns(2)
    restore("lib_inchi_col", _guess_column(columns, "inchi", none_option), valid_options=column_options)
    inchi_col = col1.selectbox("InChI column", column_options, key="lib_inchi_col")
    persist("lib_inchi_col")

    restore("lib_smiles_col", _guess_column(columns, "smiles", none_option), valid_options=column_options)
    smiles_col = col2.selectbox("SMILES column", column_options, key="lib_smiles_col")
    persist("lib_smiles_col")

    if inchi_col == none_option and smiles_col == none_option:
        st.warning("Map at least one of InChI or SMILES to continue.")
        return None

    col3, col4 = st.columns(2)
    name_options = [none_option] + columns
    restore("lib_name_col", none_option, valid_options=name_options)
    name_col = col3.selectbox("Name column (optional)", name_options, key="lib_name_col")
    persist("lib_name_col")

    organism_options = [none_option] + columns
    restore("lib_organism_col", none_option, valid_options=organism_options)
    organism_col = col4.selectbox("Organism/source column (optional)", organism_options, key="lib_organism_col")
    persist("lib_organism_col")

    source_label = os.path.splitext(os.path.basename(library_path))[0]

    return (
        raw,
        None if inchi_col == none_option else inchi_col,
        None if smiles_col == none_option else smiles_col,
        None if name_col == none_option else name_col,
        None if organism_col == none_option else organism_col,
        source_label,
    )


_NORMALIZED_REQUIRED_COLS = {"inchi", "source_db"}


def _render_normalized_stats():
    if not os.path.isfile(_NORMALIZED_PATH):
        st.info("Not normalized yet.")
        return None

    normalized = _cached_parquet(_NORMALIZED_PATH, os.path.getmtime(_NORMALIZED_PATH))
    missing = _NORMALIZED_REQUIRED_COLS - set(normalized.columns)
    if missing:
        st.error(
            f"`{os.path.basename(_NORMALIZED_PATH)}` is missing expected column(s) "
            f"({', '.join(sorted(missing))}) -- most likely left over from a normalize run "
            "that parsed 0 rows (e.g. the wrong structure column was picked). Delete it and "
            "normalize again above."
        )
        if st.button("Delete this file"):
            os.remove(_NORMALIZED_PATH)
            st.cache_data.clear()
            st.rerun()
        return None

    # No reactive-functional-group count shown here on purpose: it used to be
    # recomputed live on every page render (a real RDKit pass over every row,
    # minutes on a real library, just to display a number), and it hardcoded
    # "primary amine" as if that were the only functional group this pipeline
    # would ever react on. That count now lives in the Build step's own run
    # history below instead -- recorded once, for the run that actually used
    # it, under whichever functional group that run targeted.
    c1, c2 = st.columns(2)
    c1.metric("Unique structures", len(normalized))
    c2.metric("Sources", normalized["source_db"].str.split(",").explode().nunique())
    return normalized


def _resolve_suspect_library_path() -> str:
    """
    The suspect library shown below: whatever's set on the Setup page (a
    result from a previous run, possibly saved somewhere else), falling back
    to this module's own standard build location -- so pointing Setup at a
    different file shows *that* file's stats here too, not just whatever
    happens to sit at the fixed default path.
    """
    restore(SHARED_SUSPECT_LIBRARY_KEY, _SUSPECT_MONO_PATH if os.path.isfile(_SUSPECT_MONO_PATH) else "")
    return st.session_state.get(SHARED_SUSPECT_LIBRARY_KEY, "") or _SUSPECT_MONO_PATH


def _render_suspect_library_stats():
    path = _resolve_suspect_library_path()
    if not os.path.isfile(path):
        st.info("Suspect library not built yet.")
        return
    mono = _cached_parquet(path, os.path.getmtime(path))
    if "reaction" not in mono.columns:
        st.error(f"`{os.path.basename(path)}` doesn't look like a built suspect library (no `reaction` column).")
        return
    if path != _SUSPECT_MONO_PATH:
        st.caption(f"Showing `{path}` (set on the Setup page).")
    c1, c2, c3 = st.columns(3)
    c1.metric("Product rows", len(mono))
    c2.metric("Fluoroacetyl", int((mono["reaction"] == "fluoroacetyl").sum()))
    c3.metric("Acetyl", int((mono["reaction"] == "acetyl").sum()))
    st.dataframe(mono.head(50), width="stretch")


def render():
    page_header(
        "In-silico Library",
        "Turn a library of candidate compounds into the acetyl/fluoroacetyl suspect library "
        "used for matching.",
    )

    mapping = _render_source_and_mapping()

    st.divider()
    st.subheader("1. Normalize")
    st.caption(
        "Computes inchikey/formula for every row via RDKit, deduplicated by structure (InChIKey)."
    )
    if mapping is not None and st.button("Normalize library", type="primary"):
        raw, inchi_col, smiles_col, name_col, organism_col, source_label = mapping
        from insilico_library.db_loader import load_user_table, merge_rows

        t0 = time.time()
        status = st.empty()
        progress_bar = st.progress(0.0)
        status.text(f"Parsing {len(raw)} rows...")
        rows, stats = load_user_table(
            raw, inchi_col=inchi_col, smiles_col=smiles_col, name_col=name_col, organism_col=organism_col,
            source_label=source_label or "user", progress_callback=status.text,
            progress_fraction_callback=progress_bar.progress,
        )
        status.empty()
        progress_bar.empty()

        if stats.n_parsed_ok == 0:
            mapped = " / ".join(f"{label} = '{col}'" for label, col in (("InChI", inchi_col), ("SMILES", smiles_col)) if col)
            st.error(
                f"0 of {stats.n_records_seen} rows parsed as a valid structure from {mapped}. "
                f"Double check that column actually holds InChI or SMILES text."
            )
        else:
            status.text("Deduplicating by structure...")
            normalized = merge_rows([rows])
            os.makedirs(_OUTPUT_DIR, exist_ok=True)
            normalized.to_parquet(_NORMALIZED_PATH, index=False)
            status.empty()

            st.cache_data.clear()
            append_run(_OUTPUT_DIR, {
                "source": source_label or "user",
                "n_records_seen": stats.n_records_seen,
                "n_parsed_ok": stats.n_parsed_ok,
                "n_parse_failed": stats.n_parse_failed,
                "n_unique_structures": len(normalized),
                "duration_seconds": round(time.time() - t0, 1),
            }, filename=_NORMALIZE_RUN_LOG)
            notify_done(
                "insilico_normalize",
                f"Parsed {stats.n_parsed_ok}/{stats.n_records_seen} rows ok "
                f"({stats.n_parse_failed} failed) -> {len(normalized)} unique structures.",
            )

    render_last_notification("insilico_normalize")
    normalized = _render_normalized_stats()
    render_run_log(_OUTPUT_DIR, title="Normalize run history", filename=_NORMALIZE_RUN_LOG)

    st.divider()
    st.subheader("2. Build suspect library")
    st.caption("Runs the acetyl/fluoroacetyl acylation reactions over every normalized, primary-amine-bearing compound.")

    if normalized is not None and st.button("Build suspect library", type="primary"):
        from insilico_library.acylation import REACTIVE_GROUP_LABEL
        from insilico_library.build_suspect_library import build_library
        from insilico_library.db_loader import compute_exact_mass_series, compute_primary_amine_flags

        t0 = time.time()
        with st.spinner("Finding primary-amine-bearing structures..."):
            primary_amine_df = normalized[compute_primary_amine_flags(normalized["inchi"])].reset_index(drop=True)
            primary_amine_df["exact_mass"] = compute_exact_mass_series(primary_amine_df["inchi"])
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
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        mono_df.to_parquet(_SUSPECT_MONO_PATH, index=False)
        multi_df.to_parquet(_SUSPECT_MULTI_PATH, index=False)

        st.cache_data.clear()
        append_run(_OUTPUT_DIR, {
            "reactive_functional_group": REACTIVE_GROUP_LABEL,
            "n_normalized_compounds": len(normalized),
            "n_reactive_compounds": len(primary_amine_df),
            "n_processed": n_processed,
            "n_product_rows": len(mono_df),
            "n_multisite_compounds": n_multisite,
            "n_multidegree_rows": len(multi_df),
            "n_errors": n_errors,
            "duration_seconds": round(time.time() - t0, 1),
        }, filename=_BUILD_RUN_LOG)
        notify_done(
            "insilico_build",
            f"{n_processed} compounds processed, {len(mono_df)} product rows "
            f"({n_multisite} with >1 reactive site), {n_errors} errors.",
        )

    render_last_notification("insilico_build")
    _render_suspect_library_stats()
    render_run_log(_OUTPUT_DIR, title="Build run history", filename=_BUILD_RUN_LOG)
