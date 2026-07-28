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
from explorer.gallery import DEFAULT_SORT, PAGE_SIZE, SORT_OPTIONS, paginate, sort_structures  # noqa: E402

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


def render():
    st.title("Molecule Explorer")
    st.caption("Browse the compound structures surviving your last MS Matching run.")

    candidate_table = st.session_state.get("cmp_candidate_table")
    features_table = st.session_state.get("cmp_features_for_summary")
    if candidate_table is None or features_table is None or candidate_table.empty:
        st.info("Run a match in the MS Matching tab first.")
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
    sort_label = col2.selectbox("Sort by", list(SORT_OPTIONS), index=list(SORT_OPTIONS).index(DEFAULT_SORT), key="explorer_sort")

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
