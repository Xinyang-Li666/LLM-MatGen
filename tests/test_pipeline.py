from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pymatgen.core import Lattice, Structure


def make_fixture() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


@dataclass
class IdentityGenerator:
    defect_name: str = "identity"

    def generate(self, structure, params):
        from llm_matgen.generators.models import (
            GeneratedStructure,
            GenerationResult,
            Provenance,
            StructureRecord,
        )

        parent_id = "parent-1"
        child = structure.copy()
        record = StructureRecord(
            structure_id="child-1",
            parent_structure_id=parent_id,
            formula=child.composition.reduced_formula,
            n_atoms=len(child),
            actual_parameters={},
            site_mapping={},
        )
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            generated=[GeneratedStructure(child, record)],
            provenance=Provenance(
                generator=self.defect_name,
                generator_version="test",
                input_source="fixture",
                input_structure_hash="parent-hash",
                parameters={},
                seed=7,
                created_at=datetime.now(timezone.utc),
            ),
        )


def test_pipeline_runs_generation_checks_exports_and_manifest(tmp_path: Path):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.pipeline import GenerationPipeline

    result = GenerationPipeline(tmp_path).run(
        IdentityGenerator(),
        make_fixture(),
        params={},
        export_options=ExportOptions(
            formats=[
                OutputFormat.POSCAR,
                OutputFormat.CIF,
                OutputFormat.LAMMPS_DATA,
            ],
        ),
        run_id="run-pipeline",
    )

    assert result.ok is True
    assert result.generation.generated_count == 1
    assert len(result.artifacts) == 3
    assert result.manifest_path.is_file()


def test_pipeline_writes_manifest_when_every_structure_has_error(tmp_path: Path):
    from llm_matgen.checks.checker import LightStructureChecker
    from llm_matgen.checks.models import CheckIssue, CheckReport
    from llm_matgen.generators.models import CheckLevel
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.pipeline import GenerationPipeline

    class ErrorChecker(LightStructureChecker):
        def check(self, structure, reference=None, min_distance=0.8):
            return CheckReport(
                n_atoms=len(structure),
                formula=structure.composition.reduced_formula,
                issues=[
                    CheckIssue(
                        code="forced-error",
                        level=CheckLevel.ERROR,
                        message="test error",
                    )
                ],
            )

    result = GenerationPipeline(tmp_path, checker=ErrorChecker()).run(
        IdentityGenerator(),
        make_fixture(),
        params={},
        export_options=ExportOptions(),
        run_id="run-error",
    )

    assert result.ok is False
    assert result.artifacts == []
    assert result.manifest_path.is_file()
