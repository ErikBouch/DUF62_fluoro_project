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
import time

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


# ---------------------------------------------------------------------------
# Visual system -- top nav, 7-stage pipeline stepper, sheets, palette, boot.
#
# Ported from the "Blueprint Brutalist" design round (13 Streamlit mockups,
# narrowed to one, refined twice -- see `design/07.2_blueprint_brutalist.py`
# in the parent project folder, kept as the reference copy; not part of this
# repo). This module owns every piece that's genuinely shared across all
# five pages (CSS, the stepper's rendering, the palette selector, the boot
# sequence); each page's own PIPELINE stage-status function stays in that
# page's own gui.py (e.g. `setup.gui.acquire_data_status`) -- main.py
# assembles the 7-entry dict from those, never computing pipeline status
# itself, same "no science logic in the nav layer" principle as everywhere
# else in this app.
# ---------------------------------------------------------------------------

STAGE_LABELS = {
    "acquire_data": "ACQUIRE DATA",
    "link_library": "LINK LIBRARY",
    "lib_normalize": "NORMALIZE",
    "lib_build_suspects": "BUILD SUSPECT LIBRARY",
    "calibrate_match": "CALIBRATE MATCH",
    "execute_match": "EXECUTE MATCH",
    "review_output": "REVIEW OUTPUT",
}
PIPELINE_ORDER = list(STAGE_LABELS.keys())
STAGE_TARGET_PAGE = {
    "acquire_data": "setup",
    "link_library": "setup",
    "lib_normalize": "library",
    "lib_build_suspects": "library",
    "calibrate_match": "match",
    "execute_match": "match",
    "review_output": "explorer",
}
STAGE_GLYPH = {"todo": "○", "done": "✓", "failed": "✕"}
# Single source of truth for status -> color, shared by build_dynamic_css()
# and setup/gui.py's status ledger so the two can never drift apart.
STATUS_COLOR_VAR = {"todo": "var(--yellow)", "done": "var(--green)", "failed": "var(--red)"}

NAV_PAGES = [
    ("setup", "SETUP"),
    ("scan", "SCAN"),
    ("library", "LIBRARY"),
    ("match", "MATCH"),
    ("explorer", "EXPLORER"),
]

# key -> (sheet number, title) -- registered statically so the CSS tab-label
# rules can be generated once, up front, independent of which page/workflow
# happens to be showing this run. In-silico Library gets 5 entries because
# its "load existing" and "generate new" workflows are two different sheet
# sets, not one -- both are registered even though only one shows at a time
# (harmless: a CSS rule targeting a class that isn't on the page simply
# never matches anything).
SHEET_TITLES = {
    "sheet_setup_files": (1, "FILES"),
    "sheet_setup_library": (2, "LIBRARY"),
    "sheet_setup_results": (3, "RESULTS"),
    "sheet_setup_status": (4, "STATUS"),
    "sheet_scan_load": (1, "LOAD"),
    "sheet_scan_params": (2, "PARAMETERS"),
    "sheet_scan_run": (3, "RUN"),
    "sheet_scan_analyze": (4, "ANALYZE"),
    "sheet_lib_load_normalized": (1, "NORMALIZED LIBRARY"),
    "sheet_lib_load_suspect": (2, "SUSPECT LIBRARY"),
    "sheet_lib_gen_source": (1, "SOURCE"),
    "sheet_lib_gen_normalize": (2, "NORMALIZE"),
    "sheet_lib_gen_build": (3, "BUILD SUSPECT LIBRARY"),
    "sheet_match_load": (1, "LOAD"),
    "sheet_match_params": (2, "PARAMETERS"),
    "sheet_match_run": (3, "RUN"),
    "sheet_match_analyze": (4, "ANALYZE"),
}

