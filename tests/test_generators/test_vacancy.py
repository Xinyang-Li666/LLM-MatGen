import pytest
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_vacancy_removes_target_and_records_lineage():
    from llm_matgen.generators.vacancy import VacancyGenerator, VacancyParams

    result = VacancyGenerator().generate(
        fixture_structure(),
        VacancyParams(target_elements=["Co"], counts=[1], seed=7),
    )

    assert result.generated_count == 1
    child = result.generated[0]
    assert child.structure.composition.reduced_formula == "LiO2"
    assert child.record.parent_structure_id
    assert child.record.site_mapping
    assert child.record.actual_parameters["actual_count"] == 1


def test_vacancy_rejects_missing_or_excess_targets():
    from llm_matgen.generators.vacancy import VacancyGenerator, VacancyParams

    with pytest.raises(ValueError, match="target"):
        VacancyGenerator().generate(
            fixture_structure(),
            VacancyParams(target_elements=["Fe"], counts=[1], seed=7),
        )

    with pytest.raises(ValueError, match="available"):
        VacancyGenerator().generate(
            fixture_structure(),
            VacancyParams(target_elements=["Co"], counts=[2], seed=7),
        )


def test_vacancy_seed_is_reproducible():
    from llm_matgen.generators.vacancy import VacancyGenerator, VacancyParams
    from llm_matgen.utils.structure import structure_sha256

    params = VacancyParams(target_elements=["O"], counts=[1], variants_per_count=2, seed=7)
    first = VacancyGenerator().generate(fixture_structure(), params)
    second = VacancyGenerator().generate(fixture_structure(), params)

    assert [
        structure_sha256(item.structure) for item in first.generated
    ] == [structure_sha256(item.structure) for item in second.generated]
