"""
comparison/plotting.py — static figure export (matplotlib + RDKit), separate
from matcher.py (pure matching/aggregation logic) and gui.py (interactive
Streamlit/Plotly).

For sharing results outside the live app (e.g. a PNG in output/figures/), not
for the GUI itself -- the GUI renders the same underlying data (from
matcher.scan_count_breakdown / matcher.top_structures_by_formula) with Plotly
instead, except for the structure grid, which is inherently a static image
either way.
"""
from __future__ import annotations

import os

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


def save_scan_count_breakdown_figure(breakdown_df, out_path: str, title: str = "") -> str:
    """Bar chart of `matcher.scan_count_breakdown`'s output: feature count
    that clears each minimum-consecutive-scans threshold."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with plt.rc_context(_DARK_THEME):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        labels = [f">= {t}" for t in breakdown_df["threshold"]]
        bars = ax.bar(labels, breakdown_df["count"], color="#2dd4bf")
        ax.bar_label(bars, padding=3)
        ax.set_xlabel("Minimum consecutive scans")
        ax.set_ylabel("Features")
        ax.set_title(title or "Features by minimum consecutive scans")
        ax.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
    return out_path


def build_top_structures_grid_image(top_df, mols_per_row: int = 5):
    """RDKit structure grid for `matcher.top_structures_by_formula`'s output:
    one 2D structure per row, labeled with formula + total scan count.
    Returns a PIL Image, or None if no row has a parseable SMILES -- shared
    by the GUI (`st.image`) and `save_top_structures_grid` so the (comparatively
    expensive) RDKit rendering only happens once per run."""
    from rdkit import Chem
    from rdkit.Chem import Draw

    mols, legends = [], []
    for row in top_df.itertuples():
        smiles = getattr(row, "product_smiles", None)
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            continue
        label = f"{row.product_formula}\n{row.total_scans} scans"
        n_isomers = getattr(row, "n_isomers", 1)
        if n_isomers > 1:
            label += f"\n(1 of {n_isomers} structures)"
        if getattr(row, "parent_name", None):
            label += f"\n{row.parent_name}"
        mols.append(mol)
        legends.append(label)

    if not mols:
        return None
    return Draw.MolsToGridImage(mols, molsPerRow=mols_per_row, subImgSize=(220, 220), legends=legends)


def save_top_structures_grid(image, out_path: str) -> str | None:
    """Save a PIL Image (from `build_top_structures_grid_image`) to disk.
    Pass `image=None` (no parseable SMILES) to no-op."""
    if image is None:
        return None
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    image.save(out_path)
    return out_path


def save_feature_map_figure(df, rt_col: str, mass_col: str, intensity_col: str, out_path: str, title: str = "") -> str:
    """Static counterpart of the GUI's interactive RT-vs-mass scatter (Plotly),
    for figure-export parity -- point size scaled by intensity, colored by
    acetyl co-occurrence if that check was run."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    with plt.rc_context(_DARK_THEME):
        fig, ax = plt.subplots(figsize=(9, 5))
        if not df.empty:
            intensity = df[intensity_col].to_numpy(dtype=float)
            max_intensity = intensity.max() if intensity.max() > 0 else 1.0
            sizes = 15 + 200 * (intensity / max_intensity)
            if "acetyl_cooccurs" in df.columns and df["acetyl_cooccurs"].notna().any():
                colors = np.where(df["acetyl_cooccurs"].fillna(False), "#2dd4bf", "#f472b6")
                for label, color in [("Co-occurring", "#2dd4bf"), ("Not co-occurring", "#f472b6")]:
                    mask = colors == color
                    ax.scatter(df.loc[mask, rt_col], df.loc[mask, mass_col], s=sizes[mask],
                               color=color, alpha=0.7, label=label)
                ax.legend()
            else:
                ax.scatter(df[rt_col], df[mass_col], s=sizes, color="#2dd4bf", alpha=0.7)
        ax.set_xlabel("RT (min)")
        ax.set_ylabel("m/z")
        ax.set_title(title or "Feature map")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
    return out_path
