"""Orchestration for trajectory conversion, sampling, and filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from llm_matgen.checks.checker import LightStructureChecker
from llm_matgen import __version__
from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.manifest import ManifestArtifact, ManifestStore, ManifestStructure, RunManifest
from llm_matgen.utils.structure import structure_sha256

from .deepmd import DeepMDFrameReader
from .exporters import FrameSeriesExporter
from .filter import FilterConfig, FilterResult, filter_trajectory as _run_filter
from .readers import ASETrajectoryReader
from .sampling import select_frames


class TrajectoryService:
    def _run(self, reader, frames, output_root: Path, formats: list[OutputFormat], parameters: dict):
        run_id = f"trajectory-{uuid4().hex[:12]}"
        run_dir = Path(output_root) / run_id
        structures_dir = run_dir / "structures"
        structures_dir.mkdir(parents=True, exist_ok=False)
        checker = LightStructureChecker()
        selected = list(frames)
        if not selected:
            raise ValueError("no frames selected from trajectory")
        manifest_structures, failures = [], []
        for frame in selected:
            report = checker.check(frame.structure)
            sid = structure_sha256(frame.structure)
            manifest_structures.append(ManifestStructure(
                structure_id=sid, parent_structure_id=sid,
                formula=frame.structure.composition.reduced_formula,
                n_atoms=len(frame.structure),
                actual_parameters={"source_index": frame.source_index, **frame.metadata},
                check_issues=[issue.model_dump(mode="json") for issue in report.issues],
            ))
            if not report.can_export:
                failures.append(f"frame {frame.source_index}: structure check contains errors")
        if failures:
            raise ValueError("; ".join(failures))
        artifacts = FrameSeriesExporter().export(selected, structures_dir, formats)
        manifest_artifacts = [ManifestArtifact(
            structure_id=manifest_structures[item["export_index"] - 1].structure_id,
            format=item["format"], path=item["path"].relative_to(run_dir).as_posix(),
            sha256=item["sha256"], metadata={"source_index": item["source_index"]},
        ) for item in artifacts]
        manifest = RunManifest(
            run_id=run_id, created_at=datetime.now(timezone.utc), software_version=__version__,
            input_source=parameters.get("input_source", "trajectory"), parameters=parameters,
            structures=manifest_structures, artifacts=manifest_artifacts, warnings=failures,
        )
        return ManifestStore(output_root).write_atomic(manifest, allow_existing_dir=True)

    def convert_deepmd(self, input_dir: Path, output_root: Path, formats=None, stride: int = 1, type_map=None):
        reader = DeepMDFrameReader(input_dir, type_map=type_map)
        frames = select_frames(reader, "all", stride=stride)
        return self._run(reader, frames, output_root, formats or [OutputFormat.POSCAR],
                         {"operation": "convert-deepmd", "input_source": str(input_dir), "stride": stride})

    def sample_trajectory(self, input_path: Path, output_root: Path, method: str, count: int,
                          seed: int | None = None, input_format: str | None = None,
                          formats=None, lammps_element_map=None):
        reader = ASETrajectoryReader(input_path, input_format, lammps_element_map)
        frames = select_frames(reader, method, count=count, seed=seed)
        return self._run(reader, frames, output_root, formats or [OutputFormat.POSCAR],
                         {"operation": "sample-trajectory", "input_source": str(input_path),
                          "method": method, "count": count, "seed": seed, "input_format": reader.format})

    def filter_trajectory(self, input_path: Path, output_dir: Path,
                          config: FilterConfig | None = None,
                          *,
                          reference_path: Path | None = None,
                          model_name: str = "",
                          type_map: dict[int, int] | None = None,
                          input_format: str | None = None) -> FilterResult:
        """Run quality filtering on a trajectory (see :func:`filter.filter_trajectory`)."""
        return _run_filter(
            input_path, output_dir, config,
            reference_path=reference_path, model_name=model_name,
            type_map=type_map, input_format=input_format,
        )
