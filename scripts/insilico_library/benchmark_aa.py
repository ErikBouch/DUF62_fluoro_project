"""
insilico_library/benchmark_aa.py — small test library: the 20 proteinogenic
amino acids, fluoroacetylated, then (optionally) searched for in any local
HRMS data under `data/HRMS/`.

This validates acylation.py on a real, known, chemically diverse set:
multiple primary-amine sites in lysine, a guanidine in arginine, primary
amides in asn/gln that must NOT react, and a secondary/ring amine in proline
that correctly yields zero products.

Free (non-zwitterionic) SMILES, standard neutral forms -- stereochemistry
omitted since it doesn't affect formula/mass. Each is asserted against its
known formula before use, as a sanity check on the SMILES themselves.

The HRMS search step auto-discovers whatever .mzML files exist locally (same
mechanism as mzml_tools/gui.py) -- it does not depend on any specific dataset
and is skipped entirely if none are found.

Run: python benchmark_aa.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rdkit import Chem  # noqa: E402
from rdkit.Chem import rdMolDescriptors  # noqa: E402

from common.ui import find_mzml_files  # noqa: E402
from insilico_library.acylation import fluoroacetylate  # noqa: E402
from mzml_tools.scan_detector import find_scans_with_multiple_mz, get_file_overview  # noqa: E402

# name -> (SMILES, expected Hill-notation formula)
AMINO_ACIDS = {
    "Gly": ("NCC(=O)O", "C2H5NO2"),
    "Ala": ("CC(N)C(=O)O", "C3H7NO2"),
    "Val": ("CC(C)C(N)C(=O)O", "C5H11NO2"),
    "Leu": ("CC(C)CC(N)C(=O)O", "C6H13NO2"),
    "Ile": ("CCC(C)C(N)C(=O)O", "C6H13NO2"),
    "Pro": ("OC(=O)C1CCCN1", "C5H9NO2"),
    "Phe": ("NC(Cc1ccccc1)C(=O)O", "C9H11NO2"),
    "Trp": ("NC(Cc1c[nH]c2ccccc12)C(=O)O", "C11H12N2O2"),
    "Met": ("CSCCC(N)C(=O)O", "C5H11NO2S"),
    "Ser": ("NC(CO)C(=O)O", "C3H7NO3"),
    "Thr": ("CC(O)C(N)C(=O)O", "C4H9NO3"),
    "Cys": ("NC(CS)C(=O)O", "C3H7NO2S"),
    "Tyr": ("NC(Cc1ccc(O)cc1)C(=O)O", "C9H11NO3"),
    "Asn": ("NC(CC(N)=O)C(=O)O", "C4H8N2O3"),
    "Gln": ("NC(CCC(N)=O)C(=O)O", "C5H10N2O3"),
    "Asp": ("NC(CC(=O)O)C(=O)O", "C4H7NO4"),
    "Glu": ("NC(CCC(=O)O)C(=O)O", "C5H9NO4"),
    "Lys": ("NCCCCC(N)C(=O)O", "C6H14N2O2"),
    "Arg": ("NC(CCCNC(=N)N)C(=O)O", "C6H14N4O2"),
    "His": ("NC(Cc1c[nH]cn1)C(=O)O", "C6H9N3O2"),
}

TOLERANCE_PPM = 20.0
MIN_REL_INTENSITY = 0.01  # 1% of that scan's base peak


def build_products() -> list[dict]:
    """Fluoroacetylate all 20 AAs; returns one dict per (AA, reactive site)."""
    products = []
    for name, (smiles, expected_formula) in AMINO_ACIDS.items():
        mol = Chem.MolFromSmiles(smiles)
        actual_formula = rdMolDescriptors.CalcMolFormula(mol)
        assert actual_formula == expected_formula, (
            f"{name}: SMILES gives {actual_formula}, expected {expected_formula}"
        )
        prods = fluoroacetylate(mol)
        for site_idx, p in enumerate(prods):
            products.append({
                "aa": name,
                "site": site_idx,
                "n_sites": len(prods),
                "product": p,
            })
    return products


def run_benchmark():
    products = build_products()
    print(f"Built {len(products)} fluoroacetyl product(s) from {len(AMINO_ACIDS)} amino acids.\n")

    no_site = [name for name in AMINO_ACIDS if not any(p["aa"] == name for p in products)]
    multi_site = {p["aa"]: p["n_sites"] for p in products if p["n_sites"] > 1}
    print(f"No reactive primary amine found: {no_site or '(none)'}")
    print(f"Multiple reactive sites found: {multi_site or '(none)'}\n")

    print(f"{'AA':6s} {'site':4s} {'formula':14s} {'exact_mass':>11s} {'[M+H]+':>11s} {'[M-H]-':>11s}")
    for p in products:
        prod = p["product"]
        print(f"{p['aa']:6s} {p['site']:<4d} {prod.product_formula:14s} "
              f"{prod.product_exact_mass:11.4f} {prod.mz_pos_m_plus_h:11.4f} {prod.mz_neg_m_minus_h:11.4f}")

    # search: batch all targets per file in ONE pass (not one file-load per target)
    discovered = find_mzml_files()
    if not discovered:
        print("\nNo local mzML files found under data/HRMS/ -- skipping the search step.")
        return products, []

    print(f"\nSearching {len(discovered)} local mzML file(s) "
          f"(MS1, {TOLERANCE_PPM:g}ppm, >= {MIN_REL_INTENSITY:.0%} rel. intensity)...")

    hit_rows = []
    for label, path in discovered:
        overview = get_file_overview(path)
        polarity = max(overview.polarity_counts, key=overview.polarity_counts.get, default=None)
        if polarity not in ("+", "-"):
            continue

        targets = []
        for p in products:
            prod = p["product"]
            target_label = f"{p['aa']}_site{p['site']}"
            mz = prod.mz_pos_m_plus_h if polarity == "+" else prod.mz_neg_m_minus_h
            targets.append((target_label, mz))

        results = find_scans_with_multiple_mz(
            path, targets, tolerance=TOLERANCE_PPM, unit="ppm",
            min_relative_intensity=MIN_REL_INTENSITY, ms_level=1,
        )
        for target_label, matches in results.items():
            if not matches:
                continue
            top = max(matches, key=lambda m: m.intensity)
            hit_rows.append({
                "file": label, "target": target_label, "n_hits": len(matches),
                "apex_rt_min": top.rt_minutes, "apex_intensity": top.intensity,
                "apex_rel_intensity": top.relative_intensity,
            })

    print(f"\n{len(hit_rows)} (file, target) combinations with a hit:")
    if hit_rows:
        print(f"{'file':30s} {'target':14s} {'n_hits':>7s} {'RT(min)':>8s} {'intensity':>12s} {'rel%':>6s}")
        for h in sorted(hit_rows, key=lambda r: -r["apex_intensity"]):
            print(f"{h['file']:30s} {h['target']:14s} {h['n_hits']:7d} {h['apex_rt_min']:8.2f} "
                  f"{h['apex_intensity']:12.3e} {h['apex_rel_intensity']:6.0%}")
    else:
        print("  (none)")

    return products, hit_rows


if __name__ == "__main__":
    run_benchmark()
