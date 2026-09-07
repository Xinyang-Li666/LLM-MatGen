"""Reference sampling and reusable threshold profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable, Iterable

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from .config import FilterConfig
from .models import FilterFrame


def _coordination(frame: FilterFrame, cutoff: float) -> np.ndarray:
    atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
    i, _ = neighbor_list("ij", atoms, cutoff)
    return np.bincount(i, minlength=frame.natoms)


@dataclass(frozen=True)
class ThresholdProfile:
    schema_version: str = "1"
    sample_indices: tuple[int, ...] = ()
    reference_numbers: tuple[int, ...] = ()
    force_threshold: float | None = None
    coordination_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    coordination_groups: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sample_indices": list(self.sample_indices),
            "reference_numbers": list(self.reference_numbers),
            "force_threshold": self.force_threshold,
            "coordination_bounds": {k: list(v) for k, v in self.coordination_bounds.items()},
            "coordination_groups": {k: list(v) for k, v in self.coordination_groups.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ThresholdProfile":
        if str(data.get("schema_version", "")) != "1":
            raise ValueError("unsupported threshold profile schema")
        bounds = {
            str(k): (float(v[0]), float(v[1]))
            for k, v in dict(data.get("coordination_bounds", {})).items()
        }
        groups = {
            str(k): tuple(int(item) for item in v)
            for k, v in dict(data.get("coordination_groups", {})).items()
        }
        force = data.get("force_threshold")
        return cls(
            sample_indices=tuple(int(i) for i in data.get("sample_indices", [])),
            reference_numbers=tuple(int(i) for i in data.get("reference_numbers", [])),
            force_threshold=None if force is None else float(force),
            coordination_bounds=bounds,
            coordination_groups=groups,
        )

    def write(self, path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def calibrate_profile(reader_factory: Callable[[], Iterable[FilterFrame]], config: FilterConfig) -> ThresholdProfile:
    total = sum(1 for _ in reader_factory())
    if total == 0:
        raise ValueError("reference trajectory is empty")
    count = min(config.sample_count, total)
    if config.sample_method == "uniform":
        selected = np.linspace(0, total - 1, count, dtype=int)
    else:
        rng = np.random.default_rng(config.seed)
        selected = np.sort(rng.choice(total, size=count, replace=False))
    selected_set = set(int(i) for i in selected)
    samples: list[FilterFrame] = [frame for frame in reader_factory() if frame.source_index in selected_set]
    if not samples:
        raise ValueError("reference trajectory produced no sample frames")

    force_values = [float(np.linalg.norm(frame.forces, axis=1).max()) for frame in samples if frame.forces is not None]
    force_threshold = None
    if force_values:
        values = np.asarray(force_values)
        q1, q3 = np.percentile(values, [25, 75])
        iqr_bound = q3 + config.force_iqr * (q3 - q1)
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        force_threshold = max(float(iqr_bound), median + config.force_mad * mad)

    groups = config.coord_groups or {"all": tuple(sorted(set(int(z) for z in samples[0].atomic_numbers)))}
    groups_tuple = {name: tuple(int(z) for z in values) for name, values in groups.items()}
    coord_values: dict[str, list[float]] = {name: [] for name in groups_tuple}
    for frame in samples:
        coord = _coordination(frame, config.coord_cutoff)
        for name, atomic_numbers in groups_tuple.items():
            mask = np.isin(frame.atomic_numbers, atomic_numbers)
            if mask.any():
                coord_values[name].append(float(coord[mask].mean()))
    bounds: dict[str, tuple[float, float]] = {}
    if "coordination" in config.checks:
        for name, values in coord_values.items():
            if values:
                array = np.asarray(values)
                q1, q3 = np.percentile(array, [25, 75])
                bounds[name] = (float(q1 - config.coord_iqr * (q3 - q1)), float(q3 + config.coord_iqr * (q3 - q1)))
    return ThresholdProfile(
        sample_indices=tuple(int(i) for i in selected),
        reference_numbers=tuple(sorted(int(z) for z in samples[0].atomic_numbers)),
        force_threshold=force_threshold,
        coordination_bounds=bounds,
        coordination_groups=groups_tuple,
    )
