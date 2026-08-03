"""
insilico_library/db_loader.py — parse DNP / LOTUS / HMDB into one uniform,
deduplicated structure table.

Logic only (no Streamlit import). Each `load_*` function normalizes one source
into a common schema:
    inchi, inchikey, smiles, name, organism, source_db, formula

`inchikey`, canonical `smiles`, and `formula` are always computed here via
RDKit (not trusted from the source file), so every row is uniform and
structure-valid regardless of where it came from. Rows RDKit can't parse are
dropped (and counted).

Deliberately NOT part of this schema: `exact_mass` and `has_primary_amine`.
Both are cheap, single-pass-recomputable properties of the structure that are
specific to *later* pipeline steps (acylation needs `has_primary_amine` to
pick a subset; the suspect library needs `exact_mass`/adduct masses), not
something any of DNP/LOTUS/HMDB (or a user's own library) actually supplies --
so they don't belong baked into what's otherwise meant to be a merged, but
still input-shaped, structure table. `has_primary_amine`/`exact_mass` are
computed on demand by `build_suspect_library.py` right before they're needed,
via `compute_primary_amine_flags`/`compute_exact_mass_series` below.

Merging is by `inchikey` (dedup key) -- the same structure found in multiple
source DBs is kept once, with `source_db` recording every DB it appeared in.

CLI:
    python db_loader.py --dnp <path> --lotus <path> --hmdb <path> -o <out.parquet>
"""
from __future__ import annotations

import argparse
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")  # silence per-molecule parse warnings (expected on messy DB entries)

# Primary amine: N with 2 H's, excluding amide (N-C=O) and sulfonamide (N-S(=O)(=O)) nitrogens.
PRIMARY_AMINE_SMARTS = "[NX3H2;!$(NC(=O));!$(NS(=O)(=O))]"


@dataclass
class LoadStats:
    source_db: str
    n_records_seen: int
    n_parsed_ok: int
    n_parse_failed: int


def _mol_row(mol, source_db: str, name=None, organism=None):
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    inchi = Chem.MolToInchi(mol)
    if not inchi:
        return None
    inchikey = Chem.InchiToInchiKey(inchi)
    if not inchikey:
        return None
    return {
        "inchi": inchi,
        "inchikey": inchikey,
        "smiles": Chem.MolToSmiles(mol),
        "name": name,
        "organism": organism,
        "source_db": source_db,
        "formula": rdMolDescriptors.CalcMolFormula(mol),
    }


def has_primary_amine(mol) -> bool:
    """Same primary-amine definition acylation.py reacts on."""
    from rdkit import Chem

    return mol.HasSubstructMatch(Chem.MolFromSmarts(PRIMARY_AMINE_SMARTS))


def _mol_from_inchi_safe(i):
    """
    `Chem.MolFromInchi` requires a real string and can still fail to parse
    one -- neither is hypothetical here: a non-string value (e.g. `NaN`,
    which is truthy in Python, so a bare `if i` guard doesn't catch it) would
    otherwise raise a `Boost.Python.ArgumentError`, and even a genuine,
    previously-valid InChI can fail to re-parse after a round trip through
    parquet/pandas or for an unusual structure (RDKit isn't guaranteed to
    accept every string it itself once produced) -- both are treated as "no
    structure" rather than crashing.
    """
    from rdkit import Chem

    if not isinstance(i, str) or not i:
        return None
    try:
        return Chem.MolFromInchi(i)
    except Exception:
        return None


def compute_primary_amine_flags(inchis) -> "pandas.Series":
    """
    Compute the `has_primary_amine` flag fresh from each row's InChI --
    called right before it's needed (filtering to build the suspect library),
    not stored as a persisted column on any merged/normalized table.
    """
    import pandas as pd

    def _flag(i):
        mol = _mol_from_inchi_safe(i)
        return has_primary_amine(mol) if mol is not None else False

    return pd.Series([_flag(i) for i in inchis], index=inchis.index if hasattr(inchis, "index") else None)


