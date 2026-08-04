"""
common/ui.py — small shared helpers for the Streamlit GUI (not science logic).

mzML file discovery (`find_mzml_files`, looking under `<repo root>/data/mzml/`
-- a real, repo-relative convention any clone can use, gitignored, empty by
default) is used directly by the CLI scripts (`comparison/run_match.py`,
`insilico_library/benchmark_aa.py`). The GUI's own file picker
(`pick_mzml_files`) does NOT use it -- it used to offer a multiselect over
discovered files alongside a separate custom-paths box, but that discovery
half went unused in practice (real data lives outside the repo, in a private
folder, so every real session just typed/pasted custom paths anyway) and
having two ways to do the same thing was confusing rather than convenient.
The GUI picker is now just the one text area.
"""
from __future__ import annotations

import json
import os

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../DUF62_fluoro_project/scripts
REPO_ROOT = os.path.dirname(_SCRIPTS_DIR)  # .../DUF62_fluoro_project
PROJECT_ROOT = os.path.dirname(REPO_ROOT)  # .../DUF_62 (private data hub, not the repo)
DEFAULT_HRMS_DIR = os.path.join(REPO_ROOT, "data", "mzml")
_CONFIGS_DIR = os.path.join(REPO_ROOT, "configs")  # gitignored: local run settings, not code
_SETTINGS_STORE_KEY = "_persistent_settings"

# Set once on the Setup page; every other page seeds its own picker's default
# selection from these (see `pick_mzml_files`'s `default` param) rather than
# sharing one literal widget key -- so picking a file for e.g. one-off
# exploration on the Scan Detector page doesn't reach into MS Matching's own
# selection, but a fresh visit to either starts from the same place.
SHARED_MZML_KEY = "shared_mzml_files"
SHARED_LIBRARY_PATH_KEY = "shared_library_path"

# Paths to already-computed results -- also set on the Setup page, defaulting
# to each module's own standard output location when a file is already there.
# Downstream pages read these (via `restore`, since they're this same kind of
# widget key) to auto-populate from disk on first visit, instead of requiring
# an explicit "load" click every session -- opening each module should just
# show the results already computed.
SHARED_SUSPECT_LIBRARY_KEY = "shared_suspect_library_path"
SHARED_CANDIDATE_TABLE_KEY = "shared_candidate_table_path"


def find_mzml_files(root: str = DEFAULT_HRMS_DIR) -> list[tuple[str, str]]:
    """
    Discover .mzML files under `root`. Returns a sorted list of
    (label, full_path) tuples; label is the path relative to `root`, using
    forward slashes, e.g. "some_subfolder/file.mzML".
    Returns [] if `root` doesn't exist (e.g. a fresh clone without private data).
    """
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.lower().endswith(".mzml"):
                full = os.path.join(dirpath, fname)
                label = os.path.relpath(full, root).replace(os.sep, "/")
                found.append((label, full))
    return sorted(found, key=lambda pair: pair[0])


def pick_mzml_files(key: str = "mzml_paths", default: list[str] | None = None) -> list[str]:
    """
    File picker: one text area of full file paths, one per line. Used to
    also offer a multiselect over files auto-discovered under `data/mzml/`
    -- dropped since it went unused in practice (real data lives outside the
    repo, in a private folder, so every real session just typed/pasted
    custom paths anyway) and having two ways to do the same thing was
    confusing, not convenient. `find_mzml_files`/`DEFAULT_HRMS_DIR` still
    exist for the CLI scripts that use them directly.

    `default`: full paths to pre-fill the *first* time this widget is shown
    (e.g. the Setup page's shared file selection, so every page starts from
    the same files without being locked to it) -- pass `None`/omit to start
    empty. Only applies once; after that this picker's own text is tracked
    independently (`restore`/`persist`), so editing it here never reaches
    back into the shared selection or any other page.

    Returns a list of full paths, one per non-blank line.
    """
    import streamlit as st

    restore(key, "\n".join(default or []))
    text = st.text_area("mzML file paths (one per line)", key=key)
    persist(key)
    return [line.strip() for line in text.splitlines() if line.strip()]


