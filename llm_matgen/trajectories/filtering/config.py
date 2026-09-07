"""Configuration for the general trajectory filter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FilterConfig:
    checks: tuple[str, ...] = ("overlap",)
    overlap_scale: float = 0.55
    overlap_floor: float = 0.55
    overlap_ratio: float = 0.01
    pair_min_distance: dict[tuple[int, int], float] = field(default_factory=dict)
    force_max: float | None = None
    force_iqr: float = 3.0
    force_mad: float = 8.0
    coord_cutoff: float = 3.5
    coord_groups: dict[str, list[int]] | None = None
    coord_iqr: float = 3.0
    sample_count: int = 300
    sample_method: str = "uniform"
    seed: int | None = None
    allow_variable_composition: bool = False
    strict: bool = False

    def __post_init__(self) -> None:
        allowed = {"overlap", "force", "coordination", "cell", "continuity"}
        unknown = set(self.checks) - allowed
        if unknown:
            raise ValueError(f"unknown trajectory checks: {sorted(unknown)}")
        if not self.checks:
            raise ValueError("at least one trajectory check must be selected")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if self.sample_method not in {"uniform", "random"}:
            raise ValueError("sample_method must be uniform or random")
        if self.force_iqr < 0 or self.force_mad < 0 or self.coord_iqr < 0:
            raise ValueError("statistical multipliers must be non-negative")
