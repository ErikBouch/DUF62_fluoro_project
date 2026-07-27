# mzml_tools

Functions for opening, reading, and querying **mzML** files, plus the Streamlit
page (`gui.py`) that exposes them.

## `scan_detector.py` (logic — no Streamlit import)

Find the MS scans that contain a **target m/z** within a **tolerance** and
above an intensity filter, and export the matching scans to CSV.

- `get_file_overview(path)` — spectrum counts by MS level/polarity, RT range,
  and the observed m/z range per MS level. Worth checking before hunting for a
  target m/z: on some instruments/methods the MS1 scan range doesn't extend
  down to very low m/z, so a small fragment ion may only be observable in MS2.
- `find_scans_with_mz(...)` — for each matching scan, records the most intense
  peak in the window, that spectrum's base-peak intensity, the match's
  **intensity relative to the base peak** (portable across files/instruments —
  more useful than a raw absolute threshold, which doesn't compare across
  files), and — for MS2+ scans — the **precursor m/z**. Many distinct
  precursor masses producing the same low-mass fragment is one signal that
  it's a genuine diagnostic ion rather than noise from one intense contaminant.
- `find_scans_with_multiple_mz(...)` — like the above, but checks many target
  masses against the same file in a single pass (one file load, one loop over
  spectra) instead of once per target — much faster when screening a whole
  list of candidate masses against one file.
- `export_matches_csv(matches, out_path)` — writes a CSV.
- `extract_ion_chromatogram(path, target_mz, tolerance, unit, ms_level)` — a
  proper **XIC**: intensity of the target m/z at *every* scan of that level
  (not just above-threshold hits), so it plots as a continuous RT trace — the
  standard way to see whether there's a real chromatographic peak.

### Usage (CLI)
```bash
# see what's actually in the file first
python scan_detector.py file.mzML --overview

# hunt for a target ion
python scan_detector.py file.mzML --mz 150.0 --tol 25 --unit ppm \
    --min-rel-intensity 0.02 --ms-level 2
```

### Usage (import)
```python
from mzml_tools.scan_detector import find_scans_with_mz, export_matches_csv
matches = find_scans_with_mz("file.mzML", target_mz=150.0, tolerance=25, unit="ppm",
                              min_relative_intensity=0.02, ms_level=2)
export_matches_csv(matches, "output/hits.csv")
```

## `gui.py`
The Streamlit page (rendered from `main.py`): pick/enter an mzML file → see its
overview → type a target m/z/tolerance/MS level/relative-intensity filter →
run → sortable results table, CSV download, an interactive RT-vs-relative-
intensity scatter (Plotly, sized by intensity, colored by MS level), and a
"Compute XIC" button for a live extracted-ion chromatogram at any MS level.

## `plotting.py` (static PNG export, separate from the interactive GUI)
For sharing results outside the app (e.g. sending a file directly) rather than
screen-sharing the live tool:
- `save_xic_figure(...)` — XIC line plot, apex annotated, dark-themed.
- `save_hit_scatter_figure(...)` — RT-vs-relative-intensity scatter, for sparse/
  MS2 hits where a continuous XIC line isn't meaningful.

```python
from mzml_tools.plotting import save_xic_figure
save_xic_figure("file.mzML", target_mz=150.0, tolerance=15, unit="ppm",
                ms_level=1, out_path="output/figures/my_xic.png", title="...")
```

## Folders
- `data/`   — put input mzML here (gitignored). The real project data lives
  outside this repository; the GUI's file picker looks for it in a sibling
  data folder automatically (see `common/ui.py`), and falls back to manual
  path entry if none is found.
- `output/` — CSV exports and figures land here (gitignored; auto-created at runtime).

## Status
Built and tested end-to-end (logic + GUI, incl. XIC) against real HRMS data.
Needs `pyopenms`, `numpy`, `pandas` (logic), `matplotlib` (`plotting.py`), and
`streamlit`, `plotly` (GUI).
