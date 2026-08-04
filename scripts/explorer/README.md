# explorer

A "store shelf" gallery for browsing the compound structures surviving a
MS Matching run, instead of scrolling a results table row by row.

## `gui.py`

Reads the *same* final-filtered result that MS Matching's own Summary
section uses (`st.session_state`: `cmp_candidate_table` +
`cmp_features_for_summary` -- the acetyl-co-occurring subset when that check
was run, otherwise every feature) -- run a match in the MS Matching tab
first; this page has no data of its own.

Aggregation (`comparison.matcher.structures_by_formula`) is fully vectorized
(no per-formula Python loop) so paging/sorting stays responsive even over
thousands of distinct formulas. Each formula gets one card: a representative
2D structure (RDKit, rendered to a `data:` URI and embedded directly, via
`comparison.plotting.mol_image_data_uri`), the formula, total scan count, and
how many distinct structures ("isomers" -- not necessarily true structural
isomers, e.g. many distinct lipid species can share one elemental formula)
are pooled into that count. Hovering a card reveals exact mass, reaction
type, parent name, and acetyl co-occurrence in an overlay; a formula with
more than one structure gets an "Explore N isomers" button that opens a
modal (`st.dialog`) listing every individual structure for that formula via
`comparison.matcher.isomers_for_formula`, each with its own scan count.

Cards render 3 per row, 24 at a time (`explorer/gallery.py`'s `PAGE_SIZE`),
with a "Load more" button appending the next batch rather than a page index,
so nothing already on screen shifts position. Default sort is total scan
count (most first); also available: most isomers, formula alphabetically,
exact mass ascending (`explorer/gallery.py`'s `SORT_OPTIONS`).

**Performance**: card structure images are cached (`@st.cache_data`, keyed on
SMILES) -- Streamlit reruns the whole page on any interaction anywhere, so
without caching every already-shown card would redraw from scratch every
time, not just newly-loaded ones. The isomer dialog renders one *composed*
grid image (`comparison.plotting.build_isomer_grid_image`) rather than one
widget/embedded image per isomer -- a formula can pool dozens of isomers (one
real example had 65), and hundreds of individual small elements turned out
far more expensive to transmit/render than the RDKit drawing itself. A
bigger, separate performance factor -- `main.py`'s navigation re-running
every module's code on every interaction anywhere in the app -- is avoided
by construction: `main.py` dispatches to exactly one module's `render()`
per rerun (a `PAGE_RENDERERS` lookup on `st.session_state["page"]`, not
`st.tabs`), so the other four modules' code never runs on a rerun that
happened on this page (see the top-level `scripts/README.md`).

**Note**: this page's own pagination (`explorer_n_loaded`) is cached against
the *identity* of the result tables it's reading (`id(candidate_table)`,
`id(features_table)`), not their content, to detect a genuinely new MS
Matching run without recomputing `structures_by_formula` on every unrelated
rerun. This means whatever sets those tables in session_state must give them
a *stable* object identity across reruns -- reassigning a freshly-computed
object on every rerun (even if the data is unchanged) defeats this cache and
silently breaks pagination. See `comparison/gui.py`'s
`_populate_result_session_state`, the single place those tables are set.

## Pipeline status

Unsheeted, like Setup -- this is a browsing page, not a pipeline stage on
its own, but it still reports into the pipeline stepper: a small, pure
`review_output_status()` reads two flags this page's own `render()` sets
(`explorer_reviewed`, once real structures actually render; `explorer_last_result_empty`,
if a loaded result had none) -- both reset by `comparison.gui`'s
`_populate_result_session_state` whenever genuinely new data loads, so a
stale "already reviewed" signal can't survive onto a fresh, unreviewed
result. The three-button empty-state loader (unchanged logic) now renders
inside the same dashed "awaiting input" visual `common.ui` uses everywhere
else for an unmet precondition, rather than a plain `st.info` line -- the
three buttons themselves are still always live, not hidden behind it.

## `gallery.py` (logic — no Streamlit import)

Pure pagination/sort helpers (`paginate`, `sort_structures`) over
`structures_by_formula`'s output, kept separate from `gui.py` so the paging/
sorting rules are testable without a running Streamlit session.

## Status
Built and tested end-to-end (sort, pagination, isomer drill-down dialog, no
console errors) against real match results, including a full run across all
4 example files.