# Four color modes for the top-left "INK" selector. Hex values only -- never
# referenced directly by a page except through the CSS vars build_palette_css()
# emits, and the one Python-side exception where a native chart needs a
# literal color (a page should read PALETTE_HEX[mode]["ink"] itself for that,
# same pattern as the design mockup's Scan Detector chart).
PALETTE_HEX = {
    "blue": {
        "bg": "#0d1b2e", "panel": "#122438", "ink": "#7ec8e3",
        "ink_bright": "#a9dcef", "ink_dim": "#3a5a72",
        "text": "#e8f4f8", "text_dim": "#3a4a5c",
        "grid": "rgba(126,200,227,0.055)",
    },
    "green": {
        "bg": "#0c1f16", "panel": "#123423", "ink": "#5ab4a8",
        "ink_bright": "#8fd9cd", "ink_dim": "#2f5c46",
        "text": "#e8f8ef", "text_dim": "#375445",
        "grid": "rgba(90,180,168,0.055)",
    },
    "white": {
        "bg": "#f4f1e8", "panel": "#ffffff", "ink": "#1a4d7a",
        "ink_bright": "#0d2f4d", "ink_dim": "#9fb3c4",
        "text": "#16232f", "text_dim": "#6b7a86",
        "grid": "rgba(26,77,122,0.09)",
    },
    "black": {
        "bg": "#050505", "panel": "#131313", "ink": "#d8d8d8",
        "ink_bright": "#f2f2f2", "ink_dim": "#4a4a4a",
        "text": "#ededed", "text_dim": "#6e6e6e",
        "grid": "rgba(216,216,216,0.05)",
    },
}
PALETTE_SWATCH_LETTER = {"blue": "B", "green": "G", "white": "W", "black": "K"}
PALETTE_MODES = ["blue", "green", "white", "black"]

BOOT_DURATION = 2.4


def mount_key(base: str, flag_key: str) -> str:
    """Container key that carries a one-time CSS entrance animation.

    The first time this is called after `flag_key` becomes true it returns a
    key ending in `__animated` (given a `sheetEnter` animation by STATIC_CSS).
    Every later call -- including on unrelated reruns of the same page --
    returns a key ending in `__static` so the animation never replays.
    """
    import streamlit as st

    already_entered = st.session_state.get(flag_key, False)
    variant = "static" if already_entered else "animated"
    if not already_entered:
        st.session_state[flag_key] = True
    return f"{base}__{variant}"


def awaiting_input(message: str, key: str) -> None:
    """A dashed placeholder box for a sheet whose prerequisite hasn't been
    met yet -- used identically whether that sheet is reached in normal
    pipeline order or by jumping straight to it via the stepper; there is no
    separate "you skipped ahead" state anywhere in this app."""
    import streamlit as st

    with st.container(key=key):
        st.markdown("##### ┄┄┄ AWAITING INPUT ┄┄┄")
        st.caption(message)


def compute_current_stage(status: dict) -> str | None:
    """The first stage in pipeline order that's still `"todo"` -- both
    `"done"` and `"failed"` stages are skipped (a failed stage isn't
    "current," it's just failed and still clickable to retry). Pure and
    generic: takes any {stage_key: status} dict shaped like PIPELINE_ORDER."""
    for stage in PIPELINE_ORDER:
        if status.get(stage) == "todo":
            return stage
    return None


def _hex_to_rgb_triplet(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b}"


