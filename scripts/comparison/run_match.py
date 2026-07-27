"""
comparison/run_match.py — match the suspect library (insilico_library's
mono-acylation table) against any local mzML files under data/HRMS/,
producing a candidate table.

For each discovered file, the appropriate adduct column (positive or negative,
based on that file's dominant polarity) is matched against every MS1 spectrum
via matcher.match_library_to_file (efficient at library scale -- see that
module's docstring). Results are joined back to the full suspect-library row
so each hit carries its parent/product formula, masses, and reaction type.

Run: python run_match.py [--limit N] [--tolerance-ppm P] [--min-rel-intensity F]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.ui import find_mzml_files  # noqa: E402
from comparison.matcher import match_library_to_file  # noqa: E402
from mzml_tools.scan_detector import get_file_overview  # noqa: E402

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "insilico_library", "data")
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Match the suspect library against local mzML files.")
    p.add_argument("--library", default=os.path.join(_DATA_DIR, "suspect_library.parquet"))
    p.add_argument("--limit", type=int, default=None, help="limit library rows searched (for a quick test run)")
    p.add_argument("--tolerance-ppm", type=float, default=25.0)
    p.add_argument("--min-rel-intensity", type=float, default=0.01)
    p.add_argument("-o", "--output", default=os.path.join(_OUTPUT_DIR, "candidate_table.parquet"))
    return p


def main(argv=None):
    import pandas as pd

    args = _build_parser().parse_args(argv)

    print(f"Loading {args.library} ...", flush=True)
    library = pd.read_parquet(args.library)
    if args.limit is not None:
        library = library.iloc[:args.limit]
    print(f"{len(library)} suspect-library rows to search.", flush=True)

    discovered = find_mzml_files()
    if not discovered:
        print("No local mzML files found under data/HRMS/ -- nothing to match against.")
        return

    all_hits = []
    for file_label, path in discovered:
        overview = get_file_overview(path)
        polarity = max(overview.polarity_counts, key=overview.polarity_counts.get, default=None)
        if polarity not in ("+", "-"):
            continue
        mz_col = "mz_pos_m_plus_h" if polarity == "+" else "mz_neg_m_minus_h"

        targets = list(zip(library["product_inchikey"], library[mz_col]))
        print(f"\nSearching {file_label} ({polarity}, {len(targets)} targets, MS1, "
              f"{args.tolerance_ppm:g}ppm, >= {args.min_rel_intensity:.0%} rel. intensity)...", flush=True)

        t0 = time.time()
        matches = match_library_to_file(
            path, targets, tolerance_ppm=args.tolerance_ppm, ms_level=1,
            min_relative_intensity=args.min_rel_intensity,
        )
        print(f"  {len(matches)} raw peak-target matches in {time.time() - t0:.1f}s", flush=True)

        for m in matches:
            all_hits.append({
                "file": file_label,
                "polarity": polarity,
                "product_inchikey": m.target_label,
                "scan_index": m.scan_index,
                "rt_minutes": m.rt_minutes,
                "matched_mz": m.matched_mz,
                "target_mz": m.target_mz,
                "ppm_error": m.ppm_error,
                "intensity": m.intensity,
                "relative_intensity": m.relative_intensity,
            })

    if not all_hits:
        print("\nNo matches found.")
        return

    hits_df = pd.DataFrame(all_hits)
    candidate_table = hits_df.merge(library, on="product_inchikey", how="left")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    candidate_table.to_parquet(args.output, index=False)
    csv_path = os.path.splitext(args.output)[0] + ".csv"
    candidate_table.to_csv(csv_path, index=False)

    print(f"\nTotal raw hits: {len(candidate_table)}")
    print(f"Distinct suspect-library products with >=1 hit: {candidate_table['product_inchikey'].nunique()}")
    print(f"Distinct parent compounds with >=1 hit: {candidate_table['parent_inchikey'].nunique()}")
    print("By reaction:")
    print(candidate_table.drop_duplicates("product_inchikey")["reaction"].value_counts().to_string())
    print(f"\nWrote {args.output}")
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
