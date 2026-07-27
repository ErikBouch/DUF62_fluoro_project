"""
main.py — DUF62 fluoro project GUI (Streamlit).

The single entry point. It only handles navigation and layout; each downstream
module (mzml_tools, insilico_library, comparison) owns its own page in its
`gui.py`, calling back into that module's own logic file. main.py never
contains science logic itself.

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
    st.sidebar.title("DUF62 Fluoro Project")
    choice = st.sidebar.radio("Module", list(PAGES))
    st.sidebar.divider()
    st.sidebar.caption(
        "Finding naturally fluoroacetylated plant metabolites via an in-silico "
        "suspect library matched against LC-HRMS data."
    )
    _render(PAGES[choice])


if __name__ == "__main__":
    main()
