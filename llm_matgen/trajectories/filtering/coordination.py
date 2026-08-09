"""Reference-based coordination checks."""

from __future__ import annotations

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from .models import DetectionResult, FilterFrame


def check_coordination(
    frame: FilterFrame,
    *,
    bounds: dict[str, tuple[float, float]] | None = None,
    groups: dict[str, list[int]] | None = None,
    cutoff: float = 3.5,
) -> DetectionResult:
    if bounds is None:
        return DetectionResult("coordination", "not_evaluated", "warning", {}, ("profile_missing",))
    if cutoff <= 0:
        raise ValueError("coordination cutoff must be positive")
    atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
    i, j = neighbor_list("ij", atoms, cutoff)
    coordination = np.bincount(i, minlength=frame.natoms)
    groups = groups or {"all": [int(z) for z in np.unique(frame.atomic_numbers)]}
    metrics: dict[str, float | int | str] = {}
    reasons: list[str] = []
    for name, atomic_numbers in groups.items():
        mask = np.isin(frame.atomic_numbers, atomic_numbers)
        if not mask.any() or name not in bounds:
            continue
        average = float(coordination[mask].mean())
        metrics[f"avg_coord_{name}"] = average
        low, high = bounds[name]
        if average < low or average > high:
            reasons.append(f"coordination_{name}")
    if not metrics:
        return DetectionResult("coordination", "not_evaluated", "warning", {}, ("group_data_missing",))
    return DetectionResult(
        "coordination", "fail" if reasons else "pass", "error" if reasons else "info",
        metrics, tuple(reasons),
    )

