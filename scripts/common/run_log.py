"""
common/run_log.py — a small per-module run history: one row appended to a
plain CSV each time a pipeline action (Normalize, Build suspect library, Run
match, MS2 cross-check, ...) actually finishes, so past runs -- what was
processed, how many came out the other end, how long it took -- can be
reviewed without re-running anything or re-opening whatever large table that
run produced.

Deliberately NOT that run's own output (the parquet/CSV each module already
writes is still the real result) -- this is only a lightweight summary row.
Also deliberately NOT computed live on every page render: an earlier version
of the In-silico Library page recomputed one of these numbers (how many
compounds have a primary amine) from scratch on every rerun just to display
it, which took minutes on a real library -- recording it once, when a run
actually happens, is both cheaper and the more honest answer to "what
happened", since it reflects that specific run rather than whatever the
source file currently contains.

One small CSV per module (`<module>/output/run_log.csv`), not one shared
file across the whole app -- each module's log naturally has its own set of
columns (a match run's columns have nothing to do with a normalize run's),
and every action within one module still gets a shared history since column
sets are unioned automatically (see `append_run`).
"""
from __future__ import annotations

import os
import time

_DEFAULT_FILENAME = "run_log.csv"


def append_run(output_dir: str, row: dict, filename: str = _DEFAULT_FILENAME) -> str:
    """
    Append one run's summary to `<output_dir>/<filename>`, creating it (with
    headers) if it doesn't exist yet. `row` should be flat (str/int/float/bool
    values); a `timestamp` column is added automatically if `row` doesn't
    already supply one.

    Reads the whole (small -- one row per past run) file, concatenates, and
    rewrites it, rather than appending a raw CSV line: a later run's row can
    introduce a column an earlier run's row didn't have (e.g. a new filter),
    and a naive line-append would silently misalign every column after it
    instead of giving the new column its own place with blanks for older runs.
    """
    import pandas as pd

    row = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **row}
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    if os.path.isfile(path):
        existing = pd.read_csv(path)
        combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    else:
        combined = pd.DataFrame([row])
    combined.to_csv(path, index=False)
    return path


def read_run_log(output_dir: str, filename: str = _DEFAULT_FILENAME):
    """This module's run history, newest run first, or `None` if nothing has
    ever run yet."""
    import pandas as pd

    path = os.path.join(output_dir, filename)
    if not os.path.isfile(path):
        return None
    return pd.read_csv(path).iloc[::-1].reset_index(drop=True)


def render_run_log(output_dir: str, title: str = "Run history", filename: str = _DEFAULT_FILENAME):
    """Streamlit: a small sortable table of this module's past runs, newest
    first. Shows nothing at all if it hasn't run yet -- no empty section
    cluttering a fresh clone or a page nobody's used."""
    import streamlit as st

    log = read_run_log(output_dir, filename)
    if log is None or log.empty:
        return

    with st.expander(f"{title} ({len(log)} run{'s' if len(log) != 1 else ''})"):
        st.dataframe(log, width="stretch")
