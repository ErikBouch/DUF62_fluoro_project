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
from comparison import plotting  # noqa: E402
from comparison.matcher import (  # noqa: E402
    collapse_to_features, filter_acetyl_cooccurring, format_summary, run_match_pipeline,
    scan_count_breakdown, summarize_candidate_table, top_structures_by_formula,
)

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
    p.add_argument("--min-intensity", type=float, default=50_000.0,
                    help="minimum absolute peak intensity to count as a hit, raw instrument units "
                         "(default: 50000; 0 disables)")
    p.add_argument("--min-consecutive-scans", type=int, default=3,
                    help="drop hits not part of a run of at least this many scans in a row "
                         "for the same file+product, within --max-rt-gap of each other "
                         "(default: 3; 1 disables)")
    p.add_argument("--check-acetyl-cooccurrence", action="store_true",
                    help="also search for each fluoroacetyl hit's acetyl analog and flag co-occurrence")
    p.add_argument("--acetyl-tolerance", type=float, default=5.0, help="default: 5 ppm")
    p.add_argument("--acetyl-unit", choices=["Da", "ppm"], default="ppm")
    p.add_argument("--acetyl-rt-window", type=float, default=2.0,
                    help="the acetyl analog only counts as co-occurring if found within this many "
                         "minutes of the fluoroacetyl hit's own RT (default: 2.0)")
    p.add_argument("-o", "--output", default=os.path.join(_OUTPUT_DIR, "candidate_table.parquet"))
    p.add_argument("--collapse-to-features", action="store_true",
                    help="also collapse raw per-scan hits into one row per contiguous elution event "
                         "(same file + product, RT within --max-rt-gap of each other)")
    p.add_argument("--max-rt-gap", type=float, default=0.1,
                    help="RT gap (minutes) allowed within one feature when collapsing (default: 0.1)")
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
        min_absolute_intensity=args.min_intensity or None,
        min_consecutive_scans=args.min_consecutive_scans, max_rt_gap_minutes=args.max_rt_gap,
        check_acetyl_cooccurrence=args.check_acetyl_cooccurrence,
        acetyl_tolerance=args.acetyl_tolerance, acetyl_unit=args.acetyl_unit,
        acetyl_rt_window_minutes=args.acetyl_rt_window,
        progress_callback=print,
    )

    if candidate_table.empty:
        print("\nNo matches found.")
        return

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    candidate_table.to_parquet(args.output, index=False)
    csv_path = os.path.splitext(args.output)[0] + ".csv"
    candidate_table.to_csv(csv_path, index=False)

    summary_text = format_summary(summarize_candidate_table(candidate_table))
    summary_path = os.path.join(os.path.dirname(args.output) or ".", "candidate_table_summary.txt")
    with open(summary_path, "w") as f:
        f.write(summary_text + "\n")

    print(f"\n{summary_text}")
    print(f"\nWrote {args.output}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {summary_path}")

    if args.check_acetyl_cooccurrence:
        cooccurring = filter_acetyl_cooccurring(candidate_table)
        cooc_path = os.path.join(os.path.dirname(args.output) or ".", "candidate_table_acetyl_cooccurring.parquet")
        cooc_csv_path = os.path.splitext(cooc_path)[0] + ".csv"
        cooccurring.to_parquet(cooc_path, index=False)
        cooccurring.to_csv(cooc_csv_path, index=False)
        print(f"\n{len(cooccurring)} of {len(candidate_table)} raw hits have acetyl co-occurrence "
              f"(within {args.acetyl_rt_window} min).")
        print(f"Wrote {cooc_path}")
        print(f"Wrote {cooc_csv_path}")

    if args.collapse_to_features:
        features_df = collapse_to_features(candidate_table, max_rt_gap_minutes=args.max_rt_gap)
        features_path = os.path.join(os.path.dirname(args.output) or ".", "candidate_features.parquet")
        features_csv_path = os.path.splitext(features_path)[0] + ".csv"
        features_df.to_parquet(features_path, index=False)
        features_df.to_csv(features_csv_path, index=False)
        print(f"\nCollapsed to {len(features_df)} features (from {len(candidate_table)} raw hits, "
              f"max RT gap {args.max_rt_gap} min).")
        print(f"Wrote {features_path}")
        print(f"Wrote {features_csv_path}")

        if args.check_acetyl_cooccurrence:
            features_cooccurring = filter_acetyl_cooccurring(features_df)
            features_cooc_path = os.path.join(
                os.path.dirname(args.output) or ".", "candidate_features_acetyl_cooccurring.parquet",
            )
            features_cooc_csv_path = os.path.splitext(features_cooc_path)[0] + ".csv"
            features_cooccurring.to_parquet(features_cooc_path, index=False)
            features_cooccurring.to_csv(features_cooc_csv_path, index=False)
            print(f"\n{len(features_cooccurring)} of {len(features_df)} features have acetyl co-occurrence.")
            print(f"Wrote {features_cooc_path}")
            print(f"Wrote {features_cooc_csv_path}")
    else:
        features_df = collapse_to_features(candidate_table, max_rt_gap_minutes=args.max_rt_gap)

    # Summary figures are built from the final, most-filtered result -- if the
    # acetyl co-occurrence check ran, that means the co-occurring subset, not
    # the raw pre-acetyl-check features.
    if not features_df.empty and features_df["acetyl_cooccurs"].notna().any():
        features_for_summary = filter_acetyl_cooccurring(features_df)
    else:
        features_for_summary = features_df

    figures_dir = os.path.join(os.path.dirname(args.output) or ".", "figures")
    thresholds = tuple(sorted({args.min_consecutive_scans, 50, 100, 200, 500}))
    breakdown = scan_count_breakdown(candidate_table, thresholds=thresholds, features_table=features_for_summary)
    plotting.save_scan_count_breakdown_figure(breakdown, os.path.join(figures_dir, "scan_count_breakdown.png"))

    top_structures = top_structures_by_formula(candidate_table, top_n=10, features_table=features_for_summary)
    grid_image = plotting.build_top_structures_grid_image(top_structures)
    plotting.save_top_structures_grid(grid_image, os.path.join(figures_dir, "top_structures.png"))

    plotting.save_feature_map_figure(
        features_df, "apex_rt_minutes", "product_exact_mass", "apex_intensity",
        os.path.join(figures_dir, "feature_map.png"),
    )
    print(f"\nWrote figures to {figures_dir}")


if __name__ == "__main__":
    main()
