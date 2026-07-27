"""
comparison/matcher.py — match a large list of target masses against one mzML
file efficiently.

`mzml_tools.scan_detector.find_scans_with_multiple_mz` checks every target
against every spectrum -- fine for a handful of targets, far too slow once the
target list is a whole suspect library (tens of thousands of masses): cost
there scales as O(spectra * targets). This module instead sorts the target
masses once and, for each spectrum, does a binary search per peak to find
which targets (if any) it matches -- O(spectra * peaks * log(targets)), which
stays fast even at library scale since a spectrum's peak count is usually much
smaller than the target count.
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


def match_library_to_file(
    mzml_path: str,
    targets: list[tuple],
    tolerance_ppm: float = 25.0,
    ms_level: int | None = 1,
    min_relative_intensity: float | None = 0.0,
) -> list[LibraryMatch]:
    """
    Parameters
    ----------
    targets : list[(label, target_mz)] -- can be tens of thousands of entries.
    tolerance_ppm : float
    ms_level : int | None -- restrict to this MS level; None = all levels.
    min_relative_intensity : float | None -- minimum peak intensity as a
        fraction of that spectrum's base peak; None = no filter.

    Returns
    -------
    list[LibraryMatch] -- one entry per (matching peak, target) pair; a single
    peak can match more than one target if their tolerance windows overlap.
    """
    from pyopenms import MSExperiment, MzMLFile

    labels = np.array([t[0] for t in targets], dtype=object)
    masses = np.array([t[1] for t in targets], dtype=float)
    order = np.argsort(masses)
    sorted_masses = masses[order]
    sorted_labels = labels[order]

    exp = MSExperiment()
    MzMLFile().load(str(mzml_path), exp)

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

            delta = peak_mz * tolerance_ppm / 1e6
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
