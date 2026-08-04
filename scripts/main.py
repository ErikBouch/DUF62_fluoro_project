"""
main.py — DUF62 fluoro project GUI (Streamlit).

The single entry point. It only handles navigation and layout; each downstream
module (mzml_tools, insilico_library, comparison, explorer) owns its own page
in its `gui.py`, calling back into that module's own logic file. main.py
never contains science logic itself.

Navigation is `st.navigation` (a sidebar page list), not `st.tabs`: tabs
execute every tab's code on every single rerun, no matter which tab is
visible on screen -- confirmed directly (a heavy MS Matching page kept
re-rendering on clicks made entirely inside the unrelated Molecule Explorer
tab, since Streamlit only hides an inactive tab's DOM output, it doesn't
skip running its code). `st.navigation` only runs the current page's code,
which is the real speed win -- at the cost of clearing a widget's own keyed
session_state whenever its page is unmounted (confirmed directly too: a
checkbox's value came back `None` after navigating away and back). Every
module works around that via `common.ui.restore`/`persist`, which mirror a
widget's value into a plain session_state entry (under `_persistent_settings`)
that `st.navigation` does *not* clear (also confirmed directly: an ordinary
session_state assignment, not tied to any widget's `key=`, survived
navigating away and back intact). That same store is what `preset_controls`
saves/loads as a named JSON file under `configs/` (gitignored).

Run with:
    streamlit run main.py
"""
import os
import sys

import streamlit as st

st.set_page_config(page_title="DUF62 Fluoro Project", layout="wide")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.ui import preset_controls  # noqa: E402


def _setup_page():
    import setup.gui as gui

    # The app-level title/caption only makes sense once, on the landing
    # page -- every other page already has its own `page_header()` title,
    # so repeating this banner above it on all five pages was pure
    # redundancy.
    st.title("DUF62 Fluoro Project")
    st.caption(
        "Finding naturally fluoroacetylated plant metabolites via an in-silico "
        "suspect library matched against LC-HRMS data."
    )
    gui.render()


def _mzml_page():
    import mzml_tools.gui as gui

    gui.render()


def _insilico_page():
    import insilico_library.gui as gui

    gui.render()


def _comparison_page():
    import comparison.gui as gui

    gui.render()


def _explorer_page():
    import explorer.gui as gui

    gui.render()


# Streamlit's top-right "running" indicator has a fixed, non-configurable
# icon (an animated running-man SVG) -- there's no config/theme/API option
# to change it. This hides just that icon via its internal data-testid,
# leaving the "Stop" button next to it (genuinely useful for a long-running
# match) untouched. Depends on Streamlit's current internal markup, not a
# public API -- may need updating if a Streamlit upgrade renames it.
st.html("<style>[data-testid='stStatusWidgetRunningIcon'] { display: none; }</style>")

# No native `st.set_page_config`/theme option controls the sidebar's pixel
# width (only open/collapsed state) -- CSS is the only lever. Streamlit's own
# default range is a *fixed*, non-relative `min-width: 200px; max-width:
# 600px` -- overridden here with a percentage range instead, so the sidebar
# actually scales with screen width, and drag-resizing still works anywhere
# inside that range. Deliberately NOT setting `width` itself (an earlier
# version did, pinned to an exact px value): that fought every drag attempt
# -- Streamlit's own resize handler sets `width` as an inline style on each
# drag move, and a `width: ... !important` rule here would silently snap it
# straight back, making the sidebar look frozen/unmovable. Leaving `width`
# alone lets Streamlit's own current/dragged value stand; only the outer
# min/max range is widened.
st.html(
    "<style>[data-testid='stSidebar'] { min-width: 10% !important; "
    "max-width: 20% !important; }</style>"
)

with st.sidebar:
    preset_controls()

pg = st.navigation([
    st.Page(_setup_page, title="Setup"),
    st.Page(_mzml_page, title="mzML Scan Detector"),
    st.Page(_insilico_page, title="In-silico Library"),
    st.Page(_comparison_page, title="MS Matching"),
    st.Page(_explorer_page, title="Molecule Explorer"),
])
pg.run()
