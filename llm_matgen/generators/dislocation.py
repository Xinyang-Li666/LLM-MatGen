"""Isotropic dislocation displacement fields and structure construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import Field, PositiveFloat, field_validator, model_validator
from pymatgen.core import Structure

from llm_matgen.generators.extended import MillerIndex, normalize_miller
from llm_matgen.generators.models import (
    BaseGenerationParams,
    GeneratedStructure,
    GenerationResult,
    Provenance,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


def isotropic_displacement_field(
    points: np.ndarray,
    burgers_vector: tuple[float, float, float],
    character: str,
    poisson_ratio: float,
    core_cutoff: float = 1e-6,
) -> np.ndarray:
    """Return Cartesian displacements for a straight line along the z axis."""
    coordinates = np.asarray(points, dtype=float)
    burgers = np.asarray(burgers_vector, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if not np.isfinite(burgers).all() or np.allclose(burgers, 0):
        raise ValueError("Burgers vector must be finite and non-zero")
    if not -1 < poisson_ratio < 0.5:
        raise ValueError("Poisson ratio must lie between -1 and 0.5")
    if character not in {"edge", "screw", "mixed"}:
        raise ValueError("character must be edge, screw, or mixed")
    if core_cutoff <= 0:
        raise ValueError("core cutoff must be positive")

    x = coordinates[:, 0]
    y = coordinates[:, 1]
    radius_sq = np.maximum(x * x + y * y, core_cutoff * core_cutoff)
    theta = np.arctan2(y, x)
    displacement = np.zeros_like(coordinates, dtype=float)

    if character in {"edge", "mixed"}:
        edge_magnitude = float(np.linalg.norm(burgers[:2]))
        if character == "edge" and edge_magnitude == 0:
            raise ValueError("edge Burgers vector must have an in-plane component")
        if edge_magnitude:
            ux = edge_magnitude / (2 * np.pi) * (
                theta + x * y / (2 * (1 - poisson_ratio) * radius_sq)
            )
            uy = -edge_magnitude / (2 * np.pi) * (
                (1 - 2 * poisson_ratio)
                / (4 * (1 - poisson_ratio))
                * np.log(radius_sq)
                + (x * x - y * y) / (4 * (1 - poisson_ratio) * radius_sq)
            )
            direction = burgers[:2] / edge_magnitude
            displacement[:, 0] += ux * direction[0] - uy * direction[1]
            displacement[:, 1] += ux * direction[1] + uy * direction[0]

    if character in {"screw", "mixed"}:
        screw_magnitude = float(burgers[2])
        if character == "screw" and np.isclose(screw_magnitude, 0):
            screw_magnitude = float(np.linalg.norm(burgers))
        displacement[:, 2] += screw_magnitude / (2 * np.pi) * theta
    return displacement


class DislocationParams(BaseGenerationParams):
    line_direction: MillerIndex
    burgers_vector: tuple[float, float, float]
    slip_plane: MillerIndex
    character: Literal["edge", "screw", "mixed"]
    core_position: tuple[float, float]
    radius: PositiveFloat
    poisson_ratio: float = Field(gt=-1, lt=0.5)

    @field_validator("line_direction", "slip_plane")
    @classmethod
    def validate_indices(cls, value: MillerIndex) -> MillerIndex:
        return normalize_miller(value)

    @model_validator(mode="after")
    def validate_geometry(self):
        line = np.asarray(self.line_direction, dtype=float)
        plane = np.asarray(self.slip_plane, dtype=float)
        burgers = np.asarray(self.burgers_vector, dtype=float)
        if not np.isfinite(burgers).all() or np.allclose(burgers, 0):
            raise ValueError("Burgers vector must be finite and non-zero")
        if not np.isclose(np.dot(line, plane), 0):
            raise ValueError("line direction must lie in the slip plane")
        parallel = np.linalg.norm(np.cross(burgers, line)) <= 1e-8
        perpendicular = abs(float(np.dot(burgers, line))) <= 1e-8
        if self.character == "screw" and not parallel:
            raise ValueError("screw Burgers vector must be parallel to line direction")
        if self.character == "edge" and not perpendicular:
            raise ValueError("edge Burgers vector must be perpendicular to line direction")
        if self.character == "mixed" and (parallel or perpendicular):
            raise ValueError("mixed Burgers vector needs edge and screw components")
        if not all(0 <= value <= 1 for value in self.core_position):
            raise ValueError("core position must use fractional in-plane coordinates in [0, 1]")
        return self


class DislocationGenerator:
    defect_name = "dislocation"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: DislocationParams) -> GenerationResult:
        source = structure.copy()
        parent_id = structure_sha256(source)
        parent_sites = assign_site_ids(source, parent_id)
        repeats = (
            max(1, int(np.ceil(2 * params.radius / source.lattice.a))),
            max(1, int(np.ceil(2 * params.radius / source.lattice.b))),
            1,
        )
        expanded = source.copy()
        expanded.make_supercell(np.diag(repeats))
        if len(expanded) > params.max_atoms_per_structure:
            raise ValueError(
                f"dislocation atom limit exceeded: {len(expanded)} > {params.max_atoms_per_structure}"
            )

        line_cart = np.asarray(params.line_direction) @ expanded.lattice.matrix
        e3 = line_cart / np.linalg.norm(line_cart)
        plane_normal = np.asarray(params.slip_plane) @ expanded.lattice.reciprocal_lattice.matrix
        plane_normal /= np.linalg.norm(plane_normal)
        e1 = np.cross(plane_normal, e3)
        if np.linalg.norm(e1) <= 1e-10:
            raise ValueError("line direction and slip-plane normal do not define a local frame")
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(e3, e1)
        basis = np.vstack([e1, e2, e3])

        core_cart = (
            params.core_position[0] * expanded.lattice.matrix[0]
            + params.core_position[1] * expanded.lattice.matrix[1]
        )
        relative_cart = np.asarray(expanded.cart_coords) - core_cart
        local_points = relative_cart @ basis.T
        keep = np.linalg.norm(local_points[:, :2], axis=1) <= params.radius
        if not keep.any():
            raise ValueError("dislocation radius leaves an empty structure")
        local_burgers = np.asarray(params.burgers_vector) @ basis.T
        local_displacements = isotropic_displacement_field(
            local_points[keep],
            tuple(float(value) for value in local_burgers),
            params.character,
            params.poisson_ratio,
            core_cutoff=max(1e-6, min(source.lattice.abc) * 1e-4),
        )
        displaced_cart = np.asarray(expanded.cart_coords)[keep] + local_displacements @ basis
        species = [site.specie for site, selected in zip(expanded, keep, strict=True) if selected]
        child = Structure(
            expanded.lattice,
            species,
            displaced_cart,
            coords_are_cartesian=True,
            to_unit_cell=False,
        )
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
                            "line_direction": list(params.line_direction),
                            "burgers_vector_angstrom": list(params.burgers_vector),
                            "slip_plane": list(params.slip_plane),
                            "character": params.character,
                            "core_position": list(params.core_position),
                            "radius_angstrom": float(params.radius),
                            "poisson_ratio": params.poisson_ratio,
                            "supercell_repetitions": list(repeats),
                            "boundary_conditions": ["non-periodic", "non-periodic", "periodic"],
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
