"""Force magnitude screening."""

from __future__ import annotations

import numpy as np

from .models import DetectionResult, FilterFrame


def check_force(frame: FilterFrame, threshold: float | None = None) -> DetectionResult:
    if frame.forces is None:
        return DetectionResult("force", "not_evaluated", "warning", {}, ("forces_missing",))
    if threshold is not None and threshold < 0:
        raise ValueError("force threshold must be non-negative")
    magnitudes = np.linalg.norm(frame.forces, axis=1)
    maximum = float(np.max(magnitudes))
    metrics = {"max_force": maximum, "high_force_atoms": int(np.count_nonzero(magnitudes > (threshold or np.inf)))}
    if threshold is None:
        return DetectionResult("force", "not_evaluated", "warning", metrics, ("force_threshold_missing",))
    failed = maximum > threshold
    return DetectionResult(
        "force", "fail" if failed else "pass", "error" if failed else "info", metrics,
        ("force_exceeded",) if failed else (),
    )

