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
    from llm_matgen.generators.solid_solution import SolidSolutionParams

    params = SolidSolutionParams(
        target_element="Co",
        substituents={"Ni": 1.0},
        method="sqs",
        sqs_iterations=100,
        seed=7,
    )
    assert params.sqs_iterations == 100


def test_sqs_failure_suggests_random(monkeypatch):
    from llm_matgen.generators import backends
    from llm_matgen.generators.solid_solution import (
        SolidSolutionGenerator,
        SolidSolutionParams,
    )

    def fail(*args, **kwargs):
        raise backends.BackendGenerationError("optimizer failed")

    monkeypatch.setattr(backends.SQSBackend, "generate", fail)
    params = SolidSolutionParams(
        target_element="Co",
        substituents={"Ni": 1.0},
        method="sqs",
        seed=7,
    )
    with pytest.raises(backends.BackendGenerationError, match="method random"):
        SolidSolutionGenerator().generate(fixture_structure(), params)


def test_sqs_config_preserves_seed_and_composition():
    from llm_matgen.generators.backends import SQSBackend

    structure = fixture_structure()
    structure.append("Co", [0.25, 0.25, 0.25])
    config = SQSBackend.build_config(
        structure,
        target_element="Co",
        substituents={"Ni": 0.5, "Mn": 0.5},
        iterations=100,
        seed=7,
    )

    assert config["iterations"] == 100
    assert config["seed"] == 7
    assert config["thread_config"] == [1]
    assert config["composition"] == [
        {"sites": "Li", "Li": 1},
        {"sites": "Co", "Co": 0, "Ni": 1, "Mn": 1},
        {"sites": "O", "O": 2},
    ]


def test_sqs_integration_generates_structure_when_backend_is_installed():
    pytest.importorskip("sqsgenerator")
    from llm_matgen.generators.solid_solution import SolidSolutionGenerator, SolidSolutionParams

    structure = fixture_structure()
    structure.make_supercell((2, 2, 2))
    result = SolidSolutionGenerator().generate(
        structure,
        SolidSolutionParams(
            target_element="Co",
            substituents={"Ni": 0.5, "Mn": 0.5},
            method="sqs",
            sqs_iterations=10,
            seed=7,
        ),
    )

    assert result.generated_count == 1
    assert len(result.generated[0].structure) == len(structure)
    assert result.generated[0].record.actual_parameters["method"] == "sqs"