def build_palette_css(mode: str) -> str:
    """Per-render palette stylesheet -- the mode-dependent counterpart to
    STATIC_CSS's constant :root block (--green/--red/--amber/--yellow are
    never touched here; they live in STATIC_CSS and stay fixed across all 4
    modes, since they're reserved pipeline-status/advanced-flap signals, not
    theme colors)."""
    p = PALETTE_HEX.get(mode, PALETTE_HEX["blue"])
    ink_rgb = _hex_to_rgb_triplet(p["ink"])
    panel_rgb = _hex_to_rgb_triplet(p["panel"])

    rules = [
        ":root {"
        f" --bg: {p['bg']};"
        f" --panel: {p['panel']};"
        f" --ink: {p['ink']};"
        f" --ink-bright: {p['ink_bright']};"
        f" --ink-dim: {p['ink_dim']};"
        f" --text: {p['text']};"
        f" --text-dim: {p['text_dim']};"
        f" --grid-line: {p['grid']};"
        f" --ink-rgb: {ink_rgb};"
        f" --panel-rgb: {panel_rgb};"
        f" --panel-85: rgba({panel_rgb},0.85);"
        " }"
    ]

    # Each of the 4 swatches always shows THAT swatch's own mode colors,
    # literal hex -- never var(--ink)/var(--bg) -- so they don't all
    # converge visually once a mode is picked.
    for m, hexes in PALETTE_HEX.items():
        rules.append(
            f'div[class*="st-key-palette_{m}"] button {{ '
            f'border-color: {hexes["ink"]} !important; '
            f'background: {hexes["bg"]} !important; '
            f'color: {hexes["text"]} !important; }}'
        )

    # Active-mode swatch: scaled-down nav-active-cell corner-tick motif, plus
    # a ring echoing the stepper's own CURRENT-node outline treatment.
    active_text = p["text"]
    rules.append(
        f'div[class*="st-key-palette_{mode}"] button {{ '
        "outline: 2px solid var(--ink) !important; outline-offset: 2px !important; }"
    )
    rules.append(
        f'div[class*="st-key-palette_{mode}"] button::before {{ '
        f'content: "┌"; position:absolute; top:-1px; left:-2px; font-size:8px; '
        f'line-height:1; color:{active_text}; }}'
    )
    rules.append(
        f'div[class*="st-key-palette_{mode}"] button::after {{ '
        f'content: "┘"; position:absolute; bottom:-1px; right:-2px; font-size:8px; '
        f'line-height:1; color:{active_text}; }}'
    )

    # White mode: dark contrast ring behind all 3 status glyph colors
    # (yellow/green/red) -- load-bearing for yellow on a cream background,
    # harmless redundant on the other two. Covers both places glyphs render:
    # the stepper buttons themselves, and Setup's status ledger.
    if mode == "white":
        rules.append(
            'div[class*="st-key-step_"] button, .status-glyph { '
            "filter: drop-shadow(0 0 0.5px var(--text)) drop-shadow(0 0 1.5px var(--text)); }"
        )

    return "\n".join(rules)


def build_sheet_tab_css() -> str:
    rules = []
    for key, (number, title) in SHEET_TITLES.items():
        rules.append(
            f'div[class*="st-key-{key}"]::before {{'
            f' content: "SHEET {number} — {title}";'
            " position:absolute; top:-16px; left:18px; z-index:2;"
            " background:var(--bg); border:3px solid var(--ink); color:var(--ink);"
            " padding:2px 10px; font-size:11px; font-family:'IBM Plex Mono',monospace;"
            " letter-spacing:0.12em;"
            "}"
        )
    return "\n".join(rules)


