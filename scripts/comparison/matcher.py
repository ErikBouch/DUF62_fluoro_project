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

    results: list[LibraryMatch] = []
    for i, spec in enumerate(exp):
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
    return results


def match_library_to_file(
    mzml_path: str,
    targets: list[tuple],
    tolerance: float = 0.002,
    unit: str = "Da",
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
) -> list[LibraryMatch]:
    """Convenience one-call version of `match_experiment`: loads `mzml_path`,
    matches once, and discards the loaded experiment. If you need to match the
    same file against more than one target list, use `load_experiment` +
    `match_experiment` directly instead, to avoid loading it more than once."""
    exp = load_experiment(mzml_path)
    return match_experiment(exp, targets, tolerance, unit, ms_level, min_relative_intensity)


def run_match_pipeline(
    library_df,
    file_paths: list[str],
    fluoroacetyl_tolerance: float = 0.002,
    fluoroacetyl_unit: str = "Da",
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
    check_acetyl_cooccurrence: bool = False,
    acetyl_tolerance: float = 5.0,
    acetyl_unit: str = "ppm",
    progress_callback=None,
) -> "pandas.DataFrame":
    """
    Match the suspect library (`library_df`, as built by
    insilico_library.build_suspect_library) against every file in
    `file_paths`, filtered to `reaction == 'fluoroacetyl'` as the primary
    target set. If `check_acetyl_cooccurrence` is set, also searches the
    `reaction == 'acetyl'` rows (with their own, typically looser, tolerance)
    and flags each fluoroacetyl hit with whether its sibling acetyl product
    (same parent compound, same reactive site) was also detected in that file.

    `progress_callback(message: str)`, if given, is called once per file with
    a short status string (e.g. for a GUI spinner/log).

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

    all_rows = []
    for path in file_paths:
        if progress_callback:
            progress_callback(f"Loading {path} ...")
        exp = load_experiment(path)  # loaded once, reused below for polarity + both matches
        polarity = detect_polarity(exp)
        if polarity is None:
            if progress_callback:
                progress_callback(f"Skipped {path}: no clear polarity.")
            continue
        mz_col = "mz_pos_m_plus_h" if polarity == "+" else "mz_neg_m_minus_h"

        fluoro_targets = list(zip(fluoro_lib.index, fluoro_lib[mz_col]))
        if progress_callback:
            progress_callback(f"Matching {len(fluoro_targets)} fluoroacetyl targets against {path} ...")
        fluoro_matches = match_experiment(
            exp, fluoro_targets, fluoroacetyl_tolerance, fluoroacetyl_unit,
            ms_level, min_relative_intensity,
        )

        acetyl_found_rows = set()
        if check_acetyl_cooccurrence and len(acetyl_lib):
            acetyl_targets = list(zip(acetyl_lib.index, acetyl_lib[mz_col]))
            if progress_callback:
                progress_callback(f"Checking acetyl co-occurrence ({len(acetyl_targets)} targets) in {path} ...")
            acetyl_matches = match_experiment(
                exp, acetyl_targets, acetyl_tolerance, acetyl_unit,
                ms_level, min_relative_intensity,
            )
            acetyl_found_rows = {m.target_label for m in acetyl_matches}

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
                "_acetyl_found_rows": acetyl_found_rows,  # dropped after the join below
            })

    if not all_rows:
        return pd.DataFrame()

    hits_df = pd.DataFrame(all_rows)
    acetyl_found_by_row = hits_df.pop("_acetyl_found_rows")
    candidate_table = hits_df.merge(
        library_df, left_on="_library_row", right_index=True, how="left"
    )

    if check_acetyl_cooccurrence:
        sibling_acetyl_row = [
            acetyl_key_to_row.get((row.parent_inchikey, row.site_index))
            for row in candidate_table.itertuples()
        ]
        candidate_table["acetyl_cooccurs"] = [
            row_id in found for row_id, found in zip(sibling_acetyl_row, acetyl_found_by_row)
        ]
    else:
        candidate_table["acetyl_cooccurs"] = None

    return candidate_table.drop(columns=["_library_row"])
