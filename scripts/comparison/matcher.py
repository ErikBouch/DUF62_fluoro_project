"""
comparison/matcher.py — match a large list of target masses against mzML
files efficiently, and run the full suspect-library matching pipeline
(multiple files, fluoroacetyl/acetyl tolerances, optional co-occurrence check).

`mzml_tools.scan_detector.find_scans_with_multiple_mz` checks every target
against every spectrum -- fine for a handful of targets, far too slow once the
target list is a whole suspect library (tens of thousands of masses): cost
there scales as O(spectra * targets). `match_library_to_file` instead sorts
the target masses once and, for each spectrum, does a binary search per peak
to find which targets (if any) it matches -- O(spectra * peaks * log(targets)),
which stays fast even at library scale since a spectrum's peak count is
usually much smaller than the target count.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_POLARITY = {0: "unknown", 1: "+", 2: "-"}


@dataclass
class LibraryMatch:
    target_label: str
    target_mz: float
    scan_index: int
    native_id: str
    ms_level: int
    polarity: str
    rt_minutes: float
    matched_mz: float
    intensity: float
    base_peak_intensity: float
    relative_intensity: float
    precursor_mz: float | None
    ppm_error: float


def _tolerance_delta(mz: float, tolerance: float, unit: str) -> float:
    if unit == "ppm":
        return mz * tolerance / 1e6
    if unit == "Da":
        return tolerance
    raise ValueError(f"unknown tolerance unit {unit!r} (use 'ppm' or 'Da')")


def load_experiment(mzml_path: str):
    """Load an mzML file once, for reuse across multiple matches/polarity checks."""
    from pyopenms import MSExperiment, MzMLFile

    exp = MSExperiment()
    MzMLFile().load(str(mzml_path), exp)
    return exp


def detect_polarity(exp) -> str | None:
    """Dominant polarity ('+'/'-') of an already-loaded experiment, or None if unclear."""
    counts: dict = {}
    for spec in exp:
        pol = _POLARITY.get(int(spec.getInstrumentSettings().getPolarity()), "unknown")
        counts[pol] = counts.get(pol, 0) + 1
    dominant = max(counts, key=counts.get, default=None)
    return dominant if dominant in ("+", "-") else None


def match_experiment(
    exp,
    targets: list[tuple],
    tolerance: float = 0.002,
    unit: str = "Da",
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
    min_absolute_intensity: float | None = None,
    progress_callback=None,
) -> list[LibraryMatch]:
    """
    Same as `match_library_to_file`, but against an already-loaded experiment
    (see `load_experiment`) -- use this when matching the same file against
    more than one target list, to avoid loading it from disk more than once.

    Parameters
    ----------
    targets : list[(label, target_mz)] -- can be tens of thousands of entries.
    tolerance, unit : float, str -- 'Da' (absolute) or 'ppm'.
    ms_level : int | None -- restrict to this MS level; None = all levels.
    min_relative_intensity : float | None -- minimum peak intensity as a
        fraction of that spectrum's base peak; None = no filter.
    min_absolute_intensity : float | None -- minimum peak intensity in raw
        instrument units; None = no filter. Independent of, and applied in
        addition to, `min_relative_intensity`.
    progress_callback : callable(float) | None -- called with the fraction
        (0.0-1.0) of this experiment's spectra processed so far, throttled to
        at most ~100 calls regardless of spectrum count, for driving a
        progress bar over a single (potentially multi-minute) file's match.

    Returns
    -------
    list[LibraryMatch] -- one entry per (matching peak, target) pair; a single
    peak can match more than one target if their tolerance windows overlap.
    """
    labels = np.array([t[0] for t in targets], dtype=object)
    masses = np.array([t[1] for t in targets], dtype=float)
    order = np.argsort(masses)
    sorted_masses = masses[order]
    sorted_labels = labels[order]

    total_spectra = exp.size()
    report_every = max(total_spectra // 100, 1)

    results: list[LibraryMatch] = []
    for i, spec in enumerate(exp):
        if progress_callback is not None and i % report_every == 0:
            progress_callback(i / total_spectra if total_spectra else 1.0)
        if ms_level is not None and spec.getMSLevel() != ms_level:
            continue
        mzs, intensities = spec.get_peaks()
        if len(mzs) == 0:
            continue

        base_peak = float(intensities.max())
        rt_minutes = spec.getRT() / 60.0
        precursors = spec.getPrecursors()
        precursor_mz = float(precursors[0].getMZ()) if precursors else None
        polarity = _POLARITY.get(int(spec.getInstrumentSettings().getPolarity()), "unknown")

        for peak_mz, peak_intensity in zip(mzs, intensities):
            rel_intensity = float(peak_intensity) / base_peak if base_peak > 0 else 0.0
            if min_relative_intensity is not None and rel_intensity < min_relative_intensity:
                continue
            if min_absolute_intensity is not None and peak_intensity < min_absolute_intensity:
                continue

            delta = _tolerance_delta(peak_mz, tolerance, unit)
            lo = np.searchsorted(sorted_masses, peak_mz - delta, side="left")
            hi = np.searchsorted(sorted_masses, peak_mz + delta, side="right")
            if hi <= lo:
                continue

            for idx in range(lo, hi):
                target_mz = float(sorted_masses[idx])
                results.append(
                    LibraryMatch(
                        target_label=sorted_labels[idx],
                        target_mz=target_mz,
                        scan_index=i,
                        native_id=spec.getNativeID(),
                        ms_level=spec.getMSLevel(),
                        polarity=polarity,
                        rt_minutes=rt_minutes,
                        matched_mz=float(peak_mz),
                        intensity=float(peak_intensity),
                        base_peak_intensity=base_peak,
                        relative_intensity=rel_intensity,
                        precursor_mz=precursor_mz,
                        ppm_error=(peak_mz - target_mz) / target_mz * 1e6,
                    )
                )
    if progress_callback is not None:
        progress_callback(1.0)
    return results


def match_library_to_file(
    mzml_path: str,
    targets: list[tuple],
    tolerance: float = 0.002,
    unit: str = "Da",
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
    min_absolute_intensity: float | None = None,
) -> list[LibraryMatch]:
    """Convenience one-call version of `match_experiment`: loads `mzml_path`,
    matches once, and discards the loaded experiment. If you need to match the
    same file against more than one target list, use `load_experiment` +
    `match_experiment` directly instead, to avoid loading it more than once."""
    exp = load_experiment(mzml_path)
    return match_experiment(exp, targets, tolerance, unit, ms_level, min_relative_intensity, min_absolute_intensity)


def run_match_pipeline(
    library_df,
    file_paths: list[str],
    fluoroacetyl_tolerance: float = 0.002,
    fluoroacetyl_unit: str = "Da",
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
    min_absolute_intensity: float | None = None,
    min_consecutive_scans: int = 1,
    max_rt_gap_minutes: float = 0.1,
    check_acetyl_cooccurrence: bool = False,
    acetyl_tolerance: float = 5.0,
    acetyl_unit: str = "ppm",
    acetyl_rt_window_minutes: float = 2.0,
    progress_callback=None,
    progress_fraction_callback=None,
) -> "pandas.DataFrame":
    """
    Match the suspect library (`library_df`, as built by
    insilico_library.build_suspect_library) against every file in
    `file_paths`, filtered to `reaction == 'fluoroacetyl'` as the primary
    target set. If `check_acetyl_cooccurrence` is set, also searches the
    `reaction == 'acetyl'` rows (with their own, typically looser, tolerance)
    and flags each fluoroacetyl hit with whether its sibling acetyl product
    (same parent compound, same reactive site) was also detected **within
    `acetyl_rt_window_minutes` of that hit's own RT** in the same file --
    structurally near-identical compounds (same skeleton, just a different
    acyl group) should co-elute or nearly so, so an acetyl match at a wildly
    different retention time isn't real co-occurrence evidence.

    `min_absolute_intensity` (raw instrument units) filters out weak peaks
    before they're even counted as a hit, same as `min_relative_intensity`
    but not scan-relative. `min_consecutive_scans` (>1) additionally drops
    hits that aren't part of a run of at least that many scans in a row for
    the same (file, product) -- see `collapse_to_features` for how "in a row"
    is defined (RT proximity within `max_rt_gap_minutes`, since raw scan
    indices aren't reliable once MS1/MS2 scans interleave). A lone-scan or
    two-scan match is much more likely to be noise or a coincidental overlap
    than a real chromatographic feature.

    `progress_callback(message: str)`, if given, is called once per file with
    a short status string (e.g. for a GUI spinner/log).
    `progress_fraction_callback(fraction: float)`, if given, is called
    frequently with the overall 0.0-1.0 fraction of work done across every
    file and match step (including within-file spectrum-by-spectrum progress
    from `match_experiment`) -- for driving an actual progress bar, as
    opposed to `progress_callback`'s per-file status messages.

    Returns a DataFrame: one row per (file, fluoroacetyl hit), joined with the
    full library row (parent/product formula, masses, etc.), plus
    `acetyl_cooccurs` (bool, only meaningful if the check was enabled).

    Note: `product_inchikey` is NOT used as the join key -- different parent
    compounds (e.g. a salt form vs. the free base) can react to an identical
    product structure, so it is not guaranteed unique within the library.
    The library's own row index is used instead, which is unique by
    construction, then dropped from the final table.
    """
    import pandas as pd

    library_df = library_df.reset_index(drop=True)
    fluoro_lib = library_df[library_df["reaction"] == "fluoroacetyl"]
    acetyl_lib = library_df[library_df["reaction"] == "acetyl"]
    # (parent_inchikey, site_index) -> acetyl_lib's row index, for the co-occurrence lookup
    acetyl_key_to_row = (
        {(row.parent_inchikey, row.site_index): idx for idx, row in acetyl_lib.iterrows()}
        if len(acetyl_lib)
        else {}
    )

    n_files = len(file_paths)
    steps_per_file = 2 if (check_acetyl_cooccurrence and len(acetyl_lib)) else 1
    total_steps = max(n_files * steps_per_file, 1)
    completed_steps = 0

    def _report_step_progress(step_fraction: float):
        if progress_fraction_callback is not None:
            progress_fraction_callback(min((completed_steps + step_fraction) / total_steps, 1.0))

    all_rows = []
    for path in file_paths:
        if progress_callback:
            progress_callback(f"Loading {path} ...")
        exp = load_experiment(path)  # loaded once, reused below for polarity + both matches
        polarity = detect_polarity(exp)
        if polarity is None:
            if progress_callback:
                progress_callback(f"Skipped {path}: no clear polarity.")
            completed_steps += steps_per_file
            _report_step_progress(0.0)
            continue
        mz_col = "mz_pos_m_plus_h" if polarity == "+" else "mz_neg_m_minus_h"

        fluoro_targets = list(zip(fluoro_lib.index, fluoro_lib[mz_col]))
        if progress_callback:
            progress_callback(f"Matching {len(fluoro_targets)} fluoroacetyl targets against {path} ...")
        fluoro_matches = match_experiment(
            exp, fluoro_targets, fluoroacetyl_tolerance, fluoroacetyl_unit,
            ms_level, min_relative_intensity, min_absolute_intensity,
            progress_callback=_report_step_progress,
        )
        completed_steps += 1
        _report_step_progress(0.0)

        acetyl_rt_by_label: dict = {}
        if check_acetyl_cooccurrence and len(acetyl_lib):
            acetyl_targets = list(zip(acetyl_lib.index, acetyl_lib[mz_col]))
            if progress_callback:
                progress_callback(f"Checking acetyl co-occurrence ({len(acetyl_targets)} targets) in {path} ...")
            acetyl_matches = match_experiment(
                exp, acetyl_targets, acetyl_tolerance, acetyl_unit,
                ms_level, min_relative_intensity, min_absolute_intensity,
                progress_callback=_report_step_progress,
            )
            completed_steps += 1
            _report_step_progress(0.0)
            for m in acetyl_matches:
                acetyl_rt_by_label.setdefault(m.target_label, []).append(m.rt_minutes)
            acetyl_rt_by_label = {k: np.sort(np.array(v)) for k, v in acetyl_rt_by_label.items()}

        for m in fluoro_matches:
            all_rows.append({
                "file": path,
                "polarity": polarity,
                "_library_row": m.target_label,
                "scan_index": m.scan_index,
                "rt_minutes": m.rt_minutes,
                "matched_mz": m.matched_mz,
                "target_mz": m.target_mz,
                "ppm_error": m.ppm_error,
                "intensity": m.intensity,
                "relative_intensity": m.relative_intensity,
                "_acetyl_rt_by_label": acetyl_rt_by_label,  # dropped after the join below
            })

    if not all_rows:
        return pd.DataFrame()

    hits_df = pd.DataFrame(all_rows)
    acetyl_rt_maps_by_row = hits_df.pop("_acetyl_rt_by_label")
    candidate_table = hits_df.merge(
        library_df, left_on="_library_row", right_index=True, how="left"
    )

    if check_acetyl_cooccurrence:
        cooccurs = []
        for row, rt_map in zip(candidate_table.itertuples(), acetyl_rt_maps_by_row):
            sibling_row = acetyl_key_to_row.get((row.parent_inchikey, row.site_index))
            acetyl_rts = rt_map.get(sibling_row) if sibling_row is not None else None
            if acetyl_rts is None or len(acetyl_rts) == 0:
                cooccurs.append(False)
                continue
            lo = np.searchsorted(acetyl_rts, row.rt_minutes - acetyl_rt_window_minutes, side="left")
            hi = np.searchsorted(acetyl_rts, row.rt_minutes + acetyl_rt_window_minutes, side="right")
            cooccurs.append(hi > lo)
        candidate_table["acetyl_cooccurs"] = cooccurs
    else:
        candidate_table["acetyl_cooccurs"] = None

    candidate_table = candidate_table.drop(columns=["_library_row"])
    if min_consecutive_scans > 1:
        candidate_table = filter_min_consecutive_scans(
            candidate_table, min_consecutive_scans, max_rt_gap_minutes,
        )
    return candidate_table


def filter_acetyl_cooccurring(candidate_table):
    """The subset of rows where the acetyl analog also co-occurs (see
    `run_match_pipeline`'s `acetyl_rt_window_minutes`) -- the chemistry
    sanity-check subset, on its own for easy export."""
    if candidate_table.empty or "acetyl_cooccurs" not in candidate_table.columns:
        return candidate_table.iloc[0:0]
    mask = candidate_table["acetyl_cooccurs"].fillna(False).astype(bool)
    return candidate_table[mask].reset_index(drop=True)


def summarize_candidate_table(candidate_table) -> dict:
    """
    Explain what a raw hit count actually counts: `run_match_pipeline` emits
    one row per (file, MS1 scan, library target) match, so the same eluting
    peak typically contributes one row per scan it spans -- the raw row count
    is not a compound count and is expected to be much larger than the number
    of distinct products/parents actually detected.

    Returns a dict of scalar stats; `format_summary` renders it as text.
    """
    if candidate_table.empty:
        return {"total_raw_hits": 0}

    per_file_product = candidate_table.groupby(["file", "product_inchikey"]).size()
    stats = {
        "total_raw_hits": len(candidate_table),
        "distinct_files": candidate_table["file"].nunique(),
        "distinct_file_scan_pairs": candidate_table.groupby(["file", "scan_index"]).ngroups,
        "distinct_products": candidate_table["product_inchikey"].nunique(),
        "distinct_parents": candidate_table["parent_inchikey"].nunique(),
        "file_product_pairs": len(per_file_product),
        "hits_per_file_product_mean": float(per_file_product.mean()),
        "hits_per_file_product_median": float(per_file_product.median()),
        "hits_per_file_product_max": int(per_file_product.max()),
    }
    if candidate_table["acetyl_cooccurs"].notna().any():
        stats["hits_with_acetyl_cooccurrence"] = int(candidate_table["acetyl_cooccurs"].sum())
    return stats


def format_summary(stats: dict) -> str:
    """Render `summarize_candidate_table`'s output as a short human-readable report."""
    if stats.get("total_raw_hits", 0) == 0:
        return "No matches found."

    lines = [
        "Match summary",
        "=============",
        f"Files matched: {stats['distinct_files']}",
        f"Total raw hits (one row per file x MS1 scan x library target match): {stats['total_raw_hits']:,}",
        "  This is NOT a compound count -- a single chromatographic peak typically",
        "  produces one hit per scan it spans, so this number is inflated by",
        "  repeated per-scan detection of the same underlying feature.",
        f"Distinct (file, scan) pairs with >=1 hit: {stats['distinct_file_scan_pairs']:,}",
        f"Distinct fluoroacetyl products matched: {stats['distinct_products']:,}",
        f"Distinct parent compounds matched: {stats['distinct_parents']:,}",
        f"Hits per (file, product) pair: median {stats['hits_per_file_product_median']:.0f}, "
        f"mean {stats['hits_per_file_product_mean']:.1f}, max {stats['hits_per_file_product_max']:,}",
        "  A high count for one pair usually means a broad chromatographic peak",
        "  spanning many scans, or a persistent background/isobaric ion present in",
        "  nearly every scan -- not necessarily a stronger signal. Use",
        "  `collapse_to_features` to turn this into one row per elution event.",
    ]
    if "hits_with_acetyl_cooccurrence" in stats:
        pct = 100 * stats["hits_with_acetyl_cooccurrence"] / stats["total_raw_hits"]
        lines.append(f"Hits with acetyl co-occurrence: {stats['hits_with_acetyl_cooccurrence']:,} ({pct:.1f}%)")
    return "\n".join(lines)


def _assign_run_ids(candidate_table, max_rt_gap_minutes: float):
    """
    Sort by (file, product, RT) and assign a run id such that consecutive
    rows for the same (file, product) whose RT is within `max_rt_gap_minutes`
    of each other share a run -- the shared contiguity definition behind both
    `collapse_to_features` and `filter_min_consecutive_scans`.

    RT is used rather than `scan_index` directly, because `scan_index` is the
    raw position in the whole experiment (MS1 and MS2 scans interleaved) --
    consecutive MS1 scans are not necessarily adjacent indices, so a raw index
    gap is not a meaningful measure of chromatographic contiguity, while RT is
    continuous regardless of what's interleaved.

    Fully vectorized (groupby().diff()/cumsum(), no per-group Python loop) so
    it stays fast at full-library scale (millions of rows).

    Returns (sorted_df, run_id) -- `run_id` is a Series aligned to `sorted_df`.
    """
    df = candidate_table.sort_values(["file", "product_inchikey", "rt_minutes"]).reset_index(drop=True)
    rt_gap = df.groupby(["file", "product_inchikey"], sort=False)["rt_minutes"].diff()
    run_id = (rt_gap.isna() | (rt_gap > max_rt_gap_minutes)).cumsum()
    return df, run_id


def filter_min_consecutive_scans(candidate_table, min_consecutive_scans: int, max_rt_gap_minutes: float = 0.1):
    """
    Drop raw hits that aren't part of a run of at least
    `min_consecutive_scans` scans in a row (same file + product, RT within
    `max_rt_gap_minutes` -- see `_assign_run_ids`). A lone scan or two is much
    more likely to be noise or a coincidental mass overlap than a real
    chromatographic feature.

    `min_consecutive_scans <= 1` is a no-op (every run already has >=1 scan).
    """
    if candidate_table.empty or min_consecutive_scans <= 1:
        return candidate_table

    df, run_id = _assign_run_ids(candidate_table, max_rt_gap_minutes)
    run_sizes = run_id.groupby(run_id).size()
    keep = run_id.map(run_sizes) >= min_consecutive_scans
    return df[keep].reset_index(drop=True)


def collapse_to_features(candidate_table, max_rt_gap_minutes: float = 0.1, min_consecutive_scans: int = 1):
    """
    Collapse raw (file, scan, product) hits into one row per contiguous
    elution event, to turn per-scan repeat detections of the same feature
    into a single candidate. `min_consecutive_scans` (>1) additionally drops
    resulting features with fewer raw hits than that (see
    `filter_min_consecutive_scans` for the same idea applied to the raw,
    uncollapsed table instead).

    Returns a DataFrame, one row per (file, product, elution event), with the
    feature's RT span, apex scan (highest intensity), and every distinct
    parent compound observed for it (more than one is possible: different
    parents can react to an identical product, see `run_match_pipeline`'s
    docstring -- mass alone can't disambiguate which one this feature is).
    """
    import pandas as pd

    if candidate_table.empty:
        return candidate_table

    df, run_id = _assign_run_ids(candidate_table, max_rt_gap_minutes)
    grouped = df.groupby(run_id, sort=False)
    features = grouped.agg(
        file=("file", "first"),
        product_inchikey=("product_inchikey", "first"),
        n_raw_hits=("intensity", "size"),
        rt_start=("rt_minutes", "min"),
        rt_end=("rt_minutes", "max"),
        polarity=("polarity", "first"),
        reaction=("reaction", "first"),
        product_formula=("product_formula", "first"),
        product_exact_mass=("product_exact_mass", "first"),
    )

    apex_idx = grouped["intensity"].idxmax()
    apex_rows = df.loc[apex_idx.to_numpy()]
    features["apex_rt_minutes"] = apex_rows["rt_minutes"].to_numpy()
    features["apex_intensity"] = apex_rows["intensity"].to_numpy()
    features["apex_relative_intensity"] = apex_rows["relative_intensity"].to_numpy()
    features["apex_ppm_error"] = apex_rows["ppm_error"].to_numpy()

    n_parents = grouped["parent_inchikey"].nunique()
    single_parent = grouped["parent_inchikey"].first()
    # Ambiguous (>1 parent for the same product mass, see run_match_pipeline's
    # docstring) is rare -- only build the sorted-unique list for those groups,
    # since the per-group Python callable needed for that is comparatively slow.
    features["parent_inchikeys"] = np.where(
        (n_parents > 1).to_numpy(), None, single_parent.map(lambda p: [p]),
    )
    if (n_parents > 1).any():
        ambiguous_run_ids = n_parents[n_parents > 1].index
        ambiguous_lists = (
            df[run_id.isin(ambiguous_run_ids)]
            .groupby(run_id[run_id.isin(ambiguous_run_ids)], sort=False)["parent_inchikey"]
            .agg(lambda s: sorted(s.unique().tolist()))
        )
        features.loc[ambiguous_lists.index, "parent_inchikeys"] = ambiguous_lists

    if df["acetyl_cooccurs"].notna().any():
        features["acetyl_cooccurs"] = grouped["acetyl_cooccurs"].any()
    else:
        features["acetyl_cooccurs"] = None

    if min_consecutive_scans > 1:
        features = features[features["n_raw_hits"] >= min_consecutive_scans]
    return features.reset_index(drop=True)


def scan_count_breakdown(candidate_table, thresholds=(3, 50, 100, 200, 500), max_rt_gap_minutes=0.1, features_table=None):
    """
    Count of features with n_raw_hits >= each threshold -- "how many real
    candidates survive a stricter minimum-consecutive-scans cut", one row per
    threshold. Include the currently-applied min_consecutive_scans value in
    `thresholds` so a chart of this can show where "now" sits.

    Pass `candidate_table` (raw hits); if a `features_table` was already
    computed (e.g. the GUI's "collapse to features" was on), pass it too to
    avoid recomputing -- otherwise this collapses internally, so the scan
    count always means the same thing (a real contiguous run) regardless of
    which view the caller happens to be showing.
    """
    import pandas as pd

    if features_table is None:
        features_table = collapse_to_features(candidate_table, max_rt_gap_minutes)
    if features_table.empty or "n_raw_hits" not in features_table.columns:
        return pd.DataFrame({"threshold": list(thresholds), "count": [0] * len(thresholds)})

    counts = [int((features_table["n_raw_hits"] >= t).sum()) for t in thresholds]
    return pd.DataFrame({"threshold": list(thresholds), "count": counts})


def top_structures_by_formula(candidate_table, top_n=10, max_rt_gap_minutes=0.1, features_table=None):
    """
    The top `top_n` product formulas by total scan evidence -- summing
    n_raw_hits across every feature sharing that formula, which rewards a
    formula seen reproducibly (multiple features/files) over one broad but
    isolated noisy peak in a single file. Deduplicated by formula so isomers/
    salt forms that react to the same formula aren't shown as separate near-
    identical entries.

    Same features_table reuse as `scan_count_breakdown`. `product_smiles` /
    `parent_name` aren't columns on the (aggregated) features table, so
    they're looked up back on `candidate_table` for the single feature with
    the highest individual n_raw_hits per formula -- the best single example
    to actually draw. A formula bucket often contains several distinct
    structures (different product_inchikey values -- not necessarily true
    isomers, e.g. many distinct lipid species can share one elemental
    formula), not just one: only one is drawn, so `n_isomers` reports how
    many distinct structures the pooled `total_scans` actually represents,
    to make that dedup visible rather than silently misleading.

    Returns one row per formula: product_formula, total_scans, n_isomers,
    product_smiles, parent_name, reaction, acetyl_cooccurs (of that
    representative feature).
    """
    import pandas as pd

    if features_table is None:
        features_table = collapse_to_features(candidate_table, max_rt_gap_minutes)
    if features_table.empty or "product_formula" not in features_table.columns:
        return pd.DataFrame()

    totals = features_table.groupby("product_formula")["n_raw_hits"].sum().sort_values(ascending=False).head(top_n)

    rows = []
    for formula, total in totals.items():
        group = features_table[features_table["product_formula"] == formula]
        rep_feature = group.loc[group["n_raw_hits"].idxmax()]
        rep_hits = candidate_table[candidate_table["product_inchikey"] == rep_feature["product_inchikey"]]
        rep_hit = rep_hits.iloc[0] if len(rep_hits) else None
        rows.append({
            "product_formula": formula,
            "total_scans": int(total),
            "n_isomers": int(group["product_inchikey"].nunique()),
            "product_smiles": rep_hit["product_smiles"] if rep_hit is not None else None,
            "parent_name": rep_hit["parent_name"] if rep_hit is not None else None,
            "reaction": rep_feature.get("reaction"),
            "acetyl_cooccurs": rep_feature.get("acetyl_cooccurs"),
        })
    return pd.DataFrame(rows)