def build_dynamic_css(active_page: str, stage_status: dict, current_stage: str | None) -> str:
    # Every piece appended here is either one self-contained rule, or a run
    # of adjacent f-strings that each independently escape their own "{{"/
    # "}}" pairs -- never a plain (non-f) string glued next to an f-string,
    # which is exactly the bug that once silently broke every rule after the
    # first in this function's design-round predecessor.
    rules = []

    active_nav_key = f"nav_{active_page}"
    rules.append(
        f'div[class*="st-key-{active_nav_key}"] button {{ '
        "background: var(--ink) !important; color: var(--bg) !important; }"
    )
    rules.append(
        f'div[class*="st-key-{active_nav_key}"] button::before {{ '
        'content: "┌"; position:absolute; top:1px; left:5px; font-size:11px; color:var(--bg); }'
    )
    rules.append(
        f'div[class*="st-key-{active_nav_key}"] button::after {{ '
        'content: "┘"; position:absolute; bottom:1px; right:5px; font-size:11px; color:var(--bg); }'
    )

    for stage_key, status in stage_status.items():
        step_key = f"step_{stage_key}"
        rules.append(
            f'div[class*="st-key-{step_key}"] button {{ '
            f"border-color: {STATUS_COLOR_VAR[status]} !important; color: {STATUS_COLOR_VAR[status]} !important; }}"
        )
        if status == "failed":
            rules.append(
                f'div[class*="st-key-{step_key}"] button {{ animation: failedPulse 2.5s ease-in-out infinite; }}'
            )

    if current_stage is not None:
        cur_key = f"step_{current_stage}"
        rules.append(
            f'div[class*="st-key-{cur_key}"] button {{ '
            "outline: 3px solid var(--ink) !important; outline-offset: 5px; }"
        )
        rules.append(
            f'div[class*="st-key-{cur_key}"]::before {{ '
            'content: "CURRENT"; position:absolute; top:-32px; left:50%; transform:translateX(-50%); '
            "background:var(--bg); border:2px solid var(--ink); color:var(--ink); "
            "font-size:9px; letter-spacing:0.16em; padding:2px 8px; white-space:nowrap; z-index:3; "
            "font-family:'IBM Plex Mono',monospace; }"
        )
        rules.append(
            f'div[class*="st-key-{cur_key}"]::after {{ '
            'content:""; position:absolute; top:-12px; left:50%; width:2px; height:12px; '
            "background:var(--ink); transform:translateX(-50%); }"
        )
    return "\n".join(rules)


STATIC_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap');

:root {
  --green: #3ecf6e;
  --amber: #f5a623;
  --red: #ff4d4f;
  --yellow: #FFD60A;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background-color: var(--bg) !important;
  background-image:
    repeating-linear-gradient(0deg, var(--grid-line) 0px, var(--grid-line) 1px, transparent 1px, transparent 24px),
    repeating-linear-gradient(90deg, var(--grid-line) 0px, var(--grid-line) 1px, transparent 1px, transparent 24px);
  background-attachment: fixed;
  color: var(--text) !important;
}

* { font-family: 'Inter', sans-serif; }
h1, h2, h3, h4, h5, h6, button, label, .mono,
div[class*="st-key-sheet_"] p, div[class*="st-key-step_"] p {
  font-family: 'IBM Plex Mono', monospace !important;
  letter-spacing: 0.02em;
}

[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stMain"] .block-container { padding-top: 1.4rem; max-width: 1180px; }

hr { border-color: var(--ink-dim) !important; }

/* ---------- App title strip ---------- */
.blueprint-title {
  display:flex; align-items:baseline; justify-content:space-between;
  border-bottom: 3px solid var(--ink); padding-bottom: 10px; margin-bottom: 4px;
}
.blueprint-title .name { font-size: 20px; font-weight:700; letter-spacing:0.08em; color:var(--text); }

/* ---------- Top nav cells ---------- */
div[class*="st-key-nav_"] button {
  width:100% !important;
  border:3px solid var(--ink) !important;
  background: var(--bg) !important;
  color: var(--ink) !important;
  border-radius:0 !important;
  font-weight:700 !important;
  font-size:13px !important;
  padding:14px 4px !important;
  position:relative;
  box-shadow:none !important;
}
div[class*="st-key-nav_"] button:hover { background: rgba(var(--ink-rgb),0.14) !important; }

/* ---------- Stepper ledger ---------- */
.stepper-wrap { margin-top:18px; margin-bottom:6px; }
div[class*="st-key-step_"] { position:relative; overflow:visible; margin-top:20px; }
div[class*="st-key-step_"] button {
  width:100% !important;
  border:3px solid var(--ink) !important;
  background: var(--panel) !important;
  color: var(--text) !important;
  border-radius:0 !important;
  font-size:10px !important;
  font-weight:600 !important;
  padding:10px 3px !important;
  position:relative;
  box-shadow:none !important;
  line-height:1.35 !important;
  word-break:break-word;
  min-height:64px;
}
div[class*="st-key-step_"] button:hover { filter:brightness(1.18); }

@keyframes failedPulse {
  0%, 100% { filter: drop-shadow(0 0 2px rgba(255,77,79,0.35)); }
  50% { filter: drop-shadow(0 0 9px rgba(255,77,79,0.95)); }
}

/* ---------- Stepper: wrap to two rows below 768px, scoped to its own row
   (stHorizontalBlock is shared by every st.columns() call in the app, so
   this must not be a bare, unscoped selector). ---------- */
div[class*="st-key-stepper_row"] div[data-testid="stHorizontalBlock"] {
  flex-wrap: nowrap;
}
@media (max-width:768px) {
  div[class*="st-key-stepper_row"] div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    row-gap: 48px !important;
  }
  /* Streamlit's own bundled CSS sets each stColumn's min-width to
     calc(100% - 24px) below its own internal breakpoint, which forces one
     column per row regardless of flex-wrap. Override it here so the
     4-then-3 wrap can actually happen instead of full vertical stacking. */
  div[class*="st-key-stepper_row"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
    min-width: 76px !important;
    flex-basis: 76px !important;
  }
}

