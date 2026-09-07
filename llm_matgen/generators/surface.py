"""Surface slab generation using pymatgen's local crystallographic tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import Field, PositiveFloat, PositiveInt, field_validator
from pymatgen.core import Structure
from pymatgen.core.surface import SlabGenerator
from pymatgen.analysis.structure_matcher import StructureMatcher

from llm_matgen.generators.extended import MillerIndex, normalize_miller
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
    cell_shape: Literal["native", "near-orthogonal"] = "native"
    orthogonal_max_area: PositiveInt = 8
    orthogonal_tolerance: PositiveFloat = 0.1

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
                if len(slab) > params.max_atoms_per_structure:
                    raise ValueError(
                        f"surface atom limit exceeded: {len(slab)} > {params.max_atoms_per_structure}"
                    )
                child_id = structure_sha256(slab)
                if any(matcher.fit(slab, item.structure) for item in generated):
                    warnings.append(
                        f"duplicate surface skipped for Miller index {miller}, termination {termination}"
                    )
                    continue
                frac_z = np.asarray(slab.frac_coords)[:, 2]
                material_span = float((frac_z.max() - frac_z.min()) * slab.lattice.c)
                generated.append(
                    GeneratedStructure(
                        structure=slab,
                        record=StructureRecord(
                            structure_id=child_id,
                            parent_structure_id=parent_id,
                            formula=slab.composition.reduced_formula,
                            n_atoms=len(slab),
                            actual_parameters={
                                "miller_index": list(miller),
                                "termination": termination,
                                "cell_height": float(slab.lattice.c),
                                "material_span": material_span,
                                "vacuum_estimate": max(0.0, float(slab.lattice.c) - material_span),
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
