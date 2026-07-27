"""
mzml_tools/plotting.py — static figure export (matplotlib), separate from
scan_detector.py (pure MS logic) and gui.py (interactive Streamlit/Plotly).

For sharing results outside the live app (e.g. sending a PNG), not for the GUI
itself -- the GUI uses Plotly for interactive charts.
"""
from __future__ import annotations

import os

from mzml_tools.scan_detector import extract_ion_chromatogram, find_scans_with_mz

_DARK_THEME = {
    "figure.facecolor": "#0f172a",
    "axes.facecolor": "#0f172a",
    "axes.edgecolor": "#e2e8f0",
    "axes.labelcolor": "#e2e8f0",
    "text.color": "#e2e8f0",
    "xtick.color": "#e2e8f0",
    "ytick.color": "#e2e8f0",
    "grid.color": "#334155",
    "font.size": 11,
}


def save_xic_figure(
    mzml_path: str,
    target_mz: float,
    tolerance: float,
    unit: str,
    ms_level: int,
    out_path: str,
    title: str = "",
) -> str:
    """Save an extracted-ion-chromatogram PNG (intensity vs RT, apex annotated)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = extract_ion_chromatogram(mzml_path, target_mz, tolerance, unit, ms_level)
    rt = [p.rt_minutes for p in points]
    inten = [p.intensity for p in points]
    apex = max(points, key=lambda p: p.intensity)

    with plt.rc_context(_DARK_THEME):
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(rt, inten, color="#2dd4bf", linewidth=1.3)
        ax.fill_between(rt, inten, color="#2dd4bf", alpha=0.15)
        ax.annotate(
            f"apex: RT {apex.rt_minutes:.2f} min\nintensity {apex.intensity:.2e}",
            xy=(apex.rt_minutes, apex.intensity),
            xytext=(apex.rt_minutes + 1.5, apex.intensity * 0.85),
            arrowprops=dict(arrowstyle="->", color="#e2e8f0"),
            fontsize=9,
        )
        ax.set_xlabel("Retention time (min)")
        ax.set_ylabel("Intensity")
        subtitle = f"target m/z {target_mz:.4f} (MS{ms_level}, {tolerance} {unit})"
        ax.set_title(f"{title}\n{subtitle}" if title else subtitle)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
    return out_path


def save_hit_scatter_figure(
    mzml_path: str,
    target_mz: float,
    tolerance: float,
    unit: str,
    ms_level: int,
    out_path: str,
    title: str = "",
    min_relative_intensity: float = 0.0,
) -> str:
    """Save a scatter PNG of matching-scan relative intensity vs RT (for sparse/MS2 hits, where an XIC line isn't meaningful)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matches = find_scans_with_mz(
        mzml_path, target_mz, tolerance, unit,
        min_relative_intensity=min_relative_intensity, ms_level=ms_level,
    )

    with plt.rc_context(_DARK_THEME):
        fig, ax = plt.subplots(figsize=(9, 4.5))
        if matches:
            rt = [m.rt_minutes for m in matches]
            rel = [m.relative_intensity * 100 for m in matches]
            ax.scatter(rt, rel, color="#f472b6", s=60, alpha=0.85)
        ax.set_xlabel("Retention time (min)")
        ax.set_ylabel("Relative intensity (% of scan base peak)")
        subtitle = f"target m/z {target_mz:.4f} (MS{ms_level}, {tolerance} {unit}) -- {len(matches)} matching scans"
        ax.set_title(f"{title}\n{subtitle}" if title else subtitle)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
    return out_path