/* ---------- Palette selector (top-left, all 4 modes) ----------
   Deliberately LEFT, not right: Streamlit's own header cluster
   (hamburger menu / Deploy button) lives top-right, so this avoids
   sitting underneath or beside it. */
div[class*="st-key-palette_selector"] {
  /* Must clear Streamlit's own header/toolbar (z-index:999990) or its
     transparent-but-still-interactive overlay swallows every click. */
  position:fixed !important; top:14px !important; left:14px !important; z-index:1000000 !important;
  border:3px solid var(--ink); background:var(--panel-85);
  padding:10px 12px !important; width:auto !important;
}
div[class*="st-key-palette_selector"]::before {
  content: "INK";
  position:absolute; top:-16px; left:10px; z-index:2;
  background:var(--bg); border:3px solid var(--ink); color:var(--ink);
  padding:2px 10px; font-size:11px; font-family:'IBM Plex Mono',monospace;
  text-transform:uppercase; letter-spacing:0.12em;
}
div[class*="st-key-palette_swatch_row"] div[data-testid="stHorizontalBlock"] { gap:6px !important; }
div[class*="st-key-palette_blue"] button,
div[class*="st-key-palette_green"] button,
div[class*="st-key-palette_white"] button,
div[class*="st-key-palette_black"] button {
  width:18px !important; height:18px !important; min-height:18px !important;
  border-radius:0 !important; padding:0 !important; margin:0 !important;
  font-size:9px !important; font-weight:700 !important; line-height:18px !important;
  box-shadow:none !important; position:relative;
}
@media (max-width:768px) {
  div[class*="st-key-palette_swatch_row"] div[data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
    width: 106px !important;
  }
  div[class*="st-key-palette_swatch_row"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
    flex:0 0 calc(50% - 3px) !important; width:calc(50% - 3px) !important; min-width:0 !important;
  }
}

/* ---------- Sheets ---------- */
div[class*="st-key-sheet_"] {
  border: 4px solid var(--ink);
  background: rgba(var(--panel-rgb),0.55);
  padding: 30px 22px 20px 22px;
  margin: 30px 0 10px 0;
  position: relative;
}
div[class*="st-key-sheet_"]::after {
  content: "";
  position: absolute;
  right: 6px; top: 12px; bottom: 12px; width: 8px;
  background-image: repeating-linear-gradient(180deg, var(--ink-dim) 0, var(--ink-dim) 1px, transparent 1px, transparent 12px);
  opacity: 0.55;
}