def compute_exact_mass_series(inchis) -> "pandas.Series":
    """Same idea as `compute_primary_amine_flags`, for `exact_mass`."""
    import pandas as pd
    from rdkit.Chem import Descriptors

    def _mass(i):
        mol = _mol_from_inchi_safe(i)
        return Descriptors.ExactMolWt(mol) if mol is not None else None

    return pd.Series([_mass(i) for i in inchis], index=inchis.index if hasattr(inchis, "index") else None)


def _progress(source_db: str, seen: int, ok: int, t0: float, every: int):
    if every and seen % every == 0:
        elapsed = time.time() - t0
        rate = seen / elapsed if elapsed > 0 else 0
        print(f"  [{source_db}] {seen} seen, {ok} ok, {elapsed:.0f}s elapsed, {rate:.0f} rec/s", flush=True)


def load_dnp(path: str, limit: int | None = None, progress_every: int = 20000) -> tuple[list[dict], LoadStats]:
    """DNP tsv: columns `database | inchi | organism_dirty | reference_external`."""
    from rdkit import Chem

    rows = []
    seen = ok = failed = 0
    t0 = time.time()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.readline()  # skip header
        for line in f:
            if limit is not None and seen >= limit:
                break
            seen += 1
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                failed += 1
                continue
            _db, inchi, organism = parts[0], parts[1], parts[2]
            mol = Chem.MolFromInchi(inchi) if inchi.startswith("InChI=") else None
            if mol is None:
                failed += 1
                continue
            row = _mol_row(mol, "dnp", organism=organism or None)
            if row is None:
                failed += 1
                continue
            rows.append(row)
            ok += 1
            _progress("dnp", seen, ok, t0, progress_every)
    return rows, LoadStats("dnp", seen, ok, failed)


def load_lotus(sdf_path: str, limit: int | None = None, progress_every: int = 20000) -> tuple[list[dict], LoadStats]:
    """LOTUS SDF: streamed via RDKit's ForwardSDMolSupplier (no full-file load)."""
    from rdkit import Chem

    rows = []
    seen = ok = failed = 0
    t0 = time.time()
    with open(sdf_path, "rb") as f:
        supplier = Chem.ForwardSDMolSupplier(f)
        for mol in supplier:
            if limit is not None and seen >= limit:
                break
            seen += 1
            if mol is None:
                failed += 1
                continue
            name = mol.GetProp("name") if mol.HasProp("name") else None
            row = _mol_row(mol, "lotus", name=name)
            if row is None:
                failed += 1
                continue
            rows.append(row)
            ok += 1
            _progress("lotus", seen, ok, t0, progress_every)
    return rows, LoadStats("lotus", seen, ok, failed)


def load_hmdb(xml_path: str, limit: int | None = None, progress_every: int = 20000) -> tuple[list[dict], LoadStats]:
    """
    HMDB 'All metabolites' XML: streamed via iterparse (file is multi-GB), one
    <metabolite> element at a time, cleared from memory immediately after use.
    """
    from rdkit import Chem

    ns = "{http://www.hmdb.ca}"
    rows = []
    seen = ok = failed = 0
    t0 = time.time()

    context = ET.iterparse(xml_path, events=("end",))
    for _event, elem in context:
        if elem.tag != f"{ns}metabolite":
            continue
        if limit is not None and seen >= limit:
            elem.clear()
            break
        seen += 1

        smiles_el = elem.find(f"{ns}smiles")
        inchi_el = elem.find(f"{ns}inchi")
        name_el = elem.find(f"{ns}name")
        smiles = smiles_el.text if smiles_el is not None else None
        inchi = inchi_el.text if inchi_el is not None else None
        name = name_el.text if name_el is not None else None

        mol = None
        if inchi and inchi.startswith("InChI="):
            mol = Chem.MolFromInchi(inchi)
        if mol is None and smiles:
            mol = Chem.MolFromSmiles(smiles)

        elem.clear()  # keep memory bounded across a multi-GB file

        if mol is None:
            failed += 1
            continue
        row = _mol_row(mol, "hmdb", name=name)
        if row is None:
            failed += 1
            continue
        rows.append(row)
        ok += 1
        _progress("hmdb", seen, ok, t0, progress_every)

    return rows, LoadStats("hmdb", seen, ok, failed)


