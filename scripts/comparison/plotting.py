"""
comparison/plotting.py — figure/image rendering (matplotlib + RDKit),
separate from matcher.py (pure matching/aggregation logic) and gui.py
(interactive Streamlit/Plotly).

Most of this is static figure export for sharing results outside the live
app (e.g. a PNG in output/figures/) -- the GUI renders the same underlying
data (from matcher.scan_count_breakdown / matcher.structures_by_formula)
with Plotly instead, except for structure images, which are inherently
static either way (RDKit 2D depictions), so `mol_image_data_uri` is shared
by both the static grid export and the GUI's Molecule Explorer cards.
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


_draw_module = None
_draw_import_error = None
_draw_import_attempted = False


def _get_draw_module():
    """Lazily import rdkit.Chem.Draw once, caching success or failure. A
    broken RDKit/Cairo install (DLL load failures for rdMolDraw2D are a
    known Windows issue, independent of the rest of RDKit -- Chem.* parsing
    can work fine while Draw.* doesn't) shouldn't crash the whole page over
    one feature; callers check this instead of importing directly."""
    global _draw_module, _draw_import_error, _draw_import_attempted
    if not _draw_import_attempted:
        _draw_import_attempted = True
        try:
            from rdkit.Chem import Draw
            _draw_module = Draw
        except ImportError as exc:
            _draw_import_error = exc
    return _draw_module


def structure_rendering_error() -> str | None:
    """None if structure rendering is available; otherwise a short message
    explaining why, for the GUI to show once instead of letting the
    ImportError propagate and crash the page."""
    _get_draw_module()
    return str(_draw_import_error) if _draw_import_error else None


def mol_image_data_uri(smiles: str | None, size=(220, 200)) -> str | None:
    """SMILES -> a `data:` URI PNG, for embedding directly in an
    `<img src="...">` tag (the Molecule Explorer's HTML cards). Returns None
    for a missing/unparseable SMILES, or if structure rendering isn't
    available at all (see `structure_rendering_error`)."""
    draw = _get_draw_module()
    if not smiles or draw is None:
        return None

    import base64
    import io

    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    img = draw.MolToImage(mol, size=size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


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


def _build_grid_image(entries, mols_per_row: int, struct_size, caption_h: int, font_sizes=(30, 18)):
    """Shared PIL grid composer: one structure per cell (RDKit), with each
    entry's own list of (text, is_big) caption lines drawn underneath in one
    of two font sizes -- manual composition rather than RDKit's own grid-
    legend mechanism, because RDKit auto-shrinks an entire cell's legend to
    fit its single longest line, so one long line (lipid nomenclature can run
    50+ characters) would drag every other line in that cell down to the
    same tiny size. Also returns ONE image for however many entries there
    are, rather than one image/element per entry -- at high entry counts (a
    formula can pool dozens of isomers), embedding that many separate images
    individually (e.g. as base64 HTML `<img>` tags) is far more expensive to
    transmit/parse than one combined image via `st.image`, even though the
    RDKit rendering cost itself is the same either way.

    `entries`: list of {"mol": RDKit Mol, "lines": [(text, is_big), ...]}.
    Returns a PIL Image, or None if `entries` is empty.
    """
    if not entries:
        return None

    rdkit_draw = _get_draw_module()
    from PIL import Image, ImageDraw, ImageFont

    cell_w, cell_h = struct_size[0], struct_size[1] + caption_h
    n_rows = -(-len(entries) // mols_per_row)  # ceil
    canvas = Image.new("RGB", (mols_per_row * cell_w, n_rows * cell_h), "white")
    draw = ImageDraw.Draw(canvas)
    font_big = ImageFont.load_default(size=font_sizes[0])
    font_small = ImageFont.load_default(size=font_sizes[1])

    for i, entry in enumerate(entries):
        col, row_idx = i % mols_per_row, i // mols_per_row
        x0, y0 = col * cell_w, row_idx * cell_h
        struct_img = rdkit_draw.MolToImage(entry["mol"], size=struct_size)
        canvas.paste(struct_img, (x0, y0))

        y = y0 + struct_size[1] + 6
        for line, is_big in entry["lines"]:
            if not line:
                continue
            font = font_big if is_big else font_small
            line_w = draw.textlength(line, font=font)
            draw.text((x0 + (cell_w - line_w) / 2, y), line, fill="black", font=font)
            y += font.size + 6

    return canvas


def build_top_structures_grid_image(top_df, mols_per_row: int = 5, struct_size=(400, 340)):
    """Structure grid for `matcher.top_structures_by_formula`'s output: one
    2D structure per row, captioned with formula + total scan count (large),
    isomer count (large), and parent name (small, truncated).

    Returns a PIL Image, or None if no row has a parseable SMILES, or if
    structure rendering isn't available at all (see
    `structure_rendering_error`) -- shared by the GUI (`st.image`) and
    `save_top_structures_grid` so the (comparatively expensive) rendering
    only happens once per run."""
    if _get_draw_module() is None:
        return None

    from rdkit import Chem

    entries = []
    for row in top_df.itertuples():
        smiles = getattr(row, "product_smiles", None)
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            continue
        n_isomers = getattr(row, "n_isomers", 1)
        parent_name = getattr(row, "parent_name", None)
        parent_name = parent_name if isinstance(parent_name, str) else None
        entries.append({
            "mol": mol,
            "lines": [
                (f"{row.product_formula} -- {row.total_scans} scans", True),
                (f"(1 of {n_isomers} structures)" if n_isomers > 1 else "", True),
                ((parent_name if len(parent_name) <= 28 else parent_name[:25] + "...") if parent_name else "", False),
            ],
        })
    return _build_grid_image(entries, mols_per_row, struct_size, caption_h=130, font_sizes=(30, 18))


def build_isomer_grid_image(isomers_df, mols_per_row: int = 4, struct_size=(220, 190)):
    """Structure grid for `matcher.isomers_for_formula`'s output: one 2D
    structure per distinct isomer, captioned with scan count (large) and
    parent name/InChIKey (small, truncated) -- the drill-down view for a
    formula `build_top_structures_grid_image` only showed one representative
    structure for (a formula bucket has pooled up to 80+ in practice).

    Returns a PIL Image, or None if no row has a parseable SMILES, or if
    structure rendering isn't available (see `structure_rendering_error`)."""
    if _get_draw_module() is None:
        return None

    from rdkit import Chem

    entries = []
    for row in isomers_df.itertuples():
        smiles = getattr(row, "product_smiles", None)
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            continue
        name = row.parent_name if isinstance(row.parent_name, str) else row.product_inchikey
        entries.append({
            "mol": mol,
            "lines": [
                (f"{row.total_scans} scans", True),
                (name if len(name) <= 30 else name[:27] + "...", False),
            ],
        })
    return _build_grid_image(entries, mols_per_row, struct_size, caption_h=70, font_sizes=(22, 15))


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