/* ---------- Mount-once entrance animation ---------- */
@keyframes sheetEnter { from { opacity:0; transform: translateY(18px); } to { opacity:1; transform: translateY(0); } }
div[class*="__animated"] { animation: sheetEnter 0.55s ease-out; }

/* ---------- Awaiting-input placeholder ---------- */
div[class*="st-key-await_"] {
  border: 2px dashed var(--text-dim) !important;
  color: var(--text-dim) !important;
  padding: 20px !important;
  text-align:center;
  border-radius:2px;
}
div[class*="st-key-await_"] h5 { color: var(--text-dim) !important; margin-bottom:4px; }
div[class*="st-key-await_"] p { color: var(--text-dim) !important; }

/* ---------- Spec boxes (small bordered input clusters) ---------- */
div[class*="st-key-spec_box_"] {
  border: 2px solid var(--ink-dim);
  padding: 10px 14px 4px 14px;
  background: rgba(var(--ink-rgb),0.04);
}
div[class*="st-key-spec_box_"] label {
  color: var(--ink) !important;
  text-transform: uppercase;
  font-size: 11px !important;
  letter-spacing: 0.12em !important;
}

/* ---------- Amber flap: a restyled native st.expander(key=...), for a
   genuinely rarely-touched settings drawer. Confirmed via the installed
   Streamlit's own bundled frontend that st.expander renders a real
   HTML "details" element with a nested "summary" element, under
   [data-testid="stExpander"].
   NOTE for anyone editing this string in the future: never write a literal
   angle-bracket tag anywhere in this whole combined stylesheet, including
   inside a comment like this one, even referring to the style tag itself
   by name. st.html() sanitizes its entire input as HTML before any of it
   is treated as an inert style block, so one tag-shaped substring anywhere
   -- comment or not -- silently drops this whole multi-thousand-character
   stylesheet with no error, no exception, nothing in any log. That exact
   mistake, once fixed, is the actual reason this note exists. ---------- */
div[class*="st-key-flap_amber_"] [data-testid="stExpander"] {
  border: 2px dashed var(--amber) !important;
  background: rgba(245,166,35,0.04) !important;
}
div[class*="st-key-flap_amber_"] [data-testid="stExpander"] summary,
div[class*="st-key-flap_amber_"] [data-testid="stExpander"] summary * {
  color: var(--amber) !important;
}

/* ---------- Ink flap: same mechanism, neutral color -- for a primary
   collapsible feature (e.g. a CRUD list) that isn't "advanced/optional"
   and shouldn't borrow the amber "safe to ignore" signal. ---------- */
div[class*="st-key-flap_ink_"] [data-testid="stExpander"] {
  border: 2px solid var(--ink-dim) !important;
  background: rgba(var(--ink-rgb),0.04) !important;
}
div[class*="st-key-flap_ink_"] [data-testid="stExpander"] summary,
div[class*="st-key-flap_ink_"] [data-testid="stExpander"] summary * {
  color: var(--ink) !important;
}

/* ---------- View switcher (calm, flat pills) ---------- */
div[class*="st-key-view_mode_"] { margin-top:6px; }
div[class*="st-key-view_mode_"] button,
div[class*="st-key-view_mode_"] [role="radio"] {
  border-radius: 999px !important;
  border: 1px solid var(--ink-dim) !important;
  background: transparent !important;
  color: var(--text) !important;
  font-family:'Inter',sans-serif !important;
  font-weight:500 !important;
  box-shadow:none !important;
}
div[class*="st-key-view_mode_"] button[aria-checked="true"],
div[class*="st-key-view_mode_"] [role="radio"][aria-checked="true"] {
  background: var(--ink-dim) !important;
  border-color: var(--ink) !important;
  color: var(--text) !important;
}

