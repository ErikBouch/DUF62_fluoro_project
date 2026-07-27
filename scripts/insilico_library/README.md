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
| `formula`, `exact_mass` | computed once here via RDKit; reused by later acylation math |
| `has_primary_amine` | SMARTS `[NX3H2;!$(NC(=O));!$(NS(=O)(=O))]` — excludes amide/sulfonamide N; first-pass heuristic |
| `name` | from LOTUS/HMDB where available |
| `organism` | from DNP only (messy free text) |
| `source_db` | comma-joined set, e.g. `"dnp,lotus"` — which DB(s) this structure was found in |

Rows RDKit can't parse are dropped (and counted in the per-source `LoadStats`).

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
a generated result — hence `data/`, not `output/`.

### Usage (import)
```python
from insilico_library.db_loader import load_dnp, load_lotus, load_hmdb, merge_rows
dnp_rows, _ = load_dnp("dnp.tsv")
lotus_rows, _ = load_lotus("lotus.sdf")
hmdb_rows, _ = load_hmdb("hmdb.xml")
df = merge_rows([dnp_rows, lotus_rows, hmdb_rows])
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

Runs the acylation reactions over the *full* merged structure table (not just
the 20-AA benchmark): filters `unified_structures.parquet` to
`has_primary_amine == True`, then runs both `acylate()` reactions on every
remaining compound. Writes two tables under `data/`: the mono-acylation
products (one row per parent × reaction × reactive site, each with a real
InChI/SMILES/formula/mass/adducts) and a formula-only table for compounds with
more than one reactive site acylated at once (degree ≥ 2, no structure). Each
compound is processed inside a try/except so one bad structure can't abort
the run; failures are counted and reported at the end.

```bash
python build_suspect_library.py --limit 200          # quick test run first
python build_suspect_library.py                      # full run
python build_suspect_library.py --csv data/suspect_library.csv \
    --csv-multidegree data/suspect_library_multidegree.csv   # also write plain CSVs
```

## `gui.py`

Streamlit page: shows stats for the merged structure table and the suspect
library built from it (row counts, fluoroacetyl/acetyl breakdown, a preview),
plus a button to (re)build the suspect library from the merged table without
leaving the GUI — this calls `build_suspect_library.build_library` directly
(same code path as the CLI), with a real progress bar (not just a spinner)
driven by the same per-checkpoint fraction `build_library` already computes
for its text log.

## Folders
- `data/` — all of this module's tables live here: the merged structure table
  (`unified_structures.parquet` + a plain `.csv` copy) and the suspect library
  built from it (`suspect_library.parquet` / `suspect_library_multidegree.parquet`
  + plain `.csv` copies). This is **input data** for later steps (matching),
  not a generated result. The raw source DBs (DNP/LOTUS/HMDB) live in a shared
  parent data folder outside this repository, not here. All gitignored.
- `output/` — reserved for genuine generated results (e.g. a final match
  candidate table); empty for now.

## Status
`db_loader.py`: built, tested, and run successfully across all three sources.
`acylation.py` + `benchmark_aa.py`: built and tested, including the optional
multi-site (formula-only) calculation. `build_suspect_library.py` + `gui.py`:
built, tested, and run successfully over the full merged library.

**Not yet built**: the actual matching step against real mzML data lives in
the `comparison` module.
