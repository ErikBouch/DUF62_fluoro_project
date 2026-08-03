"""
insilico_library/build_suspect_library.py — run the acetyl/fluoroacetyl
acylation reactions (acylation.py) over every primary-amine-bearing compound
in the merged structure table (db_loader.py's output), producing the suspect
library used for downstream mass matching.

Reads a merged/normalized structure table (data/unified_structures.parquet by
default, or any table produced by db_loader.py's loaders, including
`load_user_table` for an arbitrary user-supplied library) -- a plain
inchi/inchikey/smiles/formula/name/organism/source_db table, with no
has_primary_amine or exact_mass columns of its own (those aren't things any
source database supplies, so db_loader.py doesn't store them). Both are
computed here, right before they're needed: has_primary_amine to filter down
to the compounds actually worth reacting, exact_mass to carry through onto
each product row. For each has_primary_amine compound, runs both acylate()
reactions. Writes two tables (to output/ -- this is a computed result, not
input data):
    output/suspect_library.parquet
        One row per (parent compound, reaction, reactive site) -- the mono-
        acylation products, each with a real per-site InChI/SMILES/formula/
        mass and both [M+H]+ / [M-H]- adduct m/z values.
    output/suspect_library_multidegree.parquet
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

from insilico_library.acylation import REACTIONS, acylate, count_reactive_sites, multi_degree_formulas  # noqa: E402
from insilico_library.db_loader import compute_exact_mass_series, compute_primary_amine_flags  # noqa: E402

RDLogger.DisableLog("rdApp.*")

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Parent-compound columns carried through onto every product row, prefixed
# with "parent_" so they can't collide with the product's own columns.
PARENT_COLS = ["inchikey", "formula", "exact_mass", "name", "organism", "source_db"]


def build_library(
    df, progress_every: int = 2000, progress_callback=None, progress_fraction_callback=None,
    progress_fraction_every: int | None = None,
) -> tuple[list[dict], list[dict], int, int, int]:
    """
    Run both acylation reactions over every row of `df` (expected to already
    be filtered to primary-amine-bearing compounds).

    `progress_callback(message: str)`, if given, is called every
    `progress_every` rows with a short status string (e.g. for a GUI log) --
    a console/status-text cadence, cheap enough to stay coarse.
    `progress_fraction_callback(fraction: float)` -- the GUI's actual
    progress-bar percentage -- fires on its own, much finer cadence instead:
    every `progress_fraction_every` rows if given, else scaled to `df`'s own
    size (`max(1, total // 300)`, ~300 updates total), same reasoning as
    `db_loader.load_user_table`'s equivalent split -- a fixed tiny interval
    (e.g. every row) would mean hundreds of thousands of bar-update calls on
    a real library, for no benefit a human could actually perceive.

    Returns (mono_rows, multidegree_rows, n_processed, n_multisite, n_errors).
    """
    mono_rows: list[dict] = []
    multidegree_rows: list[dict] = []
    n_processed = 0
    n_multisite = 0
    n_errors = 0

    total = len(df)
    t0 = time.time()
    fraction_every = progress_fraction_every or max(1, total // 300)

    for row in df.itertuples(index=False):
        n_processed += 1
        try:
            mol = Chem.MolFromInchi(row.inchi)
            if mol is None:
                n_errors += 1
                continue

            parent = {f"parent_{col}": getattr(row, col) for col in PARENT_COLS}

            # The true reactive-site count, NOT `len(products)`: for a
            # symmetric multi-site molecule (a simple diamine, say -- two
            # equivalent amines), `acylate()` dedupes its output by product
            # InChIKey, so both sites yield the *same* product and
            # `len(products)` under-counts as 1 -- which silently skipped
            # the degree>=2 (both-ends-acylated) row for every symmetric
            # multi-site compound, `multi_degree_formulas()` (which counts
            # sites independently of product identity) never even being
            # called. Confirmed directly against a symmetric test diamine:
            # 2 reactive sites, 1 deduped mono-product, but a real degree-2
            # product that `multi_degree_formulas()` does compute correctly
            # once actually asked.
            max_sites = count_reactive_sites(mol)
            for reaction in REACTIONS:
                products = acylate(mol, reaction)
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
        if progress_fraction_callback and n_processed % fraction_every == 0:
            progress_fraction_callback(n_processed / total if total else 1.0)

    elapsed = time.time() - t0
    done_message = (f"Done: {n_processed}/{total} compounds processed, {len(mono_rows)} product rows "
                     f"({n_multisite} multi-site, {n_errors} errors), {elapsed:.0f}s elapsed")
    print(f"  {done_message}", flush=True)
    if progress_callback:
        progress_callback(done_message)
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
    p.add_argument("-o", "--output", default=os.path.join(_OUTPUT_DIR, "suspect_library.parquet"),
                   help="output path for the mono-acylation table")
    p.add_argument("--output-multidegree", default=os.path.join(_OUTPUT_DIR, "suspect_library_multidegree.parquet"),
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
    # `--limit` slices *before* the RDKit primary-amine/mass computation, not
    # after -- both run over the whole table otherwise, defeating the whole
    # point of "a quick test run" (its own --help text) for a real,
    # hundreds-of-thousands-of-rows library, where that computation alone is
    # the expensive part, not the acylation step limit was actually bounding.
    if args.limit is not None:
        df = df.iloc[:args.limit]
    df = df[compute_primary_amine_flags(df["inchi"])].reset_index(drop=True)
    df["exact_mass"] = compute_exact_mass_series(df["inchi"])
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
