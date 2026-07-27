"""
main.py — DUF62 fluoro project GUI (Streamlit).

The single entry point. It only handles navigation and layout; each downstream
module (mzml_tools, insilico_library, comparison) owns its own page in its
`gui.py`, calling back into that module's own logic file. main.py never
contains science logic itself.

Navigation is tabs, not a sidebar radio: every module stays mounted and its
widget state stays intact regardless of which tab is currently visible --
switching tabs is a client-side toggle, not a script rerun, so settings in one
module never disappear because another tab was open for a while.

Run with:
    streamlit run main.py
"""
import streamlit as st

st.set_page_config(page_title="DUF62 Fluoro Project", layout="wide")

PAGES = {
    "mzML Scan Detector": "mzml_tools.gui",
    "In-silico Library": "insilico_library.gui",
    "MS Matching": "comparison.gui",
}


def _render(module_path: str):
    import importlib

    module = importlib.import_module(module_path)
    module.render()


def main():
    st.title("DUF62 Fluoro Project")
    st.caption(
        "Finding naturally fluoroacetylated plant metabolites via an in-silico "
        "suspect library matched against LC-HRMS data."
    )
    for tab, module_path in zip(st.tabs(list(PAGES)), PAGES.values()):
        with tab:
            _render(module_path)


if __name__ == "__main__":
    main()
