"""
explorer/gallery.py — pagination and sort-order helpers for the Molecule
Explorer page. Pure logic (no Streamlit import) so paging/sorting stays
testable independent of the GUI.
"""
from __future__ import annotations

# label -> (column, ascending), applied to comparison.matcher.structures_by_formula's output
SORT_OPTIONS = {
    "Most scans": ("total_scans", False),
    "Most isomers": ("n_isomers", False),
    "Formula (A-Z)": ("product_formula", True),
    "Exact mass (low to high)": ("product_exact_mass", True),
}
DEFAULT_SORT = "Most scans"
PAGE_SIZE = 24


def sort_structures(df, sort_label: str):
    """Sort `df` (structures_by_formula's output) by one of SORT_OPTIONS."""
    column, ascending = SORT_OPTIONS.get(sort_label, SORT_OPTIONS[DEFAULT_SORT])
    return df.sort_values(column, ascending=ascending).reset_index(drop=True)


def paginate(df, n_loaded: int):
    """The first `n_loaded` rows -- call again with a larger `n_loaded` for
    "load more" pagination rather than a page index, so rows already on
    screen never shift position."""
    return df.head(n_loaded)
