import pytest
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_doping_replaces_target_and_records_site_mapping():
    from llm_matgen.generators.doping import DopingGenerator, DopingParams

    result = DopingGenerator().generate(
        fixture_structure(),
        DopingParams(
            dopant_elements=["Ni"],
            target_elements=["Co"],
            dopant_counts=[1],
            seed=7,
        ),
    )

    assert result.generated_count == 1
    child = result.generated[0]
    assert child.structure.composition.reduced_formula == "LiNiO2"
    assert child.record.actual_parameters["dopant_elements"] == ["Ni"]
    assert any(old != new for old, new in child.record.site_mapping.items() if new)


def test_doping_supports_multi_element_combinations_and_rejects_invalid_targets():
    from llm_matgen.generators.doping import DopingGenerator, DopingParams

    result = DopingGenerator().generate(
        fixture_structure(),
        DopingParams(
            dopant_elements=["Ni", "Mn"],
            target_elements=["Co"],
            dopant_counts=[1],
            variants_per_combination=2,
            seed=7,
        ),
    )
    assert result.generated_count == 2

    with pytest.raises(ValueError, match="target"):
        DopingGenerator().generate(
            fixture_structure(),
            DopingParams(
                dopant_elements=["Ni"],
                target_elements=["Fe"],
                dopant_counts=[1],
                seed=7,
            ),
        )
