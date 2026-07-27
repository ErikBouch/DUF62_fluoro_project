"""
comparison/run_match.py — CLI wrapper around matcher.run_match_pipeline:
match the suspect library against local mzML files, producing a candidate table.

Run: python run_match.py [--limit N] [--tolerance F] [--unit Da|ppm]
                          [--check-acetyl-cooccurrence] [--acetyl-tolerance F] [--acetyl-unit Da|ppm]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.ui import find_mzml_files  # noqa: E402
from comparison.matcher import run_match_pipeline  # noqa: E402

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "insilico_library", "data")
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Match the suspect library against local mzML files.")
    p.add_argument("--library", default=os.path.join(_DATA_DIR, "suspect_library.parquet"))
    p.add_argument("--limit", type=int, default=None, help="limit library rows searched (for a quick test run)")
    p.add_argument("--tolerance", type=float, default=0.002, help="fluoroacetyl match tolerance (default: 0.002 Da)")
    p.add_argument("--unit", choices=["Da", "ppm"], default="Da")
    p.add_argument("--ms-level", type=int, default=1)
    p.add_argument("--min-rel-intensity", type=float, default=0.0)
    p.add_argument("--check-acetyl-cooccurrence", action="store_true",
                    help="also search for each fluoroacetyl hit's acetyl analog and flag co-occurrence")
    p.add_argument("--acetyl-tolerance", type=float, default=5.0, help="default: 5 ppm")
    p.add_argument("--acetyl-unit", choices=["Da", "ppm"], default="ppm")
    p.add_argument("-o", "--output", default=os.path.join(_OUTPUT_DIR, "candidate_table.parquet"))
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    import pandas as pd

    print(f"Loading {args.library} ...", flush=True)
    library = pd.read_parquet(args.library)
    if args.limit is not None:
        library = library.iloc[:args.limit]
    print(f"{len(library)} suspect-library rows loaded.", flush=True)

    discovered = find_mzml_files()
    if not discovered:
        print("No local mzML files found under data/HRMS/ -- nothing to match against.")
        return
    file_paths = [path for _label, path in discovered]

    candidate_table = run_match_pipeline(
        library, file_paths,
        fluoroacetyl_tolerance=args.tolerance, fluoroacetyl_unit=args.unit,
        ms_level=args.ms_level, min_relative_intensity=args.min_rel_intensity,
        check_acetyl_cooccurrence=args.check_acetyl_cooccurrence,
        acetyl_tolerance=args.acetyl_tolerance, acetyl_unit=args.acetyl_unit,
        progress_callback=print,
    )

    if candidate_table.empty:
        print("\nNo matches found.")
        return

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    candidate_table.to_parquet(args.output, index=False)
    csv_path = os.path.splitext(args.output)[0] + ".csv"
    candidate_table.to_csv(csv_path, index=False)

    print(f"\nTotal raw hits: {len(candidate_table)}")
    print(f"Distinct suspect-library products with >=1 hit: {candidate_table['product_inchikey'].nunique()}")
    print(f"Distinct parent compounds with >=1 hit: {candidate_table['parent_inchikey'].nunique()}")
    if args.check_acetyl_cooccurrence:
        print(f"Hits with acetyl co-occurrence: {int(candidate_table['acetyl_cooccurs'].sum())}")
    print(f"\nWrote {args.output}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