def load_user_table(
    df, inchi_col: str | None = None, smiles_col: str | None = None,
    name_col: str | None = None, organism_col: str | None = None,
    source_label: str = "user", progress_every: int = 20000, progress_callback=None,
    progress_fraction_callback=None, progress_fraction_every: int | None = None,
) -> tuple[list[dict], LoadStats]:
    """
    Normalize an arbitrary user-supplied table (any columns) into the same
    schema as `load_dnp`/`load_lotus`/`load_hmdb`. At least one of `inchi_col`/
    `smiles_col` is required -- either is enough on its own, and both can be
    given at once (InChI tried first per row, SMILES as a fallback for that
    row if the InChI value is missing/unparseable). There's no equivalent
    `inchikey_col`: an InChIKey is a one-way hash, so a table that has only
    that (no InChI/SMILES) genuinely has no structure to recover -- it isn't a
    valid input on its own.

    Everything else in the schema (`inchikey`, canonical `smiles`, `formula`)
    is computed here via RDKit exactly like the other loaders, never trusted
    from the source table -- so a user's own formula/InChIKey columns, if any,
    are simply ignored; there's nothing to map them to.

    `progress_callback(message: str)` fires every `progress_every` rows (and
    once more at the end) -- a console/status-text line, cheap enough to stay
    coarse. `progress_fraction_callback(fraction: float)` -- the GUI's actual
    progress-bar percentage -- fires on its own, much finer cadence instead:
    every `progress_fraction_every` rows if given, else scaled to this
    table's own size (`max(1, total // 300)`, ~300 updates total) so a small
    table still updates smoothly and a huge one doesn't rack up hundreds of
    thousands of individual bar-update calls for no perceptible benefit (past
    a few hundred updates, a human can't tell the difference anyway -- the
    per-call cost of driving the bar that often is pure overhead). A full
    real-world library (hundreds of thousands of rows) can take tens of
    minutes to parse, so a visible fraction matters here, not just for the
    acylation step.
    """
    from rdkit import Chem

    if not inchi_col and not smiles_col:
        raise ValueError("load_user_table needs at least one of inchi_col/smiles_col")

    rows = []
    seen = ok = failed = 0
    t0 = time.time()
    total = len(df)
    fraction_every = progress_fraction_every or max(1, total // 300)

    for row in df.itertuples(index=False):
        seen += 1
        name = getattr(row, name_col) if name_col else None
        organism = getattr(row, organism_col) if organism_col else None

        mol = None
        if inchi_col:
            inchi_value = getattr(row, inchi_col)
            if isinstance(inchi_value, str) and inchi_value.strip():
                mol = Chem.MolFromInchi(inchi_value)
        if mol is None and smiles_col:
            smiles_value = getattr(row, smiles_col)
            if isinstance(smiles_value, str) and smiles_value.strip():
                mol = Chem.MolFromSmiles(smiles_value)
        if mol is None:
            failed += 1
            continue

        parsed_row = _mol_row(mol, source_label, name=name or None, organism=organism or None)
        if parsed_row is None:
            failed += 1
            continue
        rows.append(parsed_row)
        ok += 1
        if progress_every and seen % progress_every == 0:
            elapsed = time.time() - t0
            rate = seen / elapsed if elapsed > 0 else 0
            message = f"{seen}/{total} rows, {ok} parsed ok, {elapsed:.0f}s elapsed, {rate:.0f} rec/s"
            print(f"  [{source_label}] {message}", flush=True)
            if progress_callback:
                progress_callback(message)
        if progress_fraction_callback and seen % fraction_every == 0:
            progress_fraction_callback(seen / total if total else 1.0)

    elapsed = time.time() - t0
    done_message = f"Done: {seen}/{total} rows, {ok} parsed ok, {failed} failed ({elapsed:.0f}s elapsed)"
    print(f"  [{source_label}] {done_message}", flush=True)
    if progress_callback:
        progress_callback(done_message)
    if progress_fraction_callback:
        progress_fraction_callback(1.0)
    return rows, LoadStats(source_label, seen, ok, failed)


def merge_rows(all_rows: list[list[dict]]) -> "pandas.DataFrame":
    """
    Concatenate normalized rows from multiple sources and dedupe by inchikey,
    keeping the union of source_db's and the first non-null name/organism seen.

    Single-pass dict merge (not groupby().apply()) -- at hundreds of thousands
    of rows, per-group Python calls in groupby-apply are far too slow.
    """
    import pandas as pd

    merged: dict[str, dict] = {}
    for rows in all_rows:
        for r in rows:
            key = r["inchikey"]
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "inchikey": key,
                    "inchi": r["inchi"],
                    "smiles": r["smiles"],
                    "formula": r["formula"],
                    "name": r["name"],
                    "organism": r["organism"],
                    "source_db": {r["source_db"]},
                }
            else:
                existing["source_db"].add(r["source_db"])
                if not existing["name"] and r["name"]:
                    existing["name"] = r["name"]
                if not existing["organism"] and r["organism"]:
                    existing["organism"] = r["organism"]

    records = list(merged.values())
    for rec in records:
        rec["source_db"] = ",".join(sorted(rec["source_db"]))
    return pd.DataFrame(records)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Parse DNP/LOTUS/HMDB into one merged, deduplicated structure table.")
    p.add_argument("--dnp", help="path to dnp.tsv")
    p.add_argument("--lotus", help="path to LOTUS *.sdf")
    p.add_argument("--hmdb", help="path to hmdb_metabolites.xml")
    p.add_argument("--limit", type=int, default=None, help="limit records per source (for testing)")
    p.add_argument("-o", "--output", required=True,
                    help="output .parquet path -- this is input data for later steps (acylation, matching), "
                         "so it belongs under a module's data/ folder, not output/")
    p.add_argument("--csv", default=None,
                    help="also write a plain (uncompressed) human-readable .csv copy at this path")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    all_rows = []
    stats = []

    if args.dnp:
        print(f"Loading DNP from {args.dnp} ...", flush=True)
        rows, st = load_dnp(args.dnp, limit=args.limit)
        all_rows.append(rows)
        stats.append(st)
        print(f"  done: {st}", flush=True)

    if args.lotus:
        print(f"Loading LOTUS from {args.lotus} ...", flush=True)
        rows, st = load_lotus(args.lotus, limit=args.limit)
        all_rows.append(rows)
        stats.append(st)
        print(f"  done: {st}", flush=True)

    if args.hmdb:
        print(f"Loading HMDB from {args.hmdb} ...", flush=True)
        rows, st = load_hmdb(args.hmdb, limit=args.limit)
        all_rows.append(rows)
        stats.append(st)
        print(f"  done: {st}", flush=True)

    print("Merging + deduplicating by inchikey ...", flush=True)
    merged = merge_rows(all_rows)

    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    merged.to_parquet(args.output, index=False)

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        merged.to_csv(args.csv, index=False)
        print(f"Also wrote CSV -> {args.csv}")

    total_in = sum(len(r) for r in all_rows)
    print(f"\nMerged {total_in} normalized rows -> {len(merged)} unique structures -> {args.output}")
    print("Per-source stats:")
    for st in stats:
        print(f"  {st}")
    n_amine = int(compute_primary_amine_flags(merged["inchi"]).sum())
    print(f"Primary-amine-bearing structures: {n_amine} / {len(merged)}")
    print("Source DB combination counts:")
    print(merged["source_db"].value_counts().to_string())


if __name__ == "__main__":
    main()
