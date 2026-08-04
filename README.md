# DUF62_fluoro_project

Research code and analysis workflows for a project on **DUF62-family enzymes**,
**fluorinases**, and **fluorinated compounds** (IOCB Prague, Pluskal lab).

> **Status: early-stage / work in progress.** Updated frequently as the project
> develops. Citation and license information are **to be determined** (see below).

## Repository layout

This is a **public, code-only** repository. Raw instrument data, literature
PDFs, and presentations live one level up in the private project folder and are
**not** part of this repository.

```
DUF62_fluoro_project/
├── scripts/              # main.py (Streamlit GUI) + downstream modules — see scripts/README.md
├── notebooks/            # Jupyter notebooks (exploration, figures)
├── .streamlit/config.toml # dark theme
├── requirements.txt
├── environment.yml       # conda alternative (recommended: rdkit is most reliable this way)
├── CHANGELOG.md          # notable changes, newest first
├── README.md             # this file
└── .gitignore
```

## Installation

Recommended (conda — `rdkit` is most reliable this way; `pyopenms` is pip-only
either way, conda-forge doesn't have it, but `environment.yml` handles that
for you via a nested `pip:` entry):
```bash
conda env create -f environment.yml
conda activate duf62-fluoro
```

pip alternative:
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
python -m pip install -r requirements.txt
```

## Running the GUI

```bash
streamlit run scripts/main.py
```
See `scripts/README.md` for the module architecture and running individual
modules from the CLI without the GUI.

## Your own data

The GUI's file pickers take full paths, entered manually (one per line for
mzML files) -- point them at wherever your files actually live; a library
of candidate compounds (any CSV/Parquet with a structure column) works the
same way. See the app's Setup page, which every other page's own picker
seeds its default selection from.

## Citation

_To be added._

## License

_To be added._

## Authors

Erik Bouchal¹ · _(additional authors TBD)_

¹ Institute of Organic Chemistry and Biochemistry of the Czech Academy of
Sciences (IOCB Prague), Prague, Czechia
