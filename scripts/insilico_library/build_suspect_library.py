"""
insilico_library/build_suspect_library.py — run the acetyl/fluoroacetyl
acylation reactions (acylation.py) over every primary-amine-bearing compound
in the merged structure table (db_loader.py's output), producing the suspect
library used for downstream mass matching.

Reads data/unified_structures.parquet, filters to has_primary_amine == True,
and for each remaining compound runs both acylate() reactions. Writes two
tables:
    data/suspect_library.parquet
        One row per (parent compound, reaction, reactive site) -- the mono-
        acylation products, each with a real per-site InChI/SMILES/formula/
        mass and both [M+H]+ / [M-H]- adduct m/z values.
    data/suspect_library_multidegree.parquet
        Formula/mass only (no structure), one row per (parent compound,
        reaction, degree) for degree >= 2 -- only present for compounds with
        more than one independent reactive site.

Each compound is processed independently inside a try/except so a single
unparseable structure or failed reaction does not abort the run; failures are
counted and reported in the final summary.

CLI:
    python build_suspect_library.py [--input <path>] [--limit N]
        [--progress-every N] [-o <mono_out.parquet>] [--output-multidegree <path>]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rdkit import Chem, RDLogger  # noqa: E402

from insilico_library.acylation import REACTIONS, acylate, multi_degree_formulas  # noqa: E402

RDLogger.DisableLog("rdApp.*")

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Parent-compound columns carried through onto every product row, prefixed
# with "parent_" so they can't collide with the product's own columns.
PARENT_COLS = ["inchikey", "formula", "exact_mass", "name", "organism", "source_db"]


def build_library(
    df, progress_every: int = 2000, progress_callback=None, progress_fraction_callback=None,
) -> tuple[list[dict], list[dict], int, int, int]:
    """
    Run both acylation reactions over every row of `df` (expected to already
    be filtered to primary-amine-bearing compounds).

    `progress_callback(message: str)`, if given, is called every
    `progress_every` rows with a short status string (e.g. for a GUI log).
    `progress_fraction_callback(fraction: float)`, if given, is called at the
    same checkpoints with the 0.0-1.0 fraction of rows processed so far, for
    driving an actual progress bar.

    Returns (mono_rows, multidegree_rows, n_processed, n_multisite, n_errors).
    """
    mono_rows: list[dict] = []
    multidegree_rows: list[dict] = []
    n_processed = 0
    n_multisite = 0
    n_errors = 0

    total = len(df)
    t0 = time.time()

    for row in df.itertuples(index=False):
        n_processed += 1
        try:
            mol = Chem.MolFromInchi(row.inchi)
            if mol is None:
                n_errors += 1
                continue

            parent = {f"parent_{col}": getattr(row, col) for col in PARENT_COLS}

            max_sites = 0
            for reaction in REACTIONS:
                products = acylate(mol, reaction)
                max_sites = max(max_sites, len(products))
                for site_index, product in enumerate(products):
                    mono_rows.append({
                        **parent,
                        "reaction": product.reaction,
                        "site_index": site_index,
                        "product_inchi": product.product_inchi,
                        "product_inchikey": product.product_inchikey,
                        "product_smiles": product.product_smiles,
                        "product_formula": product.product_formula,
                        "product_exact_mass": product.product_exact_mass,
                        "mz_pos_m_plus_h": product.mz_pos_m_plus_h,
                        "mz_neg_m_minus_h": product.mz_neg_m_minus_h,
                    })

            if max_sites > 1:
                n_multisite += 1
                for reaction in REACTIONS:
                    for degree_formula in multi_degree_formulas(mol, reaction):
                        if degree_formula.degree < 2:
                            continue
                        multidegree_rows.append({
                            "parent_inchikey": row.inchikey,
                            "reaction": degree_formula.reaction,
                            "degree": degree_formula.degree,
                            "formula": degree_formula.formula,
                            "exact_mass": degree_formula.exact_mass,
                            "mz_pos_m_plus_h": degree_formula.mz_pos_m_plus_h,
                            "mz_neg_m_minus_h": degree_formula.mz_neg_m_minus_h,
                        })
        except Exception:
            n_errors += 1
            continue

        if progress_every and n_processed % progress_every == 0:
            elapsed = time.time() - t0
            rate = n_processed / elapsed if elapsed > 0 else 0
            message = (f"{n_processed}/{total} compounds processed, {len(mono_rows)} product rows so far, "
                       f"{elapsed:.0f}s elapsed, {rate:.1f} compounds/s")
            print(f"  {message}", flush=True)
            if progress_callback:
                progress_callback(message)
            if progress_fraction_callback:
                progress_fraction_callback(n_processed / total if total else 1.0)

    if progress_fraction_callback:
        progress_fraction_callback(1.0)
    return mono_rows, multidegree_rows, n_processed, n_multisite, n_errors


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build the acetyl/fluoroacetyl suspect library from the merged structure table."
    )
    p.add_argument("--input", default=os.path.join(_DATA_DIR, "unified_structures.parquet"),
                   help="path to the merged structure table (db_loader.py output)")
    p.add_argument("--limit", type=int, default=None,
                   help="limit the number of primary-amine compounds processed (for a quick test run)")
    p.add_argument("--progress-every", type=int, default=2000)
    p.add_argument("-o", "--output", default=os.path.join(_DATA_DIR, "suspect_library.parquet"),
                   help="output path for the mono-acylation table")
    p.add_argument("--output-multidegree", default=os.path.join(_DATA_DIR, "suspect_library_multidegree.parquet"),
                   help="output path for the degree>=2 formula-only table")
    p.add_argument("--csv", default=None,
                   help="also write a plain (uncompressed) human-readable .csv copy of the mono-acylation table")
    p.add_argument("--csv-multidegree", default=None,
                   help="also write a plain .csv copy of the degree>=2 formula-only table")
    return p


def main(argv=None):
    import pandas as pd

    args = _build_parser().parse_args(argv)

    print(f"Loading {args.input} ...", flush=True)
    df = pd.read_parquet(args.input)
    df = df[df["has_primary_amine"]].reset_index(drop=True)
    if args.limit is not None:
        df = df.iloc[:args.limit]
    print(f"{len(df)} primary-amine compound(s) to process.", flush=True)

    mono_rows, multidegree_rows, n_processed, n_multisite, n_errors = build_library(
        df, progress_every=args.progress_every
    )

    mono_df = pd.DataFrame(mono_rows)
    multidegree_df = pd.DataFrame(multidegree_rows)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    mono_df.to_parquet(args.output, index=False)
    os.makedirs(os.path.dirname(args.output_multidegree) or ".", exist_ok=True)
    multidegree_df.to_parquet(args.output_multidegree, index=False)

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        mono_df.to_csv(args.csv, index=False)
        print(f"Also wrote CSV -> {args.csv}")
    if args.csv_multidegree:
        os.makedirs(os.path.dirname(args.csv_multidegree) or ".", exist_ok=True)
        multidegree_df.to_csv(args.csv_multidegree, index=False)
        print(f"Also wrote CSV -> {args.csv_multidegree}")

    print()
    print(f"Parent compounds processed: {n_processed}")
    print(f"Mono-acylation product rows: {len(mono_df)} -> {args.output}")
    print(f"Parents with >1 reactive site (also present in multidegree table): {n_multisite}")
    print(f"Multidegree formula rows (degree>=2): {len(multidegree_df)} -> {args.output_multidegree}")
    print(f"Errors (skipped, did not abort the run): {n_errors}")


if __name__ == "__main__":
    main()
