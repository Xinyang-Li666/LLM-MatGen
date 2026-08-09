"""Validated data contracts used by the trajectory filter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


@dataclass(frozen=True)
class FilterFrame:
    atomic_numbers: np.ndarray
    positions: np.ndarray
    cell: np.ndarray | None
    pbc: np.ndarray
    forces: np.ndarray | None = None
    source_index: int = 0
    timestep: int | float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        numbers = np.asarray(self.atomic_numbers, dtype=int)
        positions = np.asarray(self.positions, dtype=float)
        pbc = np.asarray(self.pbc, dtype=bool)
        cell = None if self.cell is None else np.asarray(self.cell, dtype=float)
        forces = None if self.forces is None else np.asarray(self.forces, dtype=float)

        if numbers.ndim != 1 or numbers.size == 0:
            raise ValueError("atomic_numbers must be a non-empty one-dimensional array")
        if np.any((numbers < 1) | (numbers > 118)):
            raise ValueError("atomic_numbers must be between 1 and 118")
        if positions.shape != (numbers.size, 3):
            raise ValueError("positions must have shape (natoms, 3)")
        if forces is not None and forces.shape != (numbers.size, 3):
            raise ValueError("forces must have shape (natoms, 3)")
        if pbc.shape != (3,):
            raise ValueError("pbc must have shape (3,)")
        if cell is not None and cell.shape != (3, 3):
            raise ValueError("cell must have shape (3, 3)")
        if np.any(pbc) and cell is None:
            raise ValueError("periodic frames require a cell")
        object.__setattr__(self, "atomic_numbers", numbers)
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "pbc", pbc)
        object.__setattr__(self, "cell", cell)
        object.__setattr__(self, "forces", forces)

    @property
    def natoms(self) -> int:
        return int(self.atomic_numbers.size)


@dataclass(frozen=True)
class DetectionResult:
    detector: str
    status: Literal["pass", "fail", "not_evaluated"]
    severity: Literal["info", "warning", "error"]
    metrics: dict[str, float | int | str | None] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrameReview:
    source_index: int
    timestep: int | float | None
    anomalous: bool
    results: tuple[DetectionResult, ...]
