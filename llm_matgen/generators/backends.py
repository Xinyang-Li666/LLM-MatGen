"""Optional generator backend contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pymatgen.core import Structure
from pymatgen.core.interface import GrainBoundaryGenerator as PymatgenGBBuilder


class OptionalDependencyError(ImportError):
    """Raised when an explicitly requested optional backend is unavailable."""


class BackendGenerationError(RuntimeError):
    """Raised when a local crystallographic backend cannot construct a result."""


@dataclass
class BackendStructure:
    structure: Structure
    actual_parameters: dict[str, object]


class GrainBoundaryBackend(Protocol):
    def generate(
        self,
        structure: Structure,
        *,
        rotation_axis: tuple[int, int, int],
        rotation_angle: float,
        plane: tuple[int, int, int] | None,
        expand_times: int,
        vacuum_thickness: float,
        ab_shift: tuple[float, float],
    ) -> BackendStructure: ...


class PymatgenGrainBoundaryBackend:
    def generate(
        self,
        structure: Structure,
        *,
        rotation_axis: tuple[int, int, int],
        rotation_angle: float,
        plane: tuple[int, int, int] | None,
        expand_times: int,
        vacuum_thickness: float,
        ab_shift: tuple[float, float],
    ) -> BackendStructure:
        try:
            boundary = PymatgenGBBuilder(structure.copy()).gb_from_parameters(
                rotation_axis=rotation_axis,
                rotation_angle=rotation_angle,
                plane=plane,
                expand_times=expand_times,
                vacuum_thickness=vacuum_thickness,
                ab_shift=ab_shift,
            )
        except Exception as exc:
            raise BackendGenerationError(f"grain-boundary backend failed: {exc}") from exc
        if boundary is None or len(boundary) == 0:
            raise BackendGenerationError("grain-boundary backend returned no structure")
        return BackendStructure(
            structure=boundary,
            actual_parameters={
                "rotation_axis": list(rotation_axis),
                "rotation_angle": rotation_angle,
                "plane": list(plane) if plane else None,
                "expand_times": expand_times,
                "vacuum_thickness": vacuum_thickness,
                "ab_shift": list(ab_shift),
            },
        )


class SQSBackend:
    def generate(self, structure, target_element, substituents, seed):
        try:
            import sqsgenerator  # noqa: F401
        except ImportError as exc:
            raise OptionalDependencyError(
                "SQS generation requires the optional dependency sqsgenerator; "
                "install with pip install llm-matgen[sqs]"
            ) from exc
        raise NotImplementedError("sqsgenerator adapter is not available in this release")
