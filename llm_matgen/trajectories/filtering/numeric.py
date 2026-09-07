"""Hard validation checks for trajectory frames."""

from __future__ import annotations

import numpy as np

from .models import DetectionResult, FilterFrame


def check_frame(
    frame: FilterFrame,
    reference_numbers: np.ndarray | None = None,
    allow_variable_composition: bool = False,
) -> DetectionResult:
    reasons: list[str] = []
    metrics: dict[str, float | int | str] = {"natoms": frame.natoms}
    for name, array in (("positions", frame.positions), ("forces", frame.forces), ("cell", frame.cell)):
        if array is not None and not np.all(np.isfinite(array)):
            reasons.append("non_finite_" + name)
    if np.any(frame.pbc) and frame.cell is None:
        reasons.append("periodic_cell_missing")
    if frame.cell is not None and np.any(frame.pbc):
        volume = abs(float(np.linalg.det(frame.cell)))
        metrics["cell_volume"] = volume
        if not np.isfinite(volume) or volume <= 1e-10:
            reasons.append("invalid_cell")
    if reference_numbers is not None and not allow_variable_composition:
        if sorted(map(int, frame.atomic_numbers)) != sorted(map(int, reference_numbers)):
            reasons.append("composition_changed")
    return DetectionResult(
        detector="numeric", status="fail" if reasons else "pass",
        severity="error" if reasons else "info", metrics=metrics, reasons=tuple(reasons),
    )
