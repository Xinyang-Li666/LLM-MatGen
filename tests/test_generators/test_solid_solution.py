import pytest
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_random_solid_solution_replaces_target_by_requested_ratio():
    from llm_matgen.generators.solid_solution import (
        SolidSolutionGenerator,
        SolidSolutionParams,
    )

    result = SolidSolutionGenerator().generate(
        fixture_structure(),
        SolidSolutionParams(
            target_element="Co",
            substituents={"Ni": 0.5, "Mn": 0.5},
            variants=1,
            seed=7,
            supercell=((2, 0, 0), (0, 1, 0), (0, 0, 1)),
        ),
    )

    assert result.generated_count == 1
    child = result.generated[0]
    assert child.structure.composition["Co"] == 0
    assert child.structure.composition["Ni"] == 1
    assert child.structure.composition["Mn"] == 1
    assert child.record.actual_parameters["actual_ratios"] == {"Ni": 0.5, "Mn": 0.5}


def test_solid_solution_rejects_invalid_ratios():
    from llm_matgen.generators.solid_solution import (
        SolidSolutionGenerator,
        SolidSolutionParams,
    )

    with pytest.raises(ValueError, match="sum"):
        SolidSolutionParams(target_element="Co", substituents={"Ni": 0.4}, seed=7)


def test_sqs_requires_optional_backend():
    from llm_matgen.generators.solid_solution import (
        SolidSolutionGenerator,
        SolidSolutionParams,
    )

    with pytest.raises(ImportError, match="sqsgenerator"):
        SolidSolutionGenerator().generate(
            fixture_structure(),
            SolidSolutionParams(
                target_element="Co",
                substituents={"Ni": 1.0},
                method="sqs",
                seed=7,
            ),
        )
