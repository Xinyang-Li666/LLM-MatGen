import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_supercell_expansion_and_parameter_validation():
    from llm_matgen.generators.base import Supercell, apply_supercell

    structure = fixture_structure()
    assert apply_supercell(structure, Supercell()).num_sites == structure.num_sites
    assert (
        apply_supercell(
            structure,
            Supercell(
                matrix=((2, 0, 0), (0, 1, 0), (0, 0, 1)),
            ),
        ).num_sites
        == structure.num_sites * 2
    )

    with pytest.raises(ValidationError):
        Supercell(matrix=((0, 0, 0), (0, 1, 0), (0, 0, 1)))
