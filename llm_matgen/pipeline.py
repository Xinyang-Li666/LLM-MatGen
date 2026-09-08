"""Deterministic generation, check, export, and manifest pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pymatgen.core import Structure

from llm_matgen import __version__

from llm_matgen.checks.checker import LightStructureChecker
from llm_matgen.checks.models import CheckIssue, CheckReport
from llm_matgen.generators.models import GenerationResult, JsonValue
from llm_matgen.io.exporters import ExportArtifact, ExportOptions, StructureExporter
from llm_matgen.io.manifest import (
    ManifestArtifact,
    ManifestStore,
    ManifestStructure,
    RunManifest,
)


@dataclass
class PipelineResult:
    generation: GenerationResult
    check_reports: dict[str, CheckReport]
    artifacts: list[ExportArtifact]
    manifest_path: Path
    ok: bool
    viewer_path: Path | None = None
    errors: list[str] = field(default_factory=list)


class GenerationPipeline:
    def __init__(
        self,
        output_root: Path,
        *,
        checker: LightStructureChecker | None = None,
        exporter: StructureExporter | None = None,
        software_version: str = __version__,
    ):
        self.output_root = Path(output_root).resolve()
        self.checker = checker or LightStructureChecker()
        self.exporter = exporter or StructureExporter()
        self.software_version = software_version

    def run(
        self,
        generator,
        structure,
        params,
        export_options: ExportOptions,
        *,
        run_id: str | None = None,
        artifact_contributor=None,
        viewer: bool = True,
    ) -> PipelineResult:
        generation = generator.generate(structure, params)
        resolved_run_id = run_id or f"run-{uuid4().hex[:12]}"
        run_dir = self.output_root / resolved_run_id
        structures_dir = run_dir / "structures"
        structures_dir.mkdir(parents=True, exist_ok=False)
        options = export_options.model_copy(update={"output_dir": structures_dir})

        reports: dict[str, CheckReport] = {}
        artifacts: list[ExportArtifact] = []
        errors: list[str] = []
        warnings: list[str] = []
        preview_entries: list[tuple[str, Structure]] = []
        manifest_structures: list[ManifestStructure] = []
        manifest_artifacts: list[ManifestArtifact] = []

        reference = structure if isinstance(structure, Structure) else getattr(structure, "substrate", None)
        for generated in generation.generated:
            record = generated.record
            report = self.checker.check(generated.structure, reference=reference)
            reports[record.structure_id] = report
            manifest_structures.append(
                ManifestStructure(
                    structure_id=record.structure_id,
                    parent_structure_id=record.parent_structure_id,
                    parent_structure_ids=record.parent_structure_ids,
                    formula=record.formula,
                    n_atoms=record.n_atoms,
                    actual_parameters=record.actual_parameters,
                    site_mapping=record.site_mapping,
                    check_issues=[issue.model_dump(mode="json") for issue in report.issues],
                )
            )
            if not report.can_export:
                errors.append(f"{record.structure_id}: lightweight check contains errors")
                continue
            try:
                exported = self.exporter.export_structure(
                    generated.structure,
                    record.structure_id,
                    options,
                )
            except Exception as exc:
                errors.append(f"{record.structure_id}: export failed: {exc}")
                continue
            artifacts.extend(exported.artifacts)
            if exported.artifacts:
                preview_entries.append((record.structure_id, generated.structure))
            for artifact in exported.artifacts:
                manifest_artifacts.append(
                    ManifestArtifact(
                        structure_id=artifact.structure_id,
                        format=artifact.format.value,
                        path=artifact.path.relative_to(run_dir).as_posix(),
                        sha256=artifact.sha256,
                        metadata=artifact.metadata,
                    )
                )

        viewer_path = None
        if viewer and preview_entries:
            try:
                from llm_matgen import viewer as viewer_module

                viewer_artifact = viewer_module.write_viewer(preview_entries, run_dir / "viewer.html")
                viewer_path = viewer_artifact.path
                manifest_artifacts.append(
                    ManifestArtifact(
                        structure_id="__run__",
                        format="html",
                        path=viewer_artifact.path.relative_to(run_dir).as_posix(),
                        sha256=viewer_artifact.sha256,
                        metadata={"run_level": True, "offline": True},
                    )
                )
            except Exception as exc:
                warnings.append(f"viewer generation failed: {exc}")

        if artifact_contributor is not None:
            contributed = artifact_contributor(run_dir, structure, generation)
            for artifact in contributed:
                manifest_artifacts.append(
                    ManifestArtifact(
                        structure_id="__run__",
                        format=f"adsorption/{artifact.kind}",
                        path=artifact.path.relative_to(run_dir).as_posix(),
                        sha256=artifact.sha256,
                        metadata={"run_level": True},
                    )
                )

        provenance = generation.provenance
        manifest = RunManifest(
            run_id=resolved_run_id,
            created_at=datetime.now(timezone.utc),
            software_version=self.software_version,
            input_source=provenance.input_source if provenance else "unknown",
            parameters=provenance.parameters if provenance else {},
            structures=manifest_structures,
            artifacts=manifest_artifacts,
            warnings=[*generation.warnings, *warnings, *errors],
        )
        manifest_path = ManifestStore(self.output_root).write_atomic(
            manifest,
            allow_existing_dir=True,
        )
        return PipelineResult(
            generation=generation,
            check_reports=reports,
            artifacts=artifacts,
            manifest_path=manifest_path,
            ok=not errors and len(artifacts) > 0,
            viewer_path=viewer_path,
            errors=errors,
        )
