# setup

The app's landing page (first in the sidebar nav). No science logic of its
own -- purely orientation and shared selection.

## `gui.py`

Four things:
1. **What each page does** -- a one-line description per module, so a new
   user isn't left guessing what "MS Matching" vs. "In-silico Library" means
   before trying either.
2. **Shared mzML file picker** -- the same `common.ui.pick_mzml_files` every
   other page uses, under `common.ui.SHARED_MZML_KEY`. Picking files here
   seeds the *default* selection on every other page (mzML Scan Detector, MS
   Matching) via `pick_mzml_files`'s `default` param -- each page still has
   its own independent, still-editable selection, so choosing a different
   file later on one page never changes what another page uses. mzML
   discovery itself looks under `<repo root>/data/mzml/` (gitignored) --
   a real, repo-relative default any clone can use, not a path that only
   makes sense on one specific machine.
3. **Shared library file path** -- a text input (`common.ui.SHARED_LIBRARY_PATH_KEY`)
   pointing at any CSV/Parquet library file, plus an explanation of the
   minimal format In-silico Library's column mapping expects (a structure
   column is the only hard requirement; everything else is computed).
4. **Results (optional)** -- paths to an already-built suspect library
   (`SHARED_SUSPECT_LIBRARY_KEY`) and an already-saved MS Matching result
   (`SHARED_CANDIDATE_TABLE_KEY`), defaulting to each module's standard
   output location when a file is already there. In-silico Library and MS
   Matching read these to auto-populate from disk the moment you open them
   -- no "load" click needed every session, so opening each module
   automatically shows the results already created.
5. **Status** -- mzML files selected, and whether a suspect library / MS
   Matching result is ready to auto-load.

## Shared-key pitfalls found while building this (both fixed)

**Reading a widget key from a different page.** A page reading
`SHARED_LIBRARY_PATH_KEY`/`SHARED_SUSPECT_LIBRARY_KEY`/`SHARED_CANDIDATE_TABLE_KEY`
without also rendering that exact widget itself must call
`common.ui.restore(key, default)` first -- these are widget keys *on this
page*, so `st.navigation` clears their own session_state entry the moment
this page is unmounted, same as any other widget. Reading them directly from
`st.session_state` works fine while Setup itself is the active page, then
silently returns nothing from any other page until `restore()` pulls the
persisted value back in.

**The mzML list is two widgets, not one -- reading only the multiselect's own
session_state silently drops anything entered as a custom path.**
`SHARED_MZML_KEY` is only the multiselect half of `pick_mzml_files`; the
custom-paths text area is a second, separate key
(`f"{SHARED_MZML_KEY}_custom"`). A real bug shipped briefly because of this:
downstream pages seeded their default from
`st.session_state.get(SHARED_MZML_KEY)` alone, so any file entered as a
custom path (exactly how a private data folder outside `data/mzml/` gets in)
never propagated anywhere, even though it displayed correctly on Setup's own
page. Fixed with `common.ui.resolved_shared_mzml_files()`, which combines
both halves *and* reads the persisted settings store directly rather than
`st.session_state` -- robust even when a preset is loaded from the sidebar
while a different page is active, since the sidebar's preset controls are
reachable from every page, not just Setup's own. Every reader of the shared
mzML selection (Setup's own status count, mzML Scan Detector, MS Matching)
now goes through this one function instead of reading the raw key.

**A value that was never wired into `restore`/`persist` at all doesn't save
with a preset, full stop -- not just a cross-page read problem.** The mzML
Scan Detector's diagnostic ion target list (`diagnostic_targets`, a
manually-managed list of dicts, not a typical single-value widget) used plain
`st.session_state.setdefault(...)`, so it was never mirrored into the
persisted settings store in the first place -- `save_preset`/`load_preset`
never saw it, no matter which page was active. Fixed by routing it through
`restore`/`persist` like everything else (`persist()` called again after
every in-place mutation -- append/remove/checkbox -- not just once after a
single widget, since this key is a whole list rather than one value); MS
Matching's own read of it also needed the same `restore()`-before-reading
fix as the first pitfall above, since it's a *different* page's key there
too. Worth checking for when adding any new shared, non-trivial (list/dict)
piece of state: does it actually flow through `restore`/`persist`, or does it
just look like it does because it happens to survive within one session?

## Status
Built and live-tested end-to-end, including the exact failure mode a real
saved preset hit (files entered as custom paths, not the discovered-file
multiselect): module descriptions render; the mzML selection -- multiselect
*and* custom paths -- correctly seeds mzML Scan Detector's and MS Matching's
own pickers across a real page navigation; the library path survives
navigating to In-silico Library the same way; MS Matching auto-loads a saved
result with no click; and the status panel correctly reflects a real built
suspect library / saved match result.
