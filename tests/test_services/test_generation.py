from datetime import datetime, timezone

import pytest
from pymatgen.core import Lattice, Structure

from llm_matgen.sources.models import SourceStructure
from llm_matgen.utils.structure import structure_sha256


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Co", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


class FakeSource:
    def __init__(self, structures=None):
        self.structures = structures or {"input": fixture_structure()}

    def get(self, reference):
        structure = self.structures[reference].copy()
        digest = structure_sha256(structure)
        return SourceStructure(
            artifact_id=digest,
            source_kind="local",
            source_reference=reference,
            structure_hash=digest,
            retrieved_at=datetime.now(timezone.utc),
            structure=structure,
        )


def make_request(tmp_path, **updates):
    from llm_matgen.services.generation import ExecutionLimits, GenerationRequest

    values = dict(
        generator="vacancy",
        input_refs=["input"],
        parameters={"target_elements": ["Co"], "counts": [1], "seed": 7},
        limits=ExecutionLimits(output_root=tmp_path),
    )
    values.update(updates)
    return GenerationRequest(**values)


def test_generation_service_runs_source_generator_check_export_and_manifest(tmp_path):
    from llm_matgen.services.generation import GenerationService

    result = GenerationService(source=FakeSource()).run(make_request(tmp_path))
    assert result.ok
    assert len(result.runs) == 1
    assert result.runs[0].generation.defect_type == "vacancy"
    assert result.runs[0].manifest_path.exists()


def test_generation_registry_contains_ten_stable_names():
    from llm_matgen.services.generation import default_generator_registry

    assert set(default_generator_registry()) == {
        "vacancy", "interstitial", "doping", "solid-solution", "surface",
        "grain-boundary", "interface", "stacking-fault", "dislocation", "adsorption",
    }


def test_generation_service_rejects_unknown_invalid_interface_and_limits(tmp_path):
    from llm_matgen.services.generation import GenerationService, GenerationServiceError

    service = GenerationService(source=FakeSource())
    with pytest.raises(GenerationServiceError, match="unknown generator"):
        service.run(make_request(tmp_path, generator="unknown"))
    with pytest.raises(GenerationServiceError, match="parameters"):
        service.run(make_request(tmp_path, parameters={"target_elements": []}))
    with pytest.raises(GenerationServiceError, match="two input"):
        service.run(make_request(tmp_path, generator="interface", parameters={}))
    with pytest.raises(GenerationServiceError, match="atom limit"):
        service.run(
            make_request(
                tmp_path,
                limits={"output_root": tmp_path, "max_atoms_per_structure": 1},
            )
        )
