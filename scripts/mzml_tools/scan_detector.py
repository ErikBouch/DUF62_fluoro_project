"""
scan_detector.py — find MS scans that contain a target m/z.

Part of the DUF62 fluoro project (mzml_tools module). Given an mzML file, a
target m/z, a tolerance, and an intensity filter, this scans every spectrum and
reports the scans that contain a peak at the target m/z (within tolerance)
above the filter. Matches are exported to a CSV.

Note: on some instruments/methods, the MS1 scan range doesn't extend down to
very low m/z, so small fragment ions may only be observable as MS2 product
ions, not MS1 features -- check `get_file_overview()` first. Matching absolute
intensity thresholds also don't compare well across files/instruments —
filtering by intensity *relative to each spectrum's base peak* is more
portable, so this module supports both.

Requires `pyopenms`, `numpy`, `pandas`.

CLI examples:
    # scan/file overview (m/z range per MS level, polarity, RT range)
    python scan_detector.py path/to/file.mzML --overview

    # find scans with a target m/z
    python scan_detector.py path/to/file.mzML --mz 150.0 --tol 25 --unit ppm \
        --min-rel-intensity 0.02 --ms-level 2
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, asdict

import numpy as np


# Polarity codes as reported by pyOpenMS IonSource.Polarity
_POLARITY = {0: "unknown", 1: "+", 2: "-"}


@dataclass
class ScanMatch:
    """One matching scan (the most intense peak found inside the m/z window)."""
    scan_index: int
    native_id: str
    ms_level: int
    polarity: str
    rt_seconds: float
    rt_minutes: float
    matched_mz: float
    intensity: float
    base_peak_intensity: float
    relative_intensity: float  # intensity / base_peak_intensity for this spectrum
    precursor_mz: float | None  # the isolated precursor m/z, for MS2+ scans


@dataclass
class FileOverview:
    """Basic shape of an mzML file: what MS levels/polarities/ranges it holds."""
    n_spectra: int
    ms_level_counts: dict
    polarity_counts: dict
    rt_range_minutes: tuple[float, float]
    mz_range_by_level: dict  # {ms_level: (min_mz, max_mz)}


def mz_window(target_mz: float, tolerance: float, unit: str) -> tuple[float, float]:
    """Return (low, high) m/z bounds for a tolerance given in 'ppm' or 'Da'."""
    if unit == "ppm":
        delta = target_mz * tolerance / 1e6
    elif unit == "Da":
        delta = tolerance
    else:
        raise ValueError(f"unknown tolerance unit {unit!r} (use 'ppm' or 'Da')")
    return target_mz - delta, target_mz + delta


def _load(mzml_path: str):
    from pyopenms import MSExperiment, MzMLFile

    exp = MSExperiment()
    MzMLFile().load(str(mzml_path), exp)
    return exp


def get_file_overview(mzml_path: str) -> FileOverview:
    """
    Summarize an mzML file: spectrum counts by MS level/polarity, RT range, and
    the observed m/z range per MS level. Useful before hunting for a target m/z,
    to check whether it could even be in range for that file/method.
    """
    exp = _load(mzml_path)

    ms_level_counts: dict = {}
    polarity_counts: dict = {}
    rt_min, rt_max = None, None
    mz_range_by_level: dict = {}

    for spec in exp:
        lvl = spec.getMSLevel()
        ms_level_counts[lvl] = ms_level_counts.get(lvl, 0) + 1

        pol = _POLARITY.get(int(spec.getInstrumentSettings().getPolarity()), "unknown")
        polarity_counts[pol] = polarity_counts.get(pol, 0) + 1

        rt = spec.getRT()
        rt_min = rt if rt_min is None else min(rt_min, rt)
        rt_max = rt if rt_max is None else max(rt_max, rt)

        mzs, _ = spec.get_peaks()
        if len(mzs):
            lo, hi = float(mzs.min()), float(mzs.max())
            prev = mz_range_by_level.get(lvl)
            mz_range_by_level[lvl] = (lo, hi) if prev is None else (min(prev[0], lo), max(prev[1], hi))

    rt_range_minutes = (
        (rt_min / 60.0, rt_max / 60.0) if rt_min is not None else (0.0, 0.0)
    )
    return FileOverview(
        n_spectra=exp.size(),
        ms_level_counts=ms_level_counts,
        polarity_counts=polarity_counts,
        rt_range_minutes=rt_range_minutes,
        mz_range_by_level=mz_range_by_level,
    )


def find_scans_with_mz(
    mzml_path: str,
    target_mz: float,
    tolerance: float = 25.0,
    unit: str = "ppm",
    intensity_threshold: float = 0.0,
    min_relative_intensity: float | None = None,
    ms_level: int | None = None,
) -> list[ScanMatch]:
    """
    Find scans whose spectrum contains a peak near `target_mz`.

    For each matching scan, the single most intense peak inside the m/z window
    is recorded, along with that spectrum's base peak intensity and the
    matched peak's intensity relative to it (portable across files/instruments,
    unlike a raw absolute-intensity cutoff).

    Parameters
    ----------
    mzml_path : str                    path to an .mzML file
    target_mz : float                  m/z to search for
    tolerance : float                  half-width of the match window (default 25)
    unit : str                         'ppm' (default) or 'Da'
    intensity_threshold : float        minimum absolute peak intensity to count as a hit
    min_relative_intensity : float|None  minimum peak intensity as a fraction (0-1) of
                                        that spectrum's base peak; None = no filter
    ms_level : int | None              restrict to this MS level (e.g. 2); None = all levels

    Returns
    -------
    list[ScanMatch]
    """
    exp = _load(mzml_path)
    low, high = mz_window(target_mz, tolerance, unit)

    matches: list[ScanMatch] = []
    for i, spec in enumerate(exp):
        if ms_level is not None and spec.getMSLevel() != ms_level:
            continue

        mzs, intensities = spec.get_peaks()
        if len(mzs) == 0:
            continue

        base_peak = float(intensities.max())
        in_window = (mzs >= low) & (mzs <= high) & (intensities >= intensity_threshold)
        if not in_window.any():
            continue

        masked_int = np.where(in_window, intensities, -np.inf)
        best = int(np.argmax(masked_int))
        best_intensity = float(intensities[best])
        rel_intensity = best_intensity / base_peak if base_peak > 0 else 0.0

        if min_relative_intensity is not None and rel_intensity < min_relative_intensity:
            continue

        precursors = spec.getPrecursors()
        precursor_mz = float(precursors[0].getMZ()) if precursors else None

        pol = _POLARITY.get(int(spec.getInstrumentSettings().getPolarity()), "unknown")
        rt = float(spec.getRT())
        matches.append(
            ScanMatch(
                scan_index=i,
                native_id=spec.getNativeID(),
                ms_level=spec.getMSLevel(),
                polarity=pol,
                rt_seconds=rt,
                rt_minutes=rt / 60.0,
                matched_mz=float(mzs[best]),
                intensity=best_intensity,
                base_peak_intensity=base_peak,
                relative_intensity=rel_intensity,
                precursor_mz=precursor_mz,
            )
        )
    return matches


def find_scans_with_multiple_mz(
    mzml_path: str,
    targets: list[tuple],
    tolerance: float = 25.0,
    unit: str = "ppm",
    intensity_threshold: float = 0.0,
    min_relative_intensity: float | None = None,
    ms_level: int | None = None,
) -> dict:
    """
    Like find_scans_with_mz, but checks MANY targets against one file in a
    single pass (one file load, one loop over spectra) -- much faster than
    calling find_scans_with_mz once per target when screening many masses
    (e.g. a whole in-silico library) against the same file.

    Parameters
    ----------
    targets : list[(label, target_mz)]

    Returns
    -------
    dict[label, list[ScanMatch]]
    """
    exp = _load(mzml_path)
    windows = [(label, *mz_window(mz, tolerance, unit)) for label, mz in targets]
    results: dict = {label: [] for label, _ in targets}

    for i, spec in enumerate(exp):
        if ms_level is not None and spec.getMSLevel() != ms_level:
            continue
        mzs, intensities = spec.get_peaks()
        if len(mzs) == 0:
            continue
        base_peak = float(intensities.max())
        pol = None
        rt = float(spec.getRT())
        precursors = spec.getPrecursors()
        precursor_mz = float(precursors[0].getMZ()) if precursors else None

        for label, low, high in windows:
            in_window = (mzs >= low) & (mzs <= high) & (intensities >= intensity_threshold)
            if not in_window.any():
                continue
            masked_int = np.where(in_window, intensities, -np.inf)
            best = int(np.argmax(masked_int))
            best_intensity = float(intensities[best])
            rel_intensity = best_intensity / base_peak if base_peak > 0 else 0.0
            if min_relative_intensity is not None and rel_intensity < min_relative_intensity:
                continue
            if pol is None:
                pol = _POLARITY.get(int(spec.getInstrumentSettings().getPolarity()), "unknown")
            results[label].append(
                ScanMatch(
                    scan_index=i,
                    native_id=spec.getNativeID(),
                    ms_level=spec.getMSLevel(),
                    polarity=pol,
                    rt_seconds=rt,
                    rt_minutes=rt / 60.0,
                    matched_mz=float(mzs[best]),
                    intensity=best_intensity,
                    base_peak_intensity=base_peak,
                    relative_intensity=rel_intensity,
                    precursor_mz=precursor_mz,
                )
            )
    return results


@dataclass
class ChromatogramPoint:
    rt_minutes: float
    intensity: float  # 0.0 if no peak fell in the m/z window for this scan


def extract_ion_chromatogram(
    mzml_path: str,
    target_mz: float,
    tolerance: float = 25.0,
    unit: str = "ppm",
    ms_level: int = 1,
) -> list[ChromatogramPoint]:
    """
    Build an extracted-ion chromatogram (XIC): intensity of the most intense
    peak within the m/z window, at every scan of `ms_level`, across the whole
    run (including scans with no peak there -> intensity 0). Unlike
    `find_scans_with_mz`, this returns one point per scan so it plots as a
    continuous trace -- the standard way to visually confirm whether a target
    m/z shows a real chromatographic peak.
    """
    exp = _load(mzml_path)
    low, high = mz_window(target_mz, tolerance, unit)

    points: list[ChromatogramPoint] = []
    for spec in exp:
        if spec.getMSLevel() != ms_level:
            continue
        mzs, intensities = spec.get_peaks()
        intensity = 0.0
        if len(mzs):
            in_window = (mzs >= low) & (mzs <= high)
            if in_window.any():
                intensity = float(intensities[in_window].max())
        points.append(ChromatogramPoint(rt_minutes=spec.getRT() / 60.0, intensity=intensity))
    return points


def export_matches_csv(matches: list[ScanMatch], out_path: str):
    """Write matches to `out_path` as CSV (creating parent dirs). Returns the DataFrame."""
    import pandas as pd

    df = pd.DataFrame([asdict(m) for m in matches])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_csv(out_path, index=False)
    return df


def _default_output_path(mzml_path: str, target_mz: float) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    stem = os.path.splitext(os.path.basename(mzml_path))[0]
    return os.path.join(here, "output", f"{stem}_mz{target_mz:g}.csv")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Find MS scans containing a target m/z and export them to CSV."
    )
    p.add_argument("mzml", help="path to an input .mzML file")
    p.add_argument("--overview", action="store_true",
                    help="print a file overview (MS levels, polarity, RT/m-z range) and exit")
    p.add_argument("--mz", type=float, help="target m/z to search for")
    p.add_argument("--tol", type=float, default=25.0, help="tolerance (default 25)")
    p.add_argument("--unit", choices=["ppm", "Da"], default="ppm", help="tolerance unit")
    p.add_argument("--threshold", type=float, default=0.0, help="min absolute peak intensity")
    p.add_argument("--min-rel-intensity", type=float, default=None,
                    help="min peak intensity as a fraction (0-1) of that spectrum's base peak")
    p.add_argument("--ms-level", type=int, default=None, help="restrict to MS level (e.g. 2)")
    p.add_argument("-o", "--output", default=None, help="output CSV path (default: ./output/...)")
    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)

    if args.overview:
        ov = get_file_overview(args.mzml)
        print(f"n_spectra: {ov.n_spectra}")
        print(f"ms_level_counts: {ov.ms_level_counts}")
        print(f"polarity_counts: {ov.polarity_counts}")
        print(f"rt_range_minutes: {ov.rt_range_minutes[0]:.2f} - {ov.rt_range_minutes[1]:.2f}")
        print(f"mz_range_by_level: {ov.mz_range_by_level}")
        return

    if args.mz is None:
        raise SystemExit("--mz is required unless --overview is given")

    matches = find_scans_with_mz(
        args.mzml, args.mz, args.tol, args.unit,
        args.threshold, args.min_rel_intensity, args.ms_level,
    )
    out_path = args.output or _default_output_path(args.mzml, args.mz)
    export_matches_csv(matches, out_path)
    print(f"{len(matches)} matching scan(s) -> {out_path}")


if __name__ == "__main__":
    main()