def resolved_shared_mzml_files() -> list[str]:
    """
    The Setup page's shared mzML selection as full paths.

    Reads the persisted settings store directly rather than
    `st.session_state`, so it works no matter which page is currently active
    -- the sidebar's "load preset" control is reachable from every page, not
    just Setup's own, and the store is what a loaded preset immediately
    updates regardless of which page happens to be mounted at the time.
    """
    text = _settings_store().get(SHARED_MZML_KEY, "")
    if isinstance(text, list):
        # A preset saved before the discovered-files multiselect was
        # dropped stores this key as a list of discovery *labels*, not full
        # paths -- meaningless now that discovery is gone from the picker.
        # Tolerate the shape so loading an old preset doesn't crash; it
        # simply resolves to no files, same as if nothing were ever set.
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _settings_store() -> dict:
    import streamlit as st

    return st.session_state.setdefault(_SETTINGS_STORE_KEY, {})


def restore(key: str, default, valid_options=None):
    """
    Seed `st.session_state[key]` from the persistent settings store, but only
    if it's currently missing -- true on first load, and also right after
    `st.navigation` unmounts and remounts a page (it clears every widget's own
    keyed session_state, unlike a plain session_state entry). A no-op on
    every other rerun, since the widget's own session_state entry already
    exists by then and always takes precedence over a widget's `value=`/
    `index=` argument.

    `valid_options`, for a selectbox/multiselect-backed key: a restored value
    that isn't among the widget's *current* options would otherwise crash the
    widget outright (Streamlit raises rather than ignoring it) -- e.g. a
    saved preset naming a file that no longer exists, or a fresh mzML file
    discovery. When given, a stored scalar not in `valid_options` falls back
    to `default`; a stored list is filtered down to just the still-valid entries.

    Call once before the widget; pair with `persist(key)` right after it.
    """
    import streamlit as st

    if key in st.session_state:
        return
    value = _settings_store().get(key, default)
    if valid_options is not None:
        if isinstance(value, list):
            value = [v for v in value if v in valid_options]
        elif value not in valid_options:
            value = default
    st.session_state[key] = value


def persist(key: str):
    """Write a widget's current value back into the persistent settings
    store, so it survives the page unmount `restore()` guards against, and
    so it can be captured by `save_preset`."""
    import streamlit as st

    _settings_store()[key] = st.session_state[key]


def list_presets() -> list[str]:
    """Names of saved settings presets (JSON files under `configs/`), most
    recently saved first."""
    if not os.path.isdir(_CONFIGS_DIR):
        return []
    names = [f[:-5] for f in os.listdir(_CONFIGS_DIR) if f.endswith(".json")]
    return sorted(names, key=lambda n: os.path.getmtime(os.path.join(_CONFIGS_DIR, f"{n}.json")), reverse=True)


