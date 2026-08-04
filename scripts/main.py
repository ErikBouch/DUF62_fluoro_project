"""
main.py — DUF62 fluoro project GUI (Streamlit).

The single entry point. It only handles navigation, layout, and theming;
each downstream module (setup, mzml_tools, insilico_library, comparison,
explorer) owns its own page in its `gui.py`, calling back into that module's
own logic file. main.py never contains science logic itself -- including the
7-stage pipeline stepper below: main.py only *assembles* that status from
each module's own pure, side-effect-free status function (e.g.
`setup.gui.acquire_data_status`), never computes it itself.

Navigation is a hand-rolled top nav bar + `st.session_state["page"]` +
if/elif dispatch, not `st.navigation` -- ported from the "Blueprint
Brutalist" visual-design round (see `design/07.2_blueprint_brutalist.py` in
the parent project folder; not part of this repo). Exactly one
`PAGE_RENDERERS[...]()` call runs per rerun either way, so this keeps
`st.navigation`'s real perf win over `st.tabs` (which runs every tab's code
on every rerun, confirmed directly in an earlier version of this app).

`st.navigation`'s specific *page-unmount* behaviour (clearing a widget's own
keyed session_state the moment its page stops being the active one) is what
originally made `common.ui.restore`/`persist` necessary. Plain if/elif
dispatch doesn't have that specific trigger -- a widget not instantiated on a
given rerun simply keeps whatever value it already had in session_state, for
the life of the session -- but `restore`/`persist` are kept exactly as they
were anyway: `save_preset`/`load_preset` still depend on the same persistent
store, and every existing `restore()` call is a no-op once its key exists, so
nothing about this swap requires touching any of the five module `gui.py`
files' own use of them.

The stepper's render is deliberately deferred until *after* page dispatch
(filled into a `nav_slot` reserved before dispatch) -- see the comment at the
fill site below for the bug this fixes.

Run with:
    streamlit run main.py
"""
import os
import sys

import streamlit as st

st.set_page_config(page_title="DUF62 Fluoro Project", page_icon="📐", layout="wide")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.ui import (  # noqa: E402
    NAV_PAGES, PALETTE_MODES, PALETTE_SWATCH_LETTER, PIPELINE_ORDER,
    STAGE_GLYPH, STAGE_LABELS, STAGE_TARGET_PAGE, STATIC_CSS,
    build_dynamic_css, build_palette_css, build_sheet_tab_css, compute_current_stage,
    preset_controls, run_boot_gate,
)

import setup.gui as setup_gui  # noqa: E402
import mzml_tools.gui as scan_gui  # noqa: E402
import insilico_library.gui as library_gui  # noqa: E402
import comparison.gui as match_gui  # noqa: E402
import explorer.gui as explorer_gui  # noqa: E402

st.session_state.setdefault("booted", False)
st.session_state.setdefault("boot_start", None)
st.session_state.setdefault("page", "setup")
st.session_state.setdefault("palette_mode", "blue")

run_boot_gate()

PAGE_RENDERERS = {
    "setup": setup_gui.render,
    "scan": scan_gui.render,
    "library": library_gui.render,
    "match": match_gui.render,
    "explorer": explorer_gui.render,
}


def _compute_real_stage_status() -> dict:
    """Assemble the 7-stage pipeline status from each module's own pure
    status function -- see this file's own docstring for why main.py never
    computes any of these itself."""
    return {
        "acquire_data": setup_gui.acquire_data_status(),
        "link_library": setup_gui.link_library_status(),
        "lib_normalize": library_gui.normalize_status(),
        "lib_build_suspects": library_gui.build_status(),
        "calibrate_match": match_gui.calibrate_status(),
        "execute_match": match_gui.execute_match_status(),
        "review_output": explorer_gui.review_output_status(),
    }


# Two existing, load-bearing CSS fixes, merged into the one combined
# stylesheet below rather than issued as separate st.html() calls: hiding
# Streamlit's fixed, non-configurable "running" icon (its data-testid is
# internal, not a public API -- may need updating on a Streamlit upgrade),
# and widening the sidebar's drag-resize range to a percentage instead of
# Streamlit's fixed default px range (deliberately not setting `width`
# itself here -- that fights Streamlit's own drag handler, which sets
# `width` as an inline style on every drag move).
_EXTRA_CSS = (
    "[data-testid='stStatusWidgetRunningIcon'] { display: none; }"
    "[data-testid='stSidebar'] { min-width: 10% !important; max-width: 20% !important; }"
)

with st.sidebar:
    preset_controls()

st.html('<div class="blueprint-title"><span class="name">DUF62 FLUORO PROJECT</span></div>')

with st.container(key="palette_selector"):
    with st.container(key="palette_swatch_row"):
        swatch_cols = st.columns(4)
        for col, mode_key in zip(swatch_cols, PALETTE_MODES):
            with col:
                if st.button(PALETTE_SWATCH_LETTER[mode_key], key=f"palette_{mode_key}", width="content"):
                    st.session_state.palette_mode = mode_key
                    st.rerun()

# Reserved slot -- filled further below, AFTER page dispatch, so the
# stepper's colors reflect anything the page body just mutated in this same
# run (see the fix note at the fill site for why this matters).
nav_slot = st.container()
st.html("<hr/>")

PAGE_RENDERERS[st.session_state.page]()  # completion flags may get mutated here

# Bug this fixes (carried over from the design round): the stepper used to
# be computed AND rendered before page dispatch. That only self-corrected
# because every RUN-style button happened to pair its flag mutation with an
# immediate st.rerun() -- a fragile convention, not a structural guarantee,
# and real code here is *not* uniformly disciplined about that (e.g. mzML
# Scan Detector's "Find scans" button falls through to the rest of the
# script instead of rerunning). Recomputing fresh here, using anything the
# page body above just mutated, then filling the reserved nav_slot, means
# the stepper reflects this run's own changes immediately regardless of
# whether that page happened to call st.rerun().
_stage_status = _compute_real_stage_status()
_current_stage = compute_current_stage(_stage_status)
with nav_slot:
    st.html(
        "<style>"
        + STATIC_CSS
        + build_palette_css(st.session_state.get("palette_mode", "blue"))
        + build_sheet_tab_css()
        + build_dynamic_css(st.session_state.page, _stage_status, _current_stage)
        + _EXTRA_CSS
        + "</style>"
    )

    nav_cols = st.columns(len(NAV_PAGES))
    for col, (page_key, label) in zip(nav_cols, NAV_PAGES):
        with col:
            if st.button(label, key=f"nav_{page_key}", width="stretch"):
                st.session_state.page = page_key
                st.rerun()

    st.html('<div class="stepper-wrap"></div>')
    with st.container(key="stepper_row"):
        step_cols = st.columns(len(PIPELINE_ORDER))
        for col, stage_key in zip(step_cols, PIPELINE_ORDER):
            with col:
                status = _stage_status[stage_key]
                glyph = STAGE_GLYPH[status]
                label = f"{glyph}\n{STAGE_LABELS[stage_key]}"
                if st.button(label, key=f"step_{stage_key}", width="stretch"):
                    st.session_state.page = STAGE_TARGET_PAGE[stage_key]
                    st.rerun()
