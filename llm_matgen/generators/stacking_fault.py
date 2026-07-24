"""Geometric stacking-fault construction without stability claims."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from pydantic import Field, NonNegativeFloat, PositiveInt, field_validator
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.extended import MillerIndex, normalize_miller
from llm_matgen.generators.models import (
    BaseGenerationParams,
    GeneratedStructure,
    GenerationResult,
    Provenance,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class StackingFaultParams(BaseGenerationParams):
    plane: MillerIndex
    slip_vector: tuple[float, float, float]
    fault_position: float = Field(default=0.5, ge=0, lt=1)
    repetitions: tuple[PositiveInt, PositiveInt, PositiveInt] = (1, 1, 1)
    vacuum_thickness: NonNegativeFloat = 0

    @field_validator("plane")
    @classmethod
    def validate_plane(cls, value: MillerIndex) -> MillerIndex:
        return normalize_miller(value)

    @field_validator("slip_vector")
    @classmethod
    def validate_slip(cls, value: tuple[float, float, float]):
        if not np.isfinite(value).all() or np.allclose(value, 0):
            raise ValueError("slip vector must be finite and non-zero")
        return tuple(float(item) for item in value)


def _add_c_vacuum(structure: Structure, vacuum: float) -> Structure:
    if vacuum == 0:
        return structure
    matrix = np.asarray(structure.lattice.matrix, dtype=float).copy()
    c_length = np.linalg.norm(matrix[2])
    c_unit = matrix[2] / c_length
    matrix[2] = c_unit * (c_length + vacuum)
    cart_coords = np.asarray(structure.cart_coords) + c_unit * (vacuum / 2)
    return Structure(
        Lattice(matrix),
        structure.species,
        cart_coords,
        coords_are_cartesian=True,
        to_unit_cell=True,
    )


class StackingFaultGenerator:
    defect_name = "stacking_fault"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: StackingFaultParams) -> GenerationResult:
        source = structure.copy()
        parent_id = structure_sha256(source)
        parent_sites = assign_site_ids(source, parent_id)
        child = source.copy()
        child.make_supercell(np.diag(params.repetitions))
        if len(child) > params.max_atoms_per_structure:
            raise ValueError(
                f"stacking-fault atom limit exceeded: {len(child)} > {params.max_atoms_per_structure}"
            )
        plane = np.asarray(params.plane, dtype=float)
        phases = np.mod(np.asarray(child.frac_coords) @ plane, 1.0)
        moved = np.flatnonzero(phases >= params.fault_position).tolist()
        if not moved:
            raise ValueError("fault position selects no atoms for displacement")
        child.translate_sites(moved, params.slip_vector, frac_coords=True, to_unit_cell=True)
        child = _add_c_vacuum(child, float(params.vacuum_thickness))
        child_id = structure_sha256(child)
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            generated=[
                GeneratedStructure(
                    child,
                    StructureRecord(
                        structure_id=child_id,
                        parent_structure_id=parent_id,
                        formula=child.composition.reduced_formula,
                        n_atoms=len(child),
                        actual_parameters={
                            "plane": list(params.plane),
                            "slip_vector": list(params.slip_vector),
                            "fault_position": params.fault_position,
                            "repetitions": list(params.repetitions),
                            "vacuum_thickness": float(params.vacuum_thickness),
                            "moved_site_count": len(moved),
                        },
                        site_mapping={site_id: None for site_id in parent_sites},
                    ),
                )
            ],
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
