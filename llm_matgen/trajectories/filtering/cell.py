"""Optional relative cell-evolution checks."""

from __future__ import annotations

import numpy as np

from .models import DetectionResult, FilterFrame


def check_cell(
    frame: FilterFrame,
    reference_volume: float | None = None,
    max_volume_change: float | None = None,
) -> DetectionResult:
    if frame.cell is None or not np.any(frame.pbc):
        return DetectionResult("cell", "pass", "info", {"volume": 0.0})
    volume = abs(float(np.linalg.det(frame.cell)))
    metrics: dict[str, float | int | str] = {"volume": volume}
    reasons: list[str] = []
    if volume <= 1e-10:
        reasons.append("invalid_cell")
    if reference_volume is not None and max_volume_change is not None:
        if reference_volume <= 0 or max_volume_change < 0:
            raise ValueError("reference_volume must be positive and max_volume_change non-negative")
        relative = abs(volume / reference_volume - 1.0)
        metrics["relative_volume_change"] = relative
        if relative > max_volume_change:
            reasons.append("cell_volume_change")
    return DetectionResult(
        "cell", "fail" if reasons else "pass", "error" if reasons else "info",
        metrics, tuple(reasons),
    )

