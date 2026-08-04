# insilico_library

Build the acetyl/fluoroacetyl in-silico suspect library for the fluoro project.

## `db_loader.py` (logic — no Streamlit import)

Parses natural-product/metabolite databases (DNP, LOTUS, HMDB) into **one
uniform, deduplicated structure table** — the goal is the structure itself,
not which source DB it came from (source DB is kept as metadata, not the
organizing principle).

**Why normalize:** the three sources are wildly different formats and
richness:
- **DNP** (`data/databases/dnp.tsv`): `database | inchi | organism_dirty | reference_external`.
- **LOTUS** (`data/databases/LOTUS_DB_LATEST/LOTUS_2021_03_simple.sdf`): SDF with
  `wikidata_id`, `lotus_id`, `inchi`, `inchikey`, `SMILES`, `name` per record —
  no organism/taxonomy despite being an SDF (the "_simple" export is
  structures-only; a companion `.tsv` in the same folder is just `SMILES + lotus_id`).
- **HMDB** (`data/databases/hmdb_metabolites/hmdb_metabolites.xml`): very rich
  per-record data (name, formula, precomputed masses, SMILES, InChI, InChIKey,
  chemical classification) but its "taxonomy" is chemical classification, not
  biological source.

Of the three, only DNP reliably has a biological-source field at all. The
uniform schema:

