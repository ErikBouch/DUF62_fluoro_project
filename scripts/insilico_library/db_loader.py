"""
insilico_library/db_loader.py — parse DNP / LOTUS / HMDB into one uniform,
deduplicated structure table.

Logic only (no Streamlit import). Each `load_*` function normalizes one source
into a common schema:
    inchi, inchikey, smiles, name, organism, source_db, formula, exact_mass, has_primary_amine

`inchikey`, canonical `smiles`, `formula`, `exact_mass`, and `has_primary_amine`
are always computed here via RDKit (not trusted from the source file), so
every row is uniform and structure-valid regardless of where it came from.
Rows RDKit can't parse are dropped (and counted).

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
    from rdkit.Chem import Descriptors, rdMolDescriptors

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
        "exact_mass": Descriptors.ExactMolWt(mol),
        "has_primary_amine": mol.HasSubstructMatch(Chem.MolFromSmarts(PRIMARY_AMINE_SMARTS)),
    }


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
                    "exact_mass": r["exact_mass"],
                    "has_primary_amine": r["has_primary_amine"],
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
    print(f"Primary-amine-bearing structures: {int(merged['has_primary_amine'].sum())} / {len(merged)}")
    print("Source DB combination counts:")
    print(merged["source_db"].value_counts().to_string())


if __name__ == "__main__":
    main()
