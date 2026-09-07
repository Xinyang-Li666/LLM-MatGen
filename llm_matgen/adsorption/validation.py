"""Shared fixed-layer policy used by generation and candidate validation."""

from __future__ import annotations

from dataclasses import dataclass
import warnings as _warnings

import numpy as np
from pymatgen.core import Structure
from ase.data import atomic_numbers, covalent_radii


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


def _covalent_radius(symbol: str) -> float:
    """Return a conservative covalent radius in angstroms."""
    try:
        radius = float(covalent_radii[atomic_numbers[symbol]])
    except (KeyError, TypeError, ValueError, IndexError):
        radius = float("nan")
    return radius if np.isfinite(radius) and radius > 0 else 1.0


def _periodic_minimum(delta: np.ndarray, lattice: np.ndarray, *, span: int = 4) -> float:
    """Minimum norm after translations in the two periodic surface vectors.

    A small integer neighborhood is sufficient after reducing the two
    in-plane vectors; the range is deliberately wider than the usual 3x3
    image check so skew cells do not silently pass a collision.
    """
    best = float("inf")
    for u in range(-span, span + 1):
        for v in range(-span, span + 1):
            best = min(best, float(np.linalg.norm(delta + u * lattice[0] + v * lattice[1])))
    return best


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
    def __init__(
        self,
        slab: Structure,
        molecule,
        *,
        min_distance: float = 0.8,
        min_vacuum: float = 5.0,
        max_coverage: float | None = None,
        anchor_index: int = 0,
        anchor_contact_window: tuple[float, float] | None = None,
        min_vacuum_each_side: float = 0.0,
        periodic_image_span: int = 4,
    ):
        self.slab = slab
        self.molecule = molecule
        self.min_distance = float(min_distance)
        self.min_vacuum = float(min_vacuum)
        self.max_coverage = max_coverage
        self.anchor_index = int(anchor_index)
        self.anchor_contact_window = anchor_contact_window
        self.min_vacuum_each_side = float(min_vacuum_each_side)
        self.periodic_image_span = int(periodic_image_span)
        if self.anchor_index < 0 or self.anchor_index >= len(molecule):
            raise ValueError("anchor_index is outside the adsorbate")
        if self.min_distance <= 0 or not np.isfinite(self.min_distance):
            raise ValueError("min_distance must be finite and positive")
        if self.min_vacuum_each_side < 0 or not np.isfinite(self.min_vacuum_each_side):
            raise ValueError("min_vacuum_each_side must be finite and non-negative")
        if self.periodic_image_span < 1:
            raise ValueError("periodic_image_span must be positive")

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
        candidate_proj = coords @ normal
        slab_min, slab_max = float(np.min(slab_proj)), float(np.max(slab_proj))
        # Report both sides relative to the slab.  The absolute origin is not
        # assumed; this remains useful for centered and non-centered slabs.
        lower_gap = max(0.0, slab_min - float(np.min(candidate_proj)))
        upper_gap = max(0.0, float(np.max(candidate_proj)) - slab_max)
        measurements = {
            "vacuum": vacuum,
            "vacuum_lower": lower_gap,
            "vacuum_upper": upper_gap,
            "coverage": float(len(self.molecule) / max(candidate.volume, 1e-12)),
        }
        if vacuum < self.min_vacuum:
            issues.append(ValidationIssue("vacuum_too_small", "cell extent along surface normal is too small", threshold=self.min_vacuum, measured=vacuum))
        if self.min_vacuum_each_side and min(lower_gap, upper_gap) < self.min_vacuum_each_side:
            issues.append(ValidationIssue("vacuum_side_too_small", "one side of the slab has insufficient vacuum", threshold=self.min_vacuum_each_side, measured=min(lower_gap, upper_gap)))
        # Check all slab/adsorbate pairs, including the nearest 2-D periodic images.
        slab_n = min(len(self.slab), len(candidate))
        min_pair = float("inf")
        min_pair_indices: tuple[int, ...] = ()
        for i in range(slab_n):
            for j in range(slab_n, len(candidate)):
                delta = coords[j] - coords[i]
                distance = _periodic_minimum(delta, candidate.lattice.matrix, span=self.periodic_image_span)
                if distance < min_pair:
                    min_pair, min_pair_indices = distance, (i, j)
        measurements["min_slab_adsorbate_distance"] = min_pair
        if min_pair < self.min_distance:
            issues.append(ValidationIssue("slab_collision", "adsorbate is too close to slab or a 2-D image", min_pair_indices, self.min_distance, min_pair))
        min_internal = float("inf")
        min_internal_pair: tuple[int, ...] = ()
        for i in range(slab_n, len(candidate)):
            for j in range(i + 1, len(candidate)):
                distance = _periodic_minimum(coords[i] - coords[j], candidate.lattice.matrix, span=self.periodic_image_span)
                if distance < min_internal:
                    min_internal, min_internal_pair = distance, (i, j)
        if min_internal < self.min_distance:
            issues.append(ValidationIssue("adsorbate_internal_collision", "adsorbate atoms are too close", min_internal_pair, self.min_distance, min_internal))
        # Use element-specific radii for both bonded and non-bonded checks.
        for i in range(slab_n, len(candidate)):
            for j in range(i + 1, len(candidate)):
                required = 0.55 * (_covalent_radius(str(candidate[i].specie)) + _covalent_radius(str(candidate[j].specie)))
                distance = _periodic_minimum(coords[i] - coords[j], candidate.lattice.matrix, span=self.periodic_image_span)
                if distance < required and distance >= self.min_distance:
                    issues.append(ValidationIssue("covalent_overlap", "adsorbate atoms overlap based on covalent radii", (i, j), required, distance))
        if self.anchor_contact_window is not None:
            lower, upper = (float(value) for value in self.anchor_contact_window)
            anchor = slab_n + self.anchor_index
            anchor_distance = _periodic_minimum(coords[anchor] - coords[:slab_n][0], candidate.lattice.matrix, span=self.periodic_image_span) if slab_n else float("inf")
            # The nearest slab atom is the physically relevant contact.
            if slab_n:
                anchor_distance = min(_periodic_minimum(coords[anchor] - coords[i], candidate.lattice.matrix, span=self.periodic_image_span) for i in range(slab_n))
            measurements["anchor_contact_distance"] = anchor_distance
            if not lower <= anchor_distance <= upper:
                issues.append(ValidationIssue("anchor_contact_out_of_window", "anchor-to-slab contact is outside the configured window", (anchor,), lower, anchor_distance))
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
    if side == "bottom":
        selected = {atom for layer in layers[:n_layers] for atom in layer}
    elif side == "top":
        selected = {atom for layer in layers[-n_layers:] for atom in layer} if n_layers else set()
    else:
        selected = {atom for layer in layers[:n_layers] for atom in layer}
        warnings.append("fixed-layer policy applies bottom layers; requested side=both")
    for atom in selected:
        flags[atom] = (False, False, False)
    # Adsorbate atoms must remain movable even when an input POSCAR already
    # carries restrictive selective-dynamics flags.
    for atom in range(slab_atom_count, len(structure)):
        flags[atom] = (True, True, True)
    return FixedLayerResult(tuple(tuple(layer) for layer in layers), projections, tuple(flags), tuple(warnings))
