"""
explorer/gui.py — Streamlit page: a "store shelf" gallery of the compound
structures surviving the last MS Matching run (final-filtered: the acetyl-
co-occurring subset, when that check was run -- same convention as MS
Matching's own Summary section).

GUI only: all aggregation logic lives in comparison/matcher.py, pagination/
sort logic in explorer/gallery.py.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comparison import plotting  # noqa: E402
from comparison.matcher import isomers_for_formula, structures_by_formula  # noqa: E402
from common.ui import persist, resolved_shared_mzml_files, restore  # noqa: E402
from explorer.gallery import DEFAULT_SORT, PAGE_SIZE, SORT_OPTIONS, paginate, sort_structures  # noqa: E402

# Reused directly from comparison/gui.py rather than duplicated: Molecule
# Explorer's whole gallery reads the same `cmp_*` session_state keys MS
# Matching's own page populates, so its own "load data" options call the
# exact same loading/running logic MS Matching uses -- keeping both pages
# in sync automatically instead of risking two paths that quietly diverge.
# These names are underscore-prefixed in their home module (comparison's own
# internal helpers, not a public API) -- imported anyway since the two
# modules are tightly coupled by design (same session_state schema), and
# duplicating this logic here would be the real drift risk.
from comparison.gui import (  # noqa: E402
    _OUTPUT_DIR as _COMPARISON_OUTPUT_DIR, _OUTPUT_VARIANT_LABELS,
    _cached_library, _discover_output_variants, _find_saved_result, _load_output_variant,
    _load_saved_result, _resolve_library_path, _run_match,
)

_CARD_CSS = """
<style>
.mol-card {
    position: relative;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 10px;
    margin-bottom: 4px;
    text-align: center;
    background: #1e293b;
}
.mol-card img { max-width: 100%; height: auto; }
.mol-card-formula { font-weight: 600; font-size: 1.0rem; margin-top: 4px; color: #e2e8f0; }
.mol-card-stats { font-size: 0.85rem; color: #94a3b8; }
.mol-card-hover {
    display: none;
    position: absolute;
    top: 6px; left: 6px; right: 6px;
    background: rgba(15, 23, 42, 0.97);
    color: #e2e8f0;
    padding: 10px;
    border-radius: 8px;
    z-index: 20;
    text-align: left;
    font-size: 0.8rem;
    line-height: 1.5;
    border: 1px solid #2dd4bf;
}
.mol-card:hover .mol-card-hover { display: block; }
</style>
"""


def _clean_str(value) -> str | None:
    """`parent_name` (and similar looked-up fields) are NaN, not None, for a
    missing value in a pandas float/object column -- and NaN is truthy in
    plain Python, so `value or default` silently lets it through instead of
    falling back. Use this instead of a bare truthiness check."""
    return value if isinstance(value, str) else None


@st.cache_data(show_spinner=False)
def _cached_mol_image(smiles: str | None, size=(220, 180)):
    """Cached wrapper around `plotting.mol_image_data_uri` -- Streamlit
    reruns this whole page top-to-bottom on *any* widget interaction
    anywhere (a sort change, a "load more" click, typing in an unrelated
    box), so without caching, every already-rendered card's RDKit image gets
    redrawn from scratch every single time, not just newly-shown ones. Keyed
    on the SMILES itself, so a given structure is only ever rendered once per
    server process, however many times/pages/dialogs it shows up in."""
    return plotting.mol_image_data_uri(smiles, size)


@st.cache_data(show_spinner=False)
def _cached_isomer_grid_image(_isomers_df, formula: str, run_id: int):
    """Cached, keyed on `formula` + `run_id` (the current match result's
    identity, i.e. `id(candidate_table)`) rather than on `_isomers_df` itself
    -- the leading underscore tells Streamlit not to hash that DataFrame for
    the cache key. `run_id` matters: without it, a *different* match run
    that happens to produce a same-named formula (e.g. re-running against
    another file) would incorrectly reuse a stale image from the old run."""
    return plotting.build_isomer_grid_image(_isomers_df)


@st.dialog("Isomers", width="large")
def _isomers_dialog(formula, candidate_table, features_table):
    """One composed grid image (RDKit + PIL, see `plotting.build_isomer_grid_image`)
    rather than N separate per-isomer widgets or N base64 `<img>` tags packed
    into one giant HTML string -- a formula can pool dozens of isomers (one
    had 65), and both of those approaches turned out far more expensive to
    transmit/render than the actual RDKit drawing (65 renders cost ~1s in
    isolation; the per-widget version of this dialog took ~26s, and even the
    single-big-HTML-string version was still slow to parse)."""
    st.subheader(formula)
    isomers = isomers_for_formula(formula, candidate_table, features_table=features_table)
    st.caption(f"{len(isomers)} distinct structures share this formula, ranked by scan evidence.")

    error = plotting.structure_rendering_error()
    if error:
        st.warning(f"Structure rendering isn't available (`rdkit.Chem.Draw` failed to import: {error}).")
    else:
        image = _cached_isomer_grid_image(isomers, formula, id(candidate_table))
        if image is not None:
            st.image(image, width="stretch")

    display_cols = ["product_inchikey", "parent_name", "total_scans", "n_features",
                     "product_exact_mass", "acetyl_cooccurs"]
    st.dataframe(isomers[display_cols], width="stretch", hide_index=True)


def _render_card(row):
    uri = _cached_mol_image(row.product_smiles)
    img_tag = f'<img src="{uri}" />' if uri else "<div>(no structure)</div>"
    mass = f"{row.product_exact_mass:.4f}" if row.product_exact_mass is not None else "?"
    acetyl_line = "Acetyl co-occurs: Yes" if row.acetyl_cooccurs else "Acetyl co-occurs: No"
    parent_name = _clean_str(row.parent_name) or "(unknown)"
    st.markdown(
        f"""
        <div class="mol-card">
            <div class="mol-card-hover">
                <b>{row.product_formula}</b><br>
                Exact mass: {mass}<br>
                Reaction: {row.reaction}<br>
                Parent: {parent_name}<br>
                {acetyl_line}
            </div>
            {img_tag}
            <div class="mol-card-formula">{row.product_formula}</div>
            <div class="mol-card-stats">{row.total_scans} scans &middot; {row.n_isomers} isomer(s)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if row.n_isomers > 1:
        if st.button(f"Explore {row.n_isomers} isomers", key=f"explore_{row.product_formula}", width="stretch"):
            _isomers_dialog(row.product_formula, st.session_state["cmp_candidate_table"],
                             st.session_state["cmp_features_for_summary"])


def _render_show_current_results():
    """
    Option 1: the already-computed default result -- same resolution MS
    Matching's own auto-load uses (`SHARED_CANDIDATE_TABLE_KEY`, falling back
    to `comparison/output/candidate_table.parquet`), so pointing the Setup
    page at a different saved result changes what this offers too.

    Button first, status line right under it -- computed on every render
    with no click needed, so "is this even possible right now" is always the
    immediate answer, not something you find out only after pressing.
    """
    saved = _find_saved_result()
    ready = saved is not None
    if st.button("Show current results", key="explorer_btn_default", disabled=not ready):
        with st.spinner("Loading saved result from disk..."):
            _load_saved_result(saved)
        st.rerun()

    if ready:
        import datetime

        saved_when = datetime.datetime.fromtimestamp(saved["table_mtime"]).strftime("%Y-%m-%d %H:%M")
        st.caption(f"Possible -- found `{saved['table_path']}` (saved {saved_when}).")
    else:
        st.caption(f"Not possible yet -- no saved result found at the default location (`{_COMPARISON_OUTPUT_DIR}`).")


def _render_load_from_path_form():
    """The actual folder/file picker, only ever shown once the button above
    is pressed (see `_render_load_from_path`) -- not rendered unconditionally
    on the page. A folder may hold several filter-variant files at once (raw
    hits, acetyl-co-occurring subset, collapsed features, MS2-confident,
    ...) -- offer the same "which result to view" selector MS Matching's own
    output-variant browser already has, rather than assuming one specific
    filename. A single file is loaded directly."""
    restore("explorer_custom_path", "")
    path = st.text_input(
        "Folder or file path", key="explorer_custom_path",
        help="A folder is scanned for known result files (candidate_table*/candidate_features*); "
             "a specific file is loaded directly.",
    )
    persist("explorer_custom_path")
    if not path:
        return

    if os.path.isdir(path):
        variants = _discover_output_variants(path)
        if not variants:
            st.warning(f"No known result files found in `{path}`.")
            return
        variant_paths = list(variants.keys())
        restore("explorer_variant_choice", variant_paths[0], valid_options=variant_paths)
        choice = st.selectbox(
            "Which result to view", variant_paths,
            format_func=lambda p: variants[p], key="explorer_variant_choice",
        )
        persist("explorer_variant_choice")
        if st.button("Load this result", key="explorer_load_variant"):
            _load_output_variant(choice, variants[choice])
            st.rerun()
    elif os.path.isfile(path):
        label = _OUTPUT_VARIANT_LABELS.get(os.path.basename(path), "Custom result file")
        if st.button(f"Load `{os.path.basename(path)}`", key="explorer_load_file"):
            _load_output_variant(path, label)
            st.rerun()
    else:
        st.warning(f"No file or folder found at `{path}`.")


def _render_load_from_path():
    """
    Option 2: any folder or file the user points at. Always "possible" (it
    just needs a path, not any precondition) -- so unlike options 1 and 3,
    the button here doesn't perform the load itself; it toggles whether the
    actual picker (`_render_load_from_path_form`) is shown at all, since that
    picker needs its own follow-up input/selection and would otherwise be a
    text box and dropdown sitting on the page permanently, which is exactly
    the "everything visible at once" clutter this redesign is fixing.
    """
    show = st.session_state.get("explorer_show_custom_path_form", False)
    if st.button("Load from a folder or file", key="explorer_btn_custom_toggle"):
        show = not show
        st.session_state["explorer_show_custom_path_form"] = show
    st.caption("Always possible -- point at any folder or a specific result file.")
    if show:
        _render_load_from_path_form()


def _render_run_missing():
    """
    Option 3: run whatever's missing, then show the result. Checks
    preconditions in order and only runs the step that can actually run
    without further user input (a match, against the existing suspect
    library + selected mzML files) -- Normalize needs the user's own column
    mapping, so a missing suspect library is reported, not silently
    guessed. Button first (disabled when not possible), status line right
    under it explaining why, same pattern as the other two options.
    """
    library_path = _resolve_library_path()
    file_paths = resolved_shared_mzml_files()

    missing = []
    if not os.path.isfile(library_path):
        missing.append("no suspect library found (build one on In-silico Library)")
    if not file_paths:
        missing.append("no mzML files selected (pick some on Setup)")
    ready = not missing

    if st.button("Run match now", key="explorer_btn_run", disabled=not ready, type="primary" if ready else "secondary"):
        library = _cached_library(library_path, os.path.getmtime(library_path))
        with st.spinner("Running match..."):
            candidate_table = _run_match(library, file_paths)
        st.success(f"Match finished -- {len(candidate_table)} raw hits across {len(file_paths)} file(s).")
        st.rerun()

    if ready:
        st.caption(
            f"Possible -- suspect library + {len(file_paths)} mzML file(s) found. Runs with whatever "
            "filter settings are currently set on the MS Matching page (or their defaults)."
        )
    else:
        st.caption("Not possible yet -- " + "; ".join(missing) + ".")


def _render_data_loader():
    st.info("No data loaded yet.")

    _render_show_current_results()
    st.divider()
    _render_load_from_path()
    st.divider()
    _render_run_missing()


def render():
    st.title("Molecule Explorer")
    st.caption("Browse the compound structures surviving your last MS Matching run.")

    candidate_table = st.session_state.get("cmp_candidate_table")
    features_table = st.session_state.get("cmp_features_for_summary")
    if candidate_table is None or features_table is None or candidate_table.empty:
        _render_data_loader()
        return

    cache_key = (id(candidate_table), id(features_table))
    if st.session_state.get("_explorer_cache_key") != cache_key:
        st.session_state["_explorer_all_structures"] = structures_by_formula(
            candidate_table, features_table=features_table,
        )
        st.session_state["_explorer_cache_key"] = cache_key
        st.session_state["explorer_n_loaded"] = PAGE_SIZE
    all_structures = st.session_state["_explorer_all_structures"]

    if all_structures.empty:
        st.warning("No structures to show.")
        return

    error = plotting.structure_rendering_error()
    if error:
        st.warning(
            "Structure rendering isn't available in this Python environment "
            f"(`rdkit.Chem.Draw` failed to import: {error}). Formula/scan/isomer "
            "info below still works; this usually means rdkit needs "
            "reinstalling in this environment."
        )

    col1, col2 = st.columns([2, 1])
    col1.caption(f"{len(all_structures)} distinct product formulas.")
    restore("explorer_sort", DEFAULT_SORT, valid_options=list(SORT_OPTIONS))
    sort_label = col2.selectbox("Sort by", list(SORT_OPTIONS), key="explorer_sort")
    persist("explorer_sort")

    sorted_structures = sort_structures(all_structures, sort_label)
    n_loaded = st.session_state.get("explorer_n_loaded", PAGE_SIZE)
    page = paginate(sorted_structures, n_loaded)

    st.markdown(_CARD_CSS, unsafe_allow_html=True)

    rows = list(page.itertuples())
    for i in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[i:i + 3]):
            with col:
                _render_card(row)

    if n_loaded < len(sorted_structures):
        if st.button(f"Load more ({min(PAGE_SIZE, len(sorted_structures) - n_loaded)} of "
                     f"{len(sorted_structures) - n_loaded} remaining)"):
            st.session_state["explorer_n_loaded"] = n_loaded + PAGE_SIZE
            st.rerun()
