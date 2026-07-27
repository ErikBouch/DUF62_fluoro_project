"""insilico_library/gui.py — Streamlit page (placeholder, not built yet)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import coming_soon  # noqa: E402


def render():
    coming_soon(
        "In-silico Library",
        "The underlying logic is built (db_loader.py merges natural-product databases "
        "into one deduplicated structure table; acylation.py adds acetyl/fluoroacetyl "
        "groups to primary amines and computes formula, monoisotopic mass, and expected "
        "adducts) — this page for running it interactively is not built yet.",
    )
