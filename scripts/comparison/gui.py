"""comparison/gui.py — Streamlit page (placeholder, not built yet)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.ui import coming_soon  # noqa: E402


def render():
    coming_soon(
        "MS Matching",
        "The underlying logic is built (matcher.py efficiently matches a large "
        "target-mass list against an mzML file; run_match.py runs it over the "
        "suspect library and writes a candidate table) — this page for running "
        "it interactively, and the additional filters (RT window, "
        "fluoro/parent/acetyl co-occurrence, isotope pattern), are not built yet.",
    )