def save_preset(name: str):
    """Write every currently `restore`/`persist`-tracked setting, across every
    module, to one named JSON file -- a preset is a full working setup, not a
    per-module snapshot, so switching presets can restore an entire session
    at once."""
    os.makedirs(_CONFIGS_DIR, exist_ok=True)
    with open(os.path.join(_CONFIGS_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(_settings_store(), f, indent=2, sort_keys=True)


def load_preset(name: str):
    """
    Load a named preset into the persistent settings store, and clear every
    currently mounted widget's own session_state entry for the keys it
    covers -- a mounted widget's own session_state value always wins over
    the store (see `restore`), so without this a loaded preset would sit in
    the store unseen until the next full page unmount/remount.

    Merges onto the existing store rather than replacing it wholesale: a
    preset saved before some setting existed (a new filter, the Setup page's
    shared file/library selection, ...) doesn't mention that key at all, and
    a `store.clear()` here would wipe it out from under whatever's currently
    set, even though the preset was never "aware" of it to begin with -- a
    real bug hit in practice (loading an older preset erased the just-picked
    Setup page selection). Only the keys a preset actually names are ever
    touched.
    """
    import streamlit as st

    with open(os.path.join(_CONFIGS_DIR, f"{name}.json"), encoding="utf-8") as f:
        loaded = json.load(f)
    _settings_store().update(loaded)
    for key in loaded:
        st.session_state.pop(key, None)


def preset_controls():
    """Save/load UI for the persistent settings store -- one shared control
    for the whole app (not per-module), since a preset captures a full
    working setup (every module's filters/selections at once)."""
    import streamlit as st

    with st.expander("Save/load a settings preset"):
        presets = list_presets()
        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("Save current settings as", key="_preset_save_name")
            if st.button("Save preset", key="_preset_save_btn") and new_name.strip():
                save_preset(new_name.strip())
                st.success(f"Saved preset '{new_name.strip()}'.")
        with col2:
            if presets:
                chosen = st.selectbox("Load a preset", presets, key="_preset_load_choice")
                if st.button("Load preset", key="_preset_load_btn"):
                    load_preset(chosen)
                    st.success(f"Loaded preset '{chosen}'.")
                    st.rerun()
            else:
                st.caption("No saved presets yet.")


def notify_done(key: str, message: str):
    """
    Signal a long-running task's completion two ways -- a transient
    `st.toast` (eye-catching, but auto-dismisses after a few seconds, so easy
    to miss if not looking at that exact moment) *and* a persistent message
    stored under `key`, shown by `render_last_notification(key)` wherever
    that task's page calls it. The persistent half survives page reruns and
    switching away and back -- it stays until the *next* time this same key
    finishes, not just the one render right after the button click (a plain
    `st.success()` right before `st.rerun()` never actually gets seen, since
    the rerun discards it before the browser renders that frame -- this is
    why `st.rerun()` should never immediately follow a one-time message).
    """
    import streamlit as st

    st.toast(message, icon="✅")
    st.session_state[f"_last_notification_{key}"] = message


def render_last_notification(key: str):
    """Companion to `notify_done` -- the persistent half of the completion
    signal, if this task has finished at least once this session."""
    import streamlit as st

    message = st.session_state.get(f"_last_notification_{key}")
    if message:
        st.success(f"Last completed: {message}")


def page_header(title: str, subtitle: str | None = None):
    """Consistent page title + optional subtitle, used at the top of each module page."""
    import streamlit as st

    st.title(title)
    if subtitle:
        st.caption(subtitle)


def coming_soon(title: str, description: str):
    """Placeholder page for a module that isn't built yet."""
    import streamlit as st

    page_header(title, "Coming soon")
    st.info(description)


# Possible right now (green) vs. not possible yet (yellow) -- the app's
# standard way of showing an action's current status at a glance, first
# built for Molecule Explorer's data loader and generalized here once it
# proved out, to reuse across every module rather than reimplementing the
# same colors/CSS per page.
STATUS_GREEN = "#22c55e"
STATUS_YELLOW = "#eab308"


def status_button(label: str, key: str, ready: bool, status_text: str) -> bool:
    """
    A big button, color-coded by whether the action it performs is possible
    right now (green) or not (yellow), with the reason directly underneath --
    computed and shown on every render, not just after clicking.

    Colors are CSS keyed on `key` (Streamlit generates a `.st-key-<key>`
    class for exactly this purpose -- the only supported hook for a second
    accent color beyond the theme's own `type="primary"/"secondary"`, which
    doesn't offer more than one). `!important` on the disabled-state rule
    too: Streamlit's own disabled-button styling (reduced opacity/grayed
    border) would otherwise still show through and wash out the yellow.

    Deliberately does not touch `width`/`min-width`/`max-width` on anything
    outside its own button -- a past version of a *different* CSS override
    in this app (the sidebar's) pinned a dimension with `!important` and
    ended up fighting Streamlit's own resize handling; button dimensions
    have no such conflict; sizing here is unaffected by that lesson, but the
    caution against overriding more than the one property actually needed
    still applies to future callers.
    """
    import streamlit as st

    color = STATUS_GREEN if ready else STATUS_YELLOW
    st.html(f"""
        <style>
        .st-key-{key} button {{
            min-height: 4.5rem;
            font-size: 1.05rem;
            font-weight: 600;
            border: 2px solid {color} !important;
            color: {color} !important;
        }}
        .st-key-{key} button:disabled {{
            border: 2px solid {color} !important;
            color: {color} !important;
            opacity: 0.85;
        }}
        </style>
    """)
    clicked = st.button(label, key=key, disabled=not ready, width="stretch")
    st.caption(status_text)
    return clicked
