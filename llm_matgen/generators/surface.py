"""Surface slab generation using pymatgen's local crystallographic tools."""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
from pydantic import Field, PositiveFloat, PositiveInt, field_validator
from pymatgen.core import Structure
from pymatgen.core.surface import SlabGenerator
from pymatgen.analysis.structure_matcher import StructureMatcher

from llm_matgen.generators.extended import MillerIndex, normalize_miller
from llm_matgen.generators.surface_cell import (
    InplaneTransform,
    apply_inplane_transform,
    find_inplane_transform,
    lattice_angles,
    measure_slab_dimensions,
    orthogonalize_c_axis,
)
from llm_matgen.generators.models import (
    BaseGenerationParams,
    GeneratedStructure,
    GenerationResult,
    Provenance,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class SurfaceParams(BaseGenerationParams):
    miller_indices: list[MillerIndex] = Field(min_length=1)
    min_slab_size: PositiveFloat
    min_vacuum_size: PositiveFloat
    center_slab: bool = True
    primitive: bool = True
    max_normal_search: PositiveInt | None = None

    @field_validator("miller_indices")
    @classmethod
    def validate_millers(cls, value: list[MillerIndex]) -> list[MillerIndex]:
        return list(dict.fromkeys(normalize_miller(index) for index in value))


class SurfaceGenerator:
    defect_name = "surface"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: SurfaceParams) -> GenerationResult:
        source = structure.copy()
        parent_id = structure_sha256(source)
        parent_sites = assign_site_ids(source, parent_id)
        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        matcher = StructureMatcher(primitive_cell=False, scale=True, attempt_supercell=False)

        for miller in params.miller_indices:
            builder = SlabGenerator(
                source,
                miller,
                float(params.min_slab_size),
                float(params.min_vacuum_size),
                center_slab=params.center_slab,
                primitive=params.primitive,
                max_normal_search=params.max_normal_search,
            )
            slabs = builder.get_slabs(symmetrize=False)
            if not slabs:
                warnings.append(f"no slab generated for Miller index {miller}")
                continue
            for termination, slab in enumerate(slabs):
                shaped, diagnostics, shape_warnings = self._shape_surface_cell(slab, params)
                warnings.extend(
                    f"Miller index {miller}, termination {termination}: {warning}"
                    for warning in shape_warnings
                )
                if len(shaped) > params.max_atoms_per_structure:
                    message = (
                        f"surface atom limit exceeded after cell shaping: "
                        f"base={len(slab)}, area_multiplier={diagnostics['area_multiplier']}, "
                        f"final={len(shaped)} > {params.max_atoms_per_structure}"
                    )
                    if params.cell_shape == "native":
                        raise ValueError(message)
                    warnings.append(
                        f"Miller index {miller}, termination {termination}: {message}"
                    )
                    continue
                child_id = structure_sha256(shaped)
                if any(matcher.fit(shaped, item.structure) for item in generated):
                    warnings.append(
                        f"duplicate surface skipped for Miller index {miller}, termination {termination}"
                    )
                    continue
                generated.append(
                    GeneratedStructure(
                        structure=shaped,
                        record=StructureRecord(
                            structure_id=child_id,
                            parent_structure_id=parent_id,
                            formula=shaped.composition.reduced_formula,
                            n_atoms=len(shaped),
                            actual_parameters={
                                "miller_index": list(miller),
                                "termination": termination,
                                **diagnostics,
                            },
                            site_mapping={site_id: None for site_id in parent_sites},
                        ),
                    )
                )
                if len(generated) >= params.max_structures:
                    warnings.append("surface variants truncated by max_structures")
                    break
            if len(generated) >= params.max_structures:
                break

        if not generated:
            raise ValueError("surface generation produced no structures")
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

    def _shape_surface_cell(
        self, slab: Structure, params: SurfaceParams
    ) -> tuple[Structure, dict[str, object], list[str]]:
        """Shape one slab and return diagnostics plus non-fatal warnings."""
        warnings: list[str] = []
        status = "native"
        shaped = slab.copy()
        transform = InplaneTransform(
            matrix=((1, 0), (0, 1)),
            lattice_angles=lattice_angles(shaped.lattice.matrix),
            area_multiplier=1,
            inplane_aspect_ratio=(
                float(np.linalg.norm(shaped.lattice.matrix[0]))
                / float(np.linalg.norm(shaped.lattice.matrix[1]))
            ),
            total_angle_error=float(
                sum(abs(angle - 90.0) for angle in lattice_angles(shaped.lattice.matrix))
            ),
            strict=all(
                abs(angle - 90.0) <= params.orthogonal_tolerance
                for angle in lattice_angles(shaped.lattice.matrix)
            ),
        )

        if params.cell_shape == "near-orthogonal":
            try:
                shaped = orthogonalize_c_axis(slab)
            except Exception as exc:
                status = "fallback-native"
                warnings.append(f"c-axis orthogonalization unavailable: {exc}")
            else:
                try:
                    candidate = find_inplane_transform(
                        shaped,
                        max_area=params.orthogonal_max_area,
                        tolerance=params.orthogonal_tolerance,
                    )
                    shaped_candidate = apply_inplane_transform(shaped, candidate)
                    transform = candidate
                    shaped = shaped_candidate
                    status = "strict" if transform.strict else "approximate"
                    if status == "approximate":
                        warnings.append(
                            "best integer cell is approximate; "
                            f"angles={tuple(round(value, 6) for value in transform.lattice_angles)}"
                        )
                except Exception as exc:
                    status = "fallback-c-orthogonal"
                    warnings.append(f"in-plane integer search unavailable: {exc}")

        final_angles = lattice_angles(shaped.lattice.matrix)
        span, vacuum = measure_slab_dimensions(shaped)
        a_length = float(np.linalg.norm(shaped.lattice.matrix[0]))
        b_length = float(np.linalg.norm(shaped.lattice.matrix[1]))
        diagnostics = {
            "cell_shape_requested": params.cell_shape,
            "cell_shape_status": status,
            "inplane_transform": [list(row) for row in transform.matrix],
            "area_multiplier": transform.area_multiplier,
            "lattice_lengths": [
                float(np.linalg.norm(vector)) for vector in shaped.lattice.matrix
            ],
            "lattice_angles": [float(angle) for angle in final_angles],
            "inplane_aspect_ratio": max(a_length, b_length) / min(a_length, b_length),
            "cell_height": float(np.linalg.norm(shaped.lattice.matrix[2])),
            "material_span": span,
            "vacuum_estimate": vacuum,
        }
        warnings.append(
            f"cell shape={status}; area multiplier={transform.area_multiplier}; "
            f"angles={tuple(round(value, 6) for value in final_angles)}"
        )
        return shaped, diagnostics, warnings
