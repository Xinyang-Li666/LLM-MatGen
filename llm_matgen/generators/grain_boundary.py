"""Local grain-boundary generation through an isolated backend contract."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from pydantic import Field, NonNegativeFloat, PositiveInt, field_validator
from pymatgen.core import Structure

from llm_matgen.generators.backends import (
    GrainBoundaryBackend,
    PymatgenGrainBoundaryBackend,
)
from llm_matgen.generators.extended import MillerIndex, normalize_miller
from llm_matgen.generators.models import (
    BaseGenerationParams,
    GeneratedStructure,
    GenerationResult,
    Provenance,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class GrainBoundaryParams(BaseGenerationParams):
    rotation_axis: MillerIndex
    rotation_angles: list[float] = Field(min_length=1)
    plane: MillerIndex | None = None
    expand_times: PositiveInt = 4
    vacuum_thickness: NonNegativeFloat = 0
    ab_shift: tuple[float, float] = (0.0, 0.0)

    @field_validator("rotation_axis")
    @classmethod
    def validate_axis(cls, value: MillerIndex) -> MillerIndex:
        return normalize_miller(value)

    @field_validator("plane")
    @classmethod
    def validate_plane(cls, value: MillerIndex | None) -> MillerIndex | None:
        return normalize_miller(value) if value is not None else None

    @field_validator("rotation_angles")
    @classmethod
    def validate_angles(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(angle) or angle == 0 for angle in value):
            raise ValueError("rotation angles must be finite and non-zero")
        return value


class GrainBoundaryGenerator:
    defect_name = "grain_boundary"
    generator_version = "0.1.0"

    def __init__(self, backend: GrainBoundaryBackend | None = None):
        self.backend = backend or PymatgenGrainBoundaryBackend()

    def generate(self, structure: Structure, params: GrainBoundaryParams) -> GenerationResult:
        source = structure.copy()
        parent_id = structure_sha256(source)
        parent_sites = assign_site_ids(source, parent_id)
        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        seen: set[str] = set()

        for angle in params.rotation_angles:
            backend_result = self.backend.generate(
                source,
                rotation_axis=params.rotation_axis,
                rotation_angle=angle,
                plane=params.plane,
                expand_times=params.expand_times,
                vacuum_thickness=float(params.vacuum_thickness),
                ab_shift=params.ab_shift,
            )
            child = backend_result.structure
            if len(child) > params.max_atoms_per_structure:
                raise ValueError(
                    f"grain-boundary atom limit exceeded: {len(child)} > {params.max_atoms_per_structure}"
                )
            child_id = structure_sha256(child)
            if child_id in seen:
                warnings.append(f"duplicate grain boundary skipped for angle {angle}")
                continue
            seen.add(child_id)
            actual = {
                **backend_result.actual_parameters,
                "rotation_axis": list(params.rotation_axis),
                "plane": list(params.plane) if params.plane else None,
            }
            generated.append(
                GeneratedStructure(
                    structure=child,
                    record=StructureRecord(
                        structure_id=child_id,
                        parent_structure_id=parent_id,
                        formula=child.composition.reduced_formula,
                        n_atoms=len(child),
                        actual_parameters=actual,
                        site_mapping={site_id: None for site_id in parent_sites},
                    ),
                )
            )
            if len(generated) >= params.max_structures:
                warnings.append("grain-boundary variants truncated by max_structures")
                break

        if not generated:
            raise ValueError("grain-boundary generation produced no structures")
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            skipped_count=0,
            generated=generated,
            warnings=warnings,
            provenance=Provenance(
                generator=self.defect_name,
                generator_version=self.generator_version,
                input_source="in-memory",
                input_structure_hash=parent_id,
                parameters=params.model_dump(mode="json"),
                seed=None,
                created_at=datetime.now(timezone.utc),
            ),
        )
