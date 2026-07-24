import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.models import BaseGenerationParams


def fixture_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def test_normalize_miller_reduces_common_factor_and_preserves_sign():
    from llm_matgen.generators.extended import normalize_miller

    assert normalize_miller((2, -2, 0)) == (1, -1, 0)
    assert normalize_miller((-3, 0, 3)) == (-1, 0, 1)


def test_normalize_miller_rejects_zero_index():
    from llm_matgen.generators.extended import normalize_miller

    with pytest.raises(ValueError, match="non-zero"):
        normalize_miller((0, 0, 0))


def test_estimate_structure_size_counts_only_material_repetitions():
    from llm_matgen.generators.extended import estimate_structure_size

    assert estimate_structure_size(fixture_structure(), (2, 3, 1)) == 12


def test_base_params_reject_non_positive_atom_limit():
    with pytest.raises(ValidationError):
        BaseGenerationParams(max_atoms_per_structure=0)
    assert BaseGenerationParams(max_atoms_per_structure=10).max_atoms_per_structure == 10