| column | notes |
|---|---|
| `inchikey` | dedup key; **always computed by RDKit here**, never trusted from source |
| `inchi` | canonical join field; present in or derivable from all three sources |
| `smiles` | canonical SMILES, computed by RDKit (not each source's own string) |
| `formula` | computed once here via RDKit |
| `name` | from LOTUS/HMDB where available |
| `organism` | from DNP only (messy free text) |
| `source_db` | comma-joined set, e.g. `"dnp,lotus"` — which DB(s) this structure was found in |

Rows RDKit can't parse are dropped (and counted in the per-source `LoadStats`).

**Deliberately not in this schema**: `exact_mass` and `has_primary_amine`.
Neither is something any of DNP/LOTUS/HMDB (or a user's own library) actually
supplies — both are specific to *later* pipeline steps (picking which
compounds to acylate, and computing adduct masses), so storing them here would
blur what's genuinely raw/merged input vs. computed downstream. Both are cheap
to recompute from `inchi` — `has_primary_amine(mol)` /
`compute_primary_amine_flags(inchis)` and `compute_exact_mass_series(inchis)`
— called right where they're actually needed (`build_suspect_library.py`, the
GUI's "Build" step), never persisted on the merged/normalized table.

**Merging**: single-pass dict merge keyed by `inchikey` (not
`groupby().apply()` — far too slow in pandas at large row counts). The same
structure found in multiple sources is kept once, with `source_db` recording
every DB it appeared in and the first non-null `name`/`organism` kept.

### Usage (CLI)
```bash
python db_loader.py --dnp <dnp.tsv> --lotus <lotus.sdf> --hmdb <hmdb.xml> \
    -o data/unified_structures.parquet --csv data/unified_structures.csv
# --limit N caps records per source, for a quick test run first
# --csv also writes a plain (uncompressed) human-readable copy
```

The merged table is **input data** for later steps (acylation, matching), not
a generated result — hence `data/`, not `output/`. The actual `data/unified_structures.parquet`
this repo's own pipeline uses is produced by `../../notebooks/build_unified_library.ipynb`
instead of a bare CLI call, so the merge process itself is documented with its
real output (the three source DBs are outside the repo, so re-running that
notebook needs your own local copies — reading it doesn't).

### Usage (import)
```python
from insilico_library.db_loader import load_dnp, load_lotus, load_hmdb, merge_rows
dnp_rows, _ = load_dnp("dnp.tsv")
lotus_rows, _ = load_lotus("lotus.sdf")
hmdb_rows, _ = load_hmdb("hmdb.xml")
df = merge_rows([dnp_rows, lotus_rows, hmdb_rows])
```

### Arbitrary user-supplied libraries: `load_user_table`

Not every library comes as DNP/LOTUS/HMDB. `load_user_table(df, inchi_col=None,
smiles_col=None, name_col=None, organism_col=None, source_label="user")`
normalizes *any* dataframe into the same schema -- at least one of `inchi_col`/
`smiles_col` is required, either is sufficient on its own, and both can be
given together (InChI tried first per row, SMILES as a fallback for that row
if the InChI value is missing/unparseable, same fallback `load_hmdb` uses
internally). There's no `inchikey_col`: an InChIKey is a one-way hash, so a
row that only has one has no structure to recover from it -- InChI or SMILES
is the only valid structure input. Everything else in the schema (`inchikey`,
canonical `smiles`, `formula`) is computed from whichever structure is found,
exactly like the other loaders -- a user's own formula/InChIKey columns, if
any, are never read; there's nothing to map them to. This is what the GUI's
column-mapping step (below) calls.

```python
from insilico_library.db_loader import load_user_table, merge_rows
rows, stats = load_user_table(my_df, smiles_col="smiles", name_col="compound_name")
normalized = merge_rows([rows])
```

## `acylation.py` (logic — no Streamlit import)

Adds an acetyl or fluoroacetyl group to a primary amine via a **real RDKit
reaction**, not string/formula arithmetic — the resulting InChI comes from
actually transforming the parsed structure and re-deriving it, since InChI
depends on full connectivity, not just atom counts. The formula delta
(+C2H1FO1 for fluoroacetyl, +C2H2O1 for acetyl) is computed too, but purely as
a cheap cross-check against the RDKit-derived product formula — never as the
source of truth.

Uses the same primary-amine definition as `db_loader.py`'s `has_primary_amine`
(excludes amide/sulfonamide N). A molecule with multiple independent reactive
sites (e.g. lysine's alpha- and epsilon-amines) yields **one product per
site** — each a distinct, independently valid mono-acylated regiochemistry,
not merged into a single result.

```python
from insilico_library.acylation import fluoroacetylate, acetylate
products = fluoroacetylate(mol)  # or an InChI string
for p in products:
    print(p.product_formula, p.product_inchi, p.mz_pos_m_plus_h, p.mz_neg_m_minus_h)
```

**Known limitation**: the SMARTS also matches a guanidine's terminal NH2 (e.g.
arginine), which is chemically much less nucleophilic than a simple
alkylamine — likely a false-positive reactive site, not fixed yet (flagged,
not blocking).

**Multi-site acylation** (more than one amine reacting at once, e.g. lysine's
alpha- *and* epsilon-amine together) is supported as an optional,
**formula/mass-only** calculation — no representative structure/InChI, and
deliberately no priority/tiering between candidate sites, to keep it cheap.
Use `multi_degree_formulas(mol, "fluoroacetyl")` — returns one entry per
degree, 1 up to the number of independent sites (`count_reactive_sites(mol)`):

```python
from insilico_library.acylation import multi_degree_formulas
for d in multi_degree_formulas(mol, "fluoroacetyl"):
    print(d.degree, d.formula, d.exact_mass)
# a molecule with 2 sites gives two entries: degree 1 (either site alone)
# and degree 2 (both sites acylated at once)
```

The per-degree mass delta is derived from RDKit itself (reacting a trivial
test amine) rather than a hand-typed periodic table, and is cross-checked
against a real single-site reaction to confirm the two agree exactly.

## `benchmark_aa.py` — 20 proteinogenic amino acids test

Fluoroacetylates all 20 AAs (SMILES verified against known formulas first),
then optionally searches all products (pos+neg adducts) against any local
mzML files found under `data/HRMS/` in one batched pass per file
(`mzml_tools.scan_detector.find_scans_with_multiple_mz` — loads each file once
instead of once per target). Doubles as a correctness test for `acylation.py`
on a chemically diverse, well-known set: multiple independent sites (lysine),
a guanidine (arginine), primary amides that must not react (asn/gln), and a
secondary/ring amine that correctly yields zero products (proline).

**Caveat on the search step**: at a loose screen (e.g. 20 ppm, low relative-
intensity threshold), expect *some* hits across most amino acids just from
coincidental overlap with background/isobaric ions at these small, chemically
common masses — a raw hit at this stage is not itself a confirmed
identification. That's exactly why the planned matching step (RT sensibility,
acetyl/parent co-occurrence, isotope pattern) exists.

```bash
python benchmark_aa.py
```

## `build_suspect_library.py`

Runs the acylation reactions over a *full* normalized structure table (not
just the 20-AA benchmark): computes `has_primary_amine` fresh from each row's
`inchi` (not read as a stored column -- see the schema note above), filters to
that subset, then runs both `acylate()` reactions on every remaining compound.
Writes two tables
under `output/` (a computed result, not input data): the mono-acylation
products (one row per parent × reaction × reactive site, each with a real
InChI/SMILES/formula/mass/adducts) and a formula-only table for compounds with
more than one reactive site acylated at once (degree ≥ 2, no structure). Each
compound is processed inside a try/except so one bad structure can't abort
the run; failures are counted and reported at the end.

```bash
python build_suspect_library.py --input data/unified_structures.parquet --limit 200  # quick test
python build_suspect_library.py --input data/unified_structures.parquet              # full run
```

## `gui.py`

Streamlit page: turns a user-supplied library into the suspect library,
**no longer specific to the DNP/LOTUS/HMDB merge** -- it reads whatever path
was set on the Setup page (any CSV/Parquet), lets you map which column holds
the structure (InChI/SMILES) and, optionally, name/organism, then runs two
stages, each with a real progress bar:

1. **Normalize** -- `db_loader.load_user_table` + `merge_rows` ->
   `output/normalized_library.parquet`, with the same stats view the old
   DNP/LOTUS/HMDB-specific page showed (unique structures, primary-amine
   count, sources).
2. **Build suspect library** -- `build_suspect_library.build_library` over
   the normalized, primary-amine subset -> `output/suspect_library.parquet`
   (+ multidegree), same as the CLI.

Verified against a known-chemistry test set (4 compounds, one column-mapped
CSV): normalize correctly flagged 3/4 as primary-amine-bearing (proline's
secondary ring amine correctly excluded), and build correctly produced 4
fluoroacetyl + 4 acetyl product rows (one simple amino acid's single site +
a symmetric diamine's single *distinct* product despite two reactive ends +
lysine's two independent alpha/epsilon sites).

## GUI layout and pipeline status

**Load existing library** shows two display-only sheets (Normalized
Library, Suspect Library -- `common.ui`'s shared sheet convention, see
`scripts/README.md`), no run controls. **Generate a new library** shows
three (Source, Normalize, Build) -- each stage's action button and its own
conditional result block share one sheet rather than being split into a
separate run box and an analyze box, since the underlying code already has
zero visual separation between the two.

Two small, pure, side-effect-free functions -- `normalize_status()` and
`build_status()` -- feed the pipeline stepper in `main.py`. Both reuse the
same file-validity checks the display functions already had (extracted so
there's exactly one place that decides "is this file actually a valid
normalized library / suspect library", not two that could drift). A fresh
Normalize run that parses 0 rows now also sets a session-only
`insilico_normalize_last_run_failed` flag (cleared on the next successful
run) -- without it, that failure was only ever an `st.error` on screen, with
no way for the stepper to know a fresh run had actually failed rather than
just not having run yet.

## Folders
- `data/` — genuinely raw/example input only: the DNP+LOTUS+HMDB merge
  (`unified_structures.parquet` + a plain `.csv` copy), produced by
  `../../notebooks/build_unified_library.ipynb` (which calls `db_loader.py`'s
  loaders), kept here as one example of "a library you already have" a user
  could point the Setup page at. A plain structure table only -- no
  `has_primary_amine`/`exact_mass` columns, same as any other input library.
  The raw source DBs themselves live in a shared parent data folder outside
  this repository, not here. All gitignored.
- `output/` — every computed result: `normalized_library.parquet` (stage 1)
  and `suspect_library.parquet`/`suspect_library_multidegree.parquet` (+ plain
  `.csv` copies, stage 2). **Moved here 2026-08-02** from `data/` -- the
  earlier "library files are input data" call was itself a mistake once the
  library became something the *user* builds from their own raw file, rather
  than something shipped with the repo; `suspect_library.parquet` in
  particular is unambiguously computed output, same as a match's own
  `candidate_table.parquet`.

## Status
`db_loader.py`: built, tested, and run successfully across all three sources,
plus the generic `load_user_table` path. `acylation.py` + `benchmark_aa.py`:
built and tested, including the optional multi-site (formula-only)
calculation. `build_suspect_library.py` + `gui.py`: built, tested, and run
successfully both over the full DNP/LOTUS/HMDB merge and a small
column-mapped user table.

**Not yet built**: the actual matching step against real mzML data lives in
the `comparison` module.
