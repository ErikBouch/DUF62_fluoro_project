"""
insilico_library/acylation.py — add acetyl / fluoroacetyl to a primary amine
via a real chemical transformation (RDKit reaction), not string arithmetic.

The formula delta for N-acylation is simple (+C2H1FO1 for fluoroacetyl,
+C2H2O1 for acetyl -- see FORMULA_DELTA below) and computed here purely as a
cheap cross-check. The InChI is NOT derived from that arithmetic -- it comes
from actually reacting the parsed molecule and re-deriving the InChI from the
real product structure, which is the only way to get it correct (InChI
depends on full connectivity/stereochemistry, not just atom counts).

Reaction: [primary amine, excluding amide/sulfonamide N] -> [amide].
A molecule with multiple independent primary-amine sites (e.g. lysine's alpha-
and epsilon-amines) yields one product PER site -- each is a separate,
independently valid mono-acylated regiochemistry, not summed into one result.

Multi-site acylation (more than one site acylated at once) is supported as
FORMULA/MASS ONLY, via `multi_degree_formulas()`: no representative
structure/InChI is generated for degree>1, and no priority is assigned between
candidate sites (no tiering by amine "reactivity", no picking a canonical
position) -- keeping this cheap on purpose. Degree-1 products (from
`acylate()`/`fluoroacetylate()`/`acetylate()`, one per site)
already have real per-site InChIs; that's unaffected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdChemReactions, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")

PROTON = 1.007276  # mass of H+, standard MS adduct convention

# Same primary-amine definition used in db_loader.py's has_primary_amine flag:
# N with 2 H's, excluding amide (N-C=O) and sulfonamide (N-S(=O)(=O)) nitrogens.
_AMINE_FILTER = "NX3H2;!$(NC(=O));!$(NS(=O)(=O))"

# Human-readable name for the functional group `_AMINE_FILTER` targets --
# primary amine is the only one implemented so far (chosen as the easiest
# benchmark case), not a permanent assumption. Callers that report which
# functional group a given run reacted on (e.g. a run summary) should read
# this rather than hardcoding "primary amine" themselves, so adding a second
# functional group later is a one-place change, not a find-and-replace.
REACTIVE_GROUP_LABEL = "primary amine"

REACTIONS = {
    "fluoroacetyl": rdChemReactions.ReactionFromSmarts(f"[{_AMINE_FILTER}:1]>>[N:1]C(=O)CF"),
    "acetyl": rdChemReactions.ReactionFromSmarts(f"[{_AMINE_FILTER}:1]>>[N:1]C(=O)C"),
}

# Net atomic change per acylated site, as a cheap arithmetic cross-check
# against the RDKit-derived product formula (not used to build the InChI).
FORMULA_DELTA = {
    "fluoroacetyl": {"C": 2, "H": 1, "F": 1, "O": 1},
    "acetyl": {"C": 2, "H": 2, "O": 1},
}


@dataclass
class AcylationProduct:
    reaction: str  # 'fluoroacetyl' or 'acetyl'
    product_inchi: str
    product_inchikey: str
    product_smiles: str
    product_formula: str  # from RDKit, on the actual reacted structure
    product_formula_from_delta: str  # from simple arithmetic on the parent formula (cross-check)
    product_exact_mass: float
    mz_pos_m_plus_h: float
    mz_neg_m_minus_h: float


@dataclass
class DegreeFormula:
    """Formula/mass for 'degree' independent sites acylated at once -- no
    structure/InChI (multi-site products aren't given a representative
    structure; see module docstring)."""
    reaction: str
    degree: int
    formula: str
    exact_mass: float
    mz_pos_m_plus_h: float
    mz_neg_m_minus_h: float


def _parse_formula(formula: str) -> dict:
    """Parse a Hill-notation formula string ('C9H11NO2') into an element->count dict."""
    counts = {}
    for element, count in re.findall(r"([A-Z][a-z]?)(\d*)", formula):
        if not element:
            continue
        counts[element] = counts.get(element, 0) + (int(count) if count else 1)
    return counts


def _format_formula(counts: dict) -> str:
    """Format an element->count dict back to Hill notation (C, then H, then alphabetical)."""
    parts = []
    for element in ("C", "H"):
        if counts.get(element):
            parts.append(element + (str(counts[element]) if counts[element] > 1 else ""))
    for element in sorted(k for k in counts if k not in ("C", "H")):
        if counts[element]:
            parts.append(element + (str(counts[element]) if counts[element] > 1 else ""))
    return "".join(parts)


def apply_formula_delta(parent_formula: str, reaction: str, degree: int = 1) -> str:
    """
    Simple arithmetic formula for `degree` independent sites acylated at once
    (cross-check for degree=1 against the RDKit-derived product formula;
    authoritative -- the only thing we compute -- for degree>1, since we don't
    generate a structure for multi-site products).
    """
    counts = _parse_formula(parent_formula)
    for element, delta in FORMULA_DELTA[reaction].items():
        counts[element] = counts.get(element, 0) + delta * degree
    return _format_formula(counts)


def _to_mol(mol_or_inchi):
    if isinstance(mol_or_inchi, str):
        mol = Chem.MolFromInchi(mol_or_inchi)
        if mol is None:
            raise ValueError(f"RDKit could not parse InChI: {mol_or_inchi!r}")
        return mol
    return mol_or_inchi


def count_reactive_sites(mol_or_inchi) -> int:
    """Number of independent primary-amine sites (same filter as db_loader.py's has_primary_amine)."""
    mol = _to_mol(mol_or_inchi)
    return len(mol.GetSubstructMatches(Chem.MolFromSmarts(f"[{_AMINE_FILTER}]")))


def acylate(mol_or_inchi, reaction: str) -> list[AcylationProduct]:
    """
    Run the given reaction ('fluoroacetyl' or 'acetyl') on a molecule (RDKit
    Mol or an InChI string). Returns one AcylationProduct per independent
    reactive site found (0 if there's no matching primary amine).
    """
    mol = _to_mol(mol_or_inchi)

    parent_formula = rdMolDescriptors.CalcMolFormula(mol)
    delta_formula = apply_formula_delta(parent_formula, reaction)

    rxn = REACTIONS[reaction]
    products: list[AcylationProduct] = []
    seen_inchikeys = set()

    for (product_mol,) in rxn.RunReactants((mol,)):
        try:
            Chem.SanitizeMol(product_mol)
        except Exception:
            continue
        inchi = Chem.MolToInchi(product_mol)
        if not inchi:
            continue
        inchikey = Chem.InchiToInchiKey(inchi)
        if not inchikey or inchikey in seen_inchikeys:
            continue
        seen_inchikeys.add(inchikey)

        exact_mass = Descriptors.ExactMolWt(product_mol)
        products.append(
            AcylationProduct(
                reaction=reaction,
                product_inchi=inchi,
                product_inchikey=inchikey,
                product_smiles=Chem.MolToSmiles(product_mol),
                product_formula=rdMolDescriptors.CalcMolFormula(product_mol),
                product_formula_from_delta=delta_formula,
                product_exact_mass=exact_mass,
                mz_pos_m_plus_h=exact_mass + PROTON,
                mz_neg_m_minus_h=exact_mass - PROTON,
            )
        )
    return products


def fluoroacetylate(mol_or_inchi) -> list[AcylationProduct]:
    return acylate(mol_or_inchi, "fluoroacetyl")


def acetylate(mol_or_inchi) -> list[AcylationProduct]:
    return acylate(mol_or_inchi, "acetyl")


# Per-site mass delta, derived from RDKit itself (react a trivial test amine)
# rather than a hand-typed periodic table -- avoids any risk of atomic-mass
# typos, and self-validates against the reaction logic above.
_TEST_AMINE = Chem.MolFromSmiles("CN")  # methylamine
_TEST_AMINE_MASS = Descriptors.ExactMolWt(_TEST_AMINE)
_DELTA_MASS = {
    reaction: acylate(_TEST_AMINE, reaction)[0].product_exact_mass - _TEST_AMINE_MASS
    for reaction in REACTIONS
}


def multi_degree_formulas(mol_or_inchi, reaction: str) -> list[DegreeFormula]:
    """
    Formula + mass for every degree of acylation from 1 up to the number of
    independent reactive sites -- e.g. lysine (2 sites) gives degree 1
    (mono-acylated, either site -- same formula/mass regardless of which one)
    and degree 2 (both sites acylated at once).

    Deliberately NOT modeling which specific site(s) react first (no priority
    tiering, no representative structure/InChI for degree>1) -- multi-site
    acylation is optional, formula/mass only, kept cheap on purpose.
    """
    mol = _to_mol(mol_or_inchi)
    n_sites = count_reactive_sites(mol)
    parent_formula = rdMolDescriptors.CalcMolFormula(mol)
    parent_mass = Descriptors.ExactMolWt(mol)

    degrees = []
    for d in range(1, n_sites + 1):
        formula = apply_formula_delta(parent_formula, reaction, degree=d)
        mass = parent_mass + d * _DELTA_MASS[reaction]
        degrees.append(
            DegreeFormula(
                reaction=reaction,
                degree=d,
                formula=formula,
                exact_mass=mass,
                mz_pos_m_plus_h=mass + PROTON,
                mz_neg_m_minus_h=mass - PROTON,
            )
        )
    return degrees