/* ---------- Molecule cards ---------- */
div[class*="st-key-card_"] {
  border: 3px solid var(--ink);
  padding: 14px;
  background: rgba(var(--panel-rgb),0.55);
  margin-bottom: 18px;
  min-height: 260px;
}
.card-title { font-family:'IBM Plex Mono', monospace; font-weight:700; color:var(--ink-bright); font-size:13px; letter-spacing:0.06em; }
.card-formula { font-family:'IBM Plex Mono', monospace; color:var(--text); font-size:12px; margin-top:2px; }
.card-scans { font-family:'IBM Plex Mono', monospace; color:var(--ink-dim); font-size:11px; margin-top:4px; }
.structure-box { text-align:center; margin:10px 0; }
.structure-placeholder { font-size:60px; color:var(--ink-dim); }

/* ---------- Sub-header inside a sheet (ANALYZE's internal sub-sections) --
   one visual step down from the sheet's own corner-tab title. ---------- */
.sub-header {
  font-family:'IBM Plex Mono', monospace; font-size:11px; letter-spacing:0.14em;
  text-transform:uppercase; color:var(--ink); border-bottom:1px solid var(--ink-dim);
  padding-bottom:4px; margin:18px 0 10px 0;
}

/* ---------- Status ledger rows (Setup) ---------- */
.status-row { display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--ink-dim); }
.status-row:last-child { border-bottom:none; }
.status-glyph { font-size:15px; width:22px; text-align:center; }
.status-label { font-family:'IBM Plex Mono', monospace; font-size:12px; letter-spacing:0.06em; flex:1; }
.status-text { font-family:'IBM Plex Mono', monospace; font-size:11px; letter-spacing:0.08em; text-transform:uppercase; }
"""


def render_boot_css() -> None:
    import streamlit as st

    st.html(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap');
:root { --ink-bright:#a9dcef; --ink-dim:#3a5a72; }
html, body { background:#0d1b2e; }
.boot-overlay {
  position:fixed; inset:0; z-index:1000000;
  background:#0d1b2e;
  display:flex; align-items:center; justify-content:center;
  flex-direction:column;
}
.boot-svg { width:min(40vw,240px); height:auto; overflow:visible; }
.boot-rect, .boot-line {
  fill:none; stroke:#7ec8e3; stroke-width:2.5;
  stroke-dasharray:1700; stroke-dashoffset:1700;
  animation: bootDraw 0.55s ease-out forwards;
}
.boot-rect.b2 { animation-delay:.075s; stroke-dasharray:520; stroke-dashoffset:520; }
.boot-rect.b3 { animation-delay:.15s; stroke-dasharray:520; stroke-dashoffset:520; }
.boot-line.l1 { animation-delay:.225s; stroke-dasharray:560; stroke-dashoffset:560; }
.boot-line.l2 { animation-delay:.275s; stroke-dasharray:260; stroke-dashoffset:260; }
@keyframes bootDraw { to { stroke-dashoffset:0; } }

.boot-log {
  border:2px solid var(--ink-dim);
  background: rgba(18,36,56,0.6);
  padding:14px 18px;
  width:min(70vw,460px);
  margin-top:22px;
  opacity:0;
  animation: bootLogFade 0.20s linear 0.10s forwards;
}
@keyframes bootLogFade { to { opacity:1; } }

.boot-log-line {
  font-family:'IBM Plex Mono', monospace;
  font-size:13px;
  letter-spacing:0 !important;
  overflow:hidden; white-space:nowrap;
  width:0ch;
  border-right:2px solid transparent;
  padding-right:1px;
  color: var(--ink-bright);
}
@keyframes bootCaretBlink { 0%,49% { border-right-color: var(--ink-bright); } 50%,100% { border-right-color: transparent; } }
@keyframes bootCaretHide { to { border-right-color: transparent; } }
@keyframes bootLineDim { to { color: var(--ink-dim); } }
@keyframes bootTypeL1 { to { width: 21ch; } }
@keyframes bootTypeL2 { to { width: 21ch; } }
@keyframes bootTypeL3 { to { width: 26ch; } }
@keyframes bootTypeL4 { to { width: 22ch; } }

.boot-log-line.l1 {
  animation:
    bootTypeL1 0.30s steps(21,end) 0.35s forwards,
    bootCaretBlink 0.5s steps(2,end) 0.35s infinite,
    bootCaretHide 0.01s linear 0.75s forwards,
    bootLineDim 0.01s linear 0.65s forwards;
}
.boot-log-line.l2 {
  animation:
    bootTypeL2 0.30s steps(21,end) 0.75s forwards,
    bootCaretBlink 0.5s steps(2,end) 0.75s infinite,
    bootCaretHide 0.01s linear 1.15s forwards,
    bootLineDim 0.01s linear 1.05s forwards;
}
.boot-log-line.l3 {
  animation:
    bootTypeL3 0.35s steps(26,end) 1.15s forwards,
    bootCaretBlink 0.5s steps(2,end) 1.15s infinite,
    bootCaretHide 0.01s linear 1.60s forwards,
    bootLineDim 0.01s linear 1.50s forwards;
}
.boot-log-line.l4 {
  animation:
    bootTypeL4 0.30s steps(22,end) 1.60s forwards,
    bootCaretBlink 0.5s steps(2,end) 1.60s infinite;
}

.boot-title { margin-top:22px; text-align:center; opacity:0; animation:bootStamp .5s ease-out 1.9s forwards; }
.boot-title-main {
  font-family:'IBM Plex Mono', monospace; color:#e8f4f8; font-size:22px;
  letter-spacing:0.12em; font-weight:700;
}
@keyframes bootStamp {
  0% { opacity:0; transform:scale(0.7); }
  60% { opacity:1; transform:scale(1.08); }
  100% { opacity:1; transform:scale(1); }
}
div[class*="st-key-boot_skip"] button {
  position:fixed !important; inset:0 !important; width:100vw !important; height:100vh !important;
  z-index:1000001 !important; background:transparent !important; border:none !important;
  opacity:0 !important; cursor:pointer !important; margin:0 !important; padding:0 !important;
}
</style>
<div class="boot-overlay">
  <svg class="boot-svg" viewBox="0 0 560 300" xmlns="http://www.w3.org/2000/svg">
    <rect class="boot-rect b1" x="14" y="14" width="532" height="272" />
    <rect class="boot-rect b2" x="46" y="46" width="200" height="110" />
    <rect class="boot-rect b3" x="314" y="176" width="200" height="98" />
    <line class="boot-line l1" x1="14" y1="150" x2="546" y2="150" />
    <line class="boot-line l2" x1="280" y1="14" x2="280" y2="286" />
  </svg>
  <div class="boot-log">
    <div class="boot-log-line l1">&gt; DRAFTING SHEET 1...</div>
    <div class="boot-log-line l2">&gt; CALIBRATING GRID...</div>
    <div class="boot-log-line l3">&gt; LOADING SUSPECT INDEX...</div>
    <div class="boot-log-line l4">&gt; STAMPING REVISION...</div>
  </div>
  <div class="boot-title">
    <div class="boot-title-main">DUF62 FLUORO PROJECT</div>
  </div>
</div>
"""
    )


def run_boot_gate() -> None:
    """Plays once per session; skippable by a click anywhere. Must be called
    after `st.set_page_config` and the `booted`/`boot_start` session-state
    defaults, before any other page content renders."""
    import streamlit as st

    if st.session_state.booted:
        return
    if st.session_state.boot_start is None:
        st.session_state.boot_start = time.monotonic()

    render_boot_css()
    skipped = st.button("Skip boot animation", key="boot_skip")
    elapsed = time.monotonic() - st.session_state.boot_start
    if skipped or elapsed >= BOOT_DURATION:
        st.session_state.booted = True
        st.rerun()
    else:
        time.sleep(0.1)
        st.rerun()
    st.stop()
