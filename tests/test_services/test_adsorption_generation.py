from datetime import datetime, timezone

import pytest
from pymatgen.core import Lattice, Molecule, Structure


class _Source:
    def get(self, reference):
        from llm_matgen.sources.models import SourceStructure
        from llm_matgen.utils.structure import structure_sha256

        structure = Structure(Lattice.from_parameters(4, 4, 14, 90, 90, 90), ["Cu"] * 4, [[0, 0, 0.4], [0.5, 0, 0.4], [0, 0.5, 0.4], [0.5, 0.5, 0.4]])
        digest = structure_sha256(structure)
        return SourceStructure(
            artifact_id=digest, source_kind="local", source_reference=reference,
            structure_hash=digest, retrieved_at=datetime.now(timezone.utc), structure=structure,
        )

    def get_molecule(self, reference):
        from llm_matgen.sources.models import SourceMolecule

        molecule = Molecule(["H"], [[0, 0, 0]])
        return SourceMolecule(
            artifact_id="molecule-h", source_kind="local", source_reference=reference,
            molecule_hash="molecule-h", retrieved_at=datetime.now(timezone.utc), molecule=molecule,
        )


def _request(tmp_path, refs=("slab", "adsorbate")):
    from llm_matgen.services.generation import ExecutionLimits, GenerationRequest

    return GenerationRequest(
        generator="adsorption", input_refs=list(refs),
        parameters={"max_structures": 1, "site_types": ["top"]},
        limits=ExecutionLimits(output_root=tmp_path),
    )


def test_adsorption_uses_typed_structure_and_molecule_inputs(tmp_path):
    from llm_matgen.services.generation import GenerationService, default_generator_registry

    specs = default_generator_registry()["adsorption"].inputs
    assert [(item.role, item.kind, item.cardinality) for item in specs] == [
        ("slab", "structure", "one"), ("adsorbate", "molecule", "one")
    ]
    result = GenerationService(_Source()).run(_request(tmp_path))
    assert result.ok
    assert result.runs[0].generation.defect_type == "adsorption"


def test_adsorption_rejects_missing_or_extra_input_roles(tmp_path):
    from llm_matgen.services.generation import GenerationService, GenerationServiceError

    service = GenerationService(_Source())
    with pytest.raises(GenerationServiceError, match="slab.*adsorbate"):
        service.run(_request(tmp_path, refs=("slab",)))
    with pytest.raises(GenerationServiceError, match="slab.*adsorbate"):
        service.run(_request(tmp_path, refs=("slab", "adsorbate", "extra")))


def test_local_source_reads_xyz_molecule(tmp_path):
    from llm_matgen.sources.local import LocalStructureSource

    path = tmp_path / "adsorbate.xyz"
    path.write_text("2\nOH\nO 0 0 0\nH 0 0 0.97\n", encoding="utf-8")
    result = LocalStructureSource([tmp_path]).get_molecule(str(path))
    assert [str(site.specie) for site in result.molecule] == ["O", "H"]
    assert result.local_path == path.resolve()
