"""
comparison/ms2_confidence.py — cross-check MS Matching features against MS2
scans for a diagnostic fragment ion, an additional filter on top of (not
instead of) the regular MS1-based result.

Association rule: an MS2 scan supports a feature if its precursor m/z is
close to the feature's own observed mass (`apex_matched_mz`, the actual
instrument-observed value at the feature's apex scan, not the theoretical
`product_exact_mass`) AND its RT is close to the feature's apex RT --
DDA precursor selection happens on or very near the MS1 scan that triggered
it, so both conditions together are what actually ties an MS2 event to a
specific MS1 feature (precursor mass alone is not enough: many features can
share a similar mass at very different retention times). A feature can have
more than one such MS2 scan; the count itself is tracked, not just whether
at least one exists, since more supporting scans is itself a confidence signal.

Independent from `mzml_tools.scan_detector`'s single/multi-target MS1+MS2
peak search (checks a target list against every scan directly) -- this
module instead starts from an already-computed feature table and asks
"which of *this file's* MS2 scans are near enough to belong to this specific
feature", which needs each file's MS2 spectra grouped and RT-sorted once,
not a per-scan-per-target sweep.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class DiagnosticTarget:
    label: str
    target_mz: float


def _tolerance_delta(mz: float, tolerance: float, unit: str) -> float:
    if unit == "ppm":
        return mz * tolerance / 1e6
    if unit == "Da":
        return tolerance
    raise ValueError(f"unknown tolerance unit {unit!r} (use 'ppm' or 'Da')")


def load_ms2_scans(mzml_path: str):
    """
    One-time extraction of every MS2 spectrum's precursor m/z, RT, and peaks
    from a file, sorted by RT -- built once per file and reused across every
    feature in that file in `find_ms2_support`, rather than re-scanning the
    whole experiment per feature.

    Returns a list of dicts: scan_index, native_id, rt_minutes, precursor_mz,
    mzs (np.ndarray), intensities (np.ndarray). Scans with no precursor
    (shouldn't happen for MS2, but pyOpenMS allows an empty precursor list)
    are skipped, since there's nothing to match on.
    """
    from pyopenms import MSExperiment, MzMLFile

    exp = MSExperiment()
    MzMLFile().load(str(mzml_path), exp)

    scans = []
    for i, spec in enumerate(exp):
        if spec.getMSLevel() != 2:
            continue
        precursors = spec.getPrecursors()
        if not precursors:
            continue
        mzs, intensities = spec.get_peaks()
        scans.append({
            "scan_index": i,
            "native_id": spec.getNativeID(),
            "rt_minutes": spec.getRT() / 60.0,
            "precursor_mz": float(precursors[0].getMZ()),
            "mzs": mzs,
            "intensities": intensities,
        })
    scans.sort(key=lambda s: s["rt_minutes"])
    return scans


def _scan_has_diagnostic_ion(scan, diagnostic_targets, ion_tolerance, ion_unit):
    mzs = scan["mzs"]
    if len(mzs) == 0:
        return False
    for target in diagnostic_targets:
        delta = _tolerance_delta(target.target_mz, ion_tolerance, ion_unit)
        if np.any((mzs >= target.target_mz - delta) & (mzs <= target.target_mz + delta)):
            return True
    return False


def find_ms2_support(
    features_df,
    diagnostic_targets: list,
    precursor_tolerance: float = 0.5,
    precursor_unit: str = "Da",
    rt_window_minutes: float = 0.5,
    ion_tolerance: float = 25.0,
    ion_unit: str = "ppm",
    progress_callback=None,
):
    """
    For each row of `features_df` (needs `file`, `apex_rt_minutes`,
    `apex_matched_mz` -- see `matcher.collapse_to_features`), find MS2 scans
    in the same file within `rt_window_minutes` of the feature's apex RT and
    `precursor_tolerance` of the feature's own observed mass, then check
    each one's peaks against every entry in `diagnostic_targets` (within
    `ion_tolerance`).

    Returns a copy of `features_df` with three added columns:
    - `n_ms2_associated`: how many MS2 scans matched on precursor mass + RT,
      regardless of whether a diagnostic ion was found in them
    - `n_ms2_with_diagnostic_ion`: the subset of those that contained at
      least one diagnostic-ion peak
    - `has_diagnostic_ms2`: `n_ms2_with_diagnostic_ion > 0`

    An empty `diagnostic_targets` list still populates `n_ms2_associated`
    (useful on its own -- "does this feature have MS2 coverage at all") but
    `n_ms2_with_diagnostic_ion`/`has_diagnostic_ms2` are then always 0/False.
    """
    n_associated = np.zeros(len(features_df), dtype=int)
    n_with_ion = np.zeros(len(features_df), dtype=int)

    files = features_df["file"].unique()
    for file_i, file in enumerate(files):
        if progress_callback:
            progress_callback(f"Scanning MS2 spectra in file {file_i + 1}/{len(files)}...")

        file_mask = (features_df["file"] == file).to_numpy()
        file_positions = np.flatnonzero(file_mask)

        ms2_scans = load_ms2_scans(file)
        if not ms2_scans:
            continue
        scan_rts = np.array([s["rt_minutes"] for s in ms2_scans])
        scan_precursors = np.array([s["precursor_mz"] for s in ms2_scans])

        apex_rts = features_df["apex_rt_minutes"].to_numpy()[file_positions]
        apex_mzs = features_df["apex_matched_mz"].to_numpy()[file_positions]

        for local_i, (apex_rt, apex_mz) in enumerate(zip(apex_rts, apex_mzs)):
            lo = np.searchsorted(scan_rts, apex_rt - rt_window_minutes, side="left")
            hi = np.searchsorted(scan_rts, apex_rt + rt_window_minutes, side="right")
            if hi <= lo:
                continue

            delta = _tolerance_delta(apex_mz, precursor_tolerance, precursor_unit)
            candidate_precursors = scan_precursors[lo:hi]
            precursor_hit = np.abs(candidate_precursors - apex_mz) <= delta
            if not precursor_hit.any():
                continue

            feature_pos = file_positions[local_i]
            candidate_indices = np.flatnonzero(precursor_hit) + lo
            n_associated[feature_pos] = len(candidate_indices)

            if diagnostic_targets:
                hits = sum(
                    _scan_has_diagnostic_ion(ms2_scans[j], diagnostic_targets, ion_tolerance, ion_unit)
                    for j in candidate_indices
                )
                n_with_ion[feature_pos] = hits

    result = features_df.copy()
    result["n_ms2_associated"] = n_associated
    result["n_ms2_with_diagnostic_ion"] = n_with_ion
    result["has_diagnostic_ms2"] = n_with_ion > 0
    return result
