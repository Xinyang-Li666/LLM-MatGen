import pytest
from pydantic import ValidationError


def test_generation_models_validate_and_round_trip():
    from llm_matgen.generators.models import (
        BaseGenerationParams,
        CheckLevel,
        GenerationResult,
        OutputFormat,
        Provenance,
        RandomGenerationParams,
    )

    assert BaseGenerationParams().max_structures == 1000
    assert RandomGenerationParams(seed=None).seed is None
    assert RandomGenerationParams(seed=-7).seed == -7
    assert list(OutputFormat) == [
        OutputFormat.POSCAR,
        OutputFormat.CIF,
        OutputFormat.LAMMPS_DATA,
    ]
    assert [level.value for level in CheckLevel] == ["info", "warning", "error"]

    provenance = Provenance(
        generator="test",
        generator_version="0.1.0",
        input_source="fixture",
        input_structure_hash="abc",
        parameters={"count": 1},
        seed=7,
        created_at="2026-07-24T00:00:00Z",
    )
    restored = Provenance.model_validate_json(provenance.model_dump_json())
    assert restored == provenance
    assert GenerationResult(defect_type="vacancy").generated_count == 0


def test_generation_models_reject_invalid_limits_and_conflicting_combine():
    from llm_matgen.generators.models import (
        BaseGenerationParams,
        GenerationResult,
    )

    with pytest.raises(ValidationError):
        BaseGenerationParams(max_structures=0)

    left = GenerationResult(defect_type="vacancy", input_count=1)
    right = GenerationResult(defect_type="doping", input_count=1)
    with pytest.raises(ValueError, match="defect_type"):
        left.combine(right)
