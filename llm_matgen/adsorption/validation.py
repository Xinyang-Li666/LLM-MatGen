"""Shared fixed-layer policy used by generation and candidate validation."""

from __future__ import annotations

from dataclasses import dataclass
import warnings as _warnings

import numpy as np
from pymatgen.core import Structure


def _surface_normal(structure: Structure) -> np.ndarray:
    normal = np.cross(structure.lattice.matrix[0], structure.lattice.matrix[1]).astype(float)
    normal /= np.linalg.norm(normal)
    if np.dot(normal, structure.lattice.matrix[2]) < 0:
        normal = -normal
    return normal


def _layer_ids(structure: Structure, slab_atom_count: int, tolerance: float = 0.15):
    if not 0 <= slab_atom_count <= len(structure):
        raise ValueError("slab_atom_count must be between zero and the number of atoms")
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be finite and positive")
    normal = _surface_normal(structure)
    projections = np.asarray(structure.cart_coords[:slab_atom_count]) @ normal
    order = np.argsort(projections, kind="stable")
    layers: list[list[int]] = []
    for index in order:
        if not layers or abs(float(projections[index]) - float(np.mean(projections[layers[-1]]))) > tolerance:
            layers.append([int(index)])
        else:
            layers[-1].append(int(index))
    return layers, tuple(float(value) for value in projections)


@dataclass(frozen=True)
class FixedLayerResult:
    layer_indices: tuple[tuple[int, ...], ...]
    projections: tuple[float, ...]
    flags: tuple[tuple[bool, bool, bool], ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    atom_indices: tuple[int, ...] = ()
    threshold: float | None = None
    measured: float | None = None


@dataclass(frozen=True)
class AdsorptionValidationReport:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    measurements: dict[str, float]


class AdsorptionCandidateValidator:
    def __init__(self, slab: Structure, molecule, *, min_distance: float = 0.8, min_vacuum: float = 5.0, max_coverage: float | None = None):
        self.slab = slab
        self.molecule = molecule
        self.min_distance = float(min_distance)
        self.min_vacuum = float(min_vacuum)
        self.max_coverage = max_coverage

    def validate(self, candidate: Structure, *, expected_flags=None) -> AdsorptionValidationReport:
        issues: list[ValidationIssue] = []
        expected_atoms = len(self.slab) + len(self.molecule)
        if len(candidate) != expected_atoms:
            issues.append(ValidationIssue("atom_count_mismatch", f"expected {expected_atoms}, got {len(candidate)}"))
        expected_species = [str(site.specie) for site in self.slab] + [str(site.specie) for site in self.molecule]
        if [str(site.specie) for site in candidate[:expected_atoms]] != expected_species[: len(candidate)]:
            issues.append(ValidationIssue("atom_order_mismatch", "slab atoms must precede adsorbate atoms"))
        coords = np.asarray(candidate.cart_coords, dtype=float)
        normal = _surface_normal(candidate)
        slab_proj = np.asarray(self.slab.cart_coords) @ normal
        cell_extent = abs(float(np.dot(candidate.lattice.matrix[2], normal)))
        slab_thickness = float(np.max(slab_proj) - np.min(slab_proj)) if len(slab_proj) else 0.0
        vacuum = max(0.0, cell_extent - slab_thickness)
        measurements = {"vacuum": vacuum, "coverage": float(len(self.molecule) / max(candidate.volume, 1e-12))}
        if vacuum < self.min_vacuum:
            issues.append(ValidationIssue("vacuum_too_small", "cell extent along surface normal is too small", threshold=self.min_vacuum, measured=vacuum))
        # Check all slab/adsorbate pairs, including the nearest 2-D periodic images.
        slab_n = min(len(self.slab), len(candidate))
        min_pair = float("inf")
        min_pair_indices: tuple[int, ...] = ()
        for i in range(slab_n):
            for j in range(slab_n, len(candidate)):
                for u in (-1, 0, 1):
                    for v in (-1, 0, 1):
                        delta = coords[j] + u * candidate.lattice.matrix[0] + v * candidate.lattice.matrix[1] - coords[i]
                        distance = float(np.linalg.norm(delta))
                        if distance < min_pair:
                            min_pair, min_pair_indices = distance, (i, j)
        measurements["min_slab_adsorbate_distance"] = min_pair
        if min_pair < self.min_distance:
            issues.append(ValidationIssue("slab_collision", "adsorbate is too close to slab or a 2-D image", min_pair_indices, self.min_distance, min_pair))
        min_internal = float("inf")
        for i in range(slab_n, len(candidate)):
            for j in range(i + 1, len(candidate)):
                min_internal = min(min_internal, float(np.linalg.norm(coords[i] - coords[j])))
        if min_internal < self.min_distance:
            issues.append(ValidationIssue("adsorbate_internal_collision", "adsorbate atoms are too close", threshold=self.min_distance, measured=min_internal))
        if expected_flags is not None:
            actual = candidate.site_properties.get("selective_dynamics")
            if actual is None or tuple(tuple(bool(v) for v in row) for row in actual) != tuple(expected_flags):
                issues.append(ValidationIssue("fixed_flags_mismatch", "candidate selective dynamics differ from expected flags"))
        if self.max_coverage is not None and measurements["coverage"] > self.max_coverage:
            issues.append(ValidationIssue("coverage_exceeded", "adsorbate coverage exceeds configured limit", threshold=self.max_coverage, measured=measurements["coverage"]))
        return AdsorptionValidationReport(not issues, tuple(issues), measurements)


def apply_fixed_bottom_layers(
    structure: Structure,
    *,
    slab_atom_count: int,
    n_layers: int,
    tolerance: float = 0.15,
    side: str = "bottom",
) -> FixedLayerResult:
    if side not in {"bottom", "top", "both"}:
        raise ValueError("side must be bottom, top or both")
    layers, projections = _layer_ids(structure, slab_atom_count, tolerance)
    if n_layers < 0 or n_layers > len(layers):
        raise ValueError(f"n_layers must be between 0 and {len(layers)}")
    existing = structure.site_properties.get("selective_dynamics", [(True, True, True)] * len(structure))
    flags = [tuple(bool(value) for value in row) for row in existing]
    warnings: list[str] = []
    if side in {"top", "both"}:
        warnings.append(f"fixed-layer policy applies bottom layers; requested side={side}")
    selected = {atom for layer in layers[:n_layers] for atom in layer}
    for atom in selected:
        flags[atom] = (False, False, False)
    return FixedLayerResult(tuple(tuple(layer) for layer in layers), projections, tuple(flags), tuple(warnings))
