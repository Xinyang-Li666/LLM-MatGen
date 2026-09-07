"""Element-pair overlap detection using ASE's periodic neighbour list."""

from __future__ import annotations

import numpy as np
from ase import Atoms
from ase.data import covalent_radii
from ase.neighborlist import neighbor_list

from .models import DetectionResult, FilterFrame


def _pair_threshold(
    z1: int,
    z2: int,
    scale: float,
    floor: float,
    overrides: dict[tuple[int, int], float],
) -> float:
    pair = (min(z1, z2), max(z1, z2))
    if pair in overrides:
        return float(overrides[pair])
    radius_1, radius_2 = float(covalent_radii[z1]), float(covalent_radii[z2])
    if radius_1 <= 0 or radius_2 <= 0:
        raise ValueError(f"no covalent radius is available for pair {z1}-{z2}")
    return max(floor, scale * (radius_1 + radius_2))


def check_overlap(
    frame: FilterFrame,
    *,
    overlap_scale: float = 0.55,
    absolute_floor: float = 0.55,
    overlap_ratio: float = 0.01,
    pair_min_distance: dict[tuple[int, int], float] | None = None,
) -> DetectionResult:
    if overlap_scale <= 0 or absolute_floor < 0 or not 0 <= overlap_ratio <= 1:
        raise ValueError("invalid overlap parameters")
    overrides = pair_min_distance or {}
    max_cutoff = max(
        _pair_threshold(int(z1), int(z2), overlap_scale, absolute_floor, overrides)
        for z1 in frame.atomic_numbers
        for z2 in frame.atomic_numbers
    )
    atoms = Atoms(
        numbers=frame.atomic_numbers,
        positions=frame.positions,
        cell=frame.cell,
        pbc=frame.pbc,
    )
    indices_i, indices_j, distances = neighbor_list("ijd", atoms, max_cutoff)
    overlap_atoms: set[int] = set()
    overlap_pairs = 0
    minimum = float("inf")
    for i, j, distance in zip(indices_i, indices_j, distances):
        distance = float(distance)
        minimum = min(minimum, distance)
        threshold = _pair_threshold(
            int(frame.atomic_numbers[i]), int(frame.atomic_numbers[j]),
            overlap_scale, absolute_floor, overrides,
        )
        if distance < threshold:
            overlap_pairs += 1
            overlap_atoms.update((int(i), int(j)))
    fraction = len(overlap_atoms) / frame.natoms
    severe = any(
        float(d) < 0.70 * _pair_threshold(
            int(frame.atomic_numbers[i]), int(frame.atomic_numbers[j]),
            overlap_scale, absolute_floor, overrides,
        )
        for i, j, d in zip(indices_i, indices_j, distances)
    )
    reasons = []
    if severe or fraction >= overlap_ratio and overlap_pairs > 0:
        reasons.append("atomic_overlap")
    minimum_metric = None if not np.isfinite(minimum) else minimum
    return DetectionResult(
        "overlap", "fail" if reasons else "pass", "error" if reasons else "info",
        {"overlap_pairs": overlap_pairs, "overlap_atoms": len(overlap_atoms),
         "overlap_atom_fraction": fraction, "minimum_distance": minimum_metric},
        tuple(reasons),
    )
