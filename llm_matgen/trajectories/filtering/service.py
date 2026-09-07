"""Path-oriented service facade for the streaming filter engine."""

from __future__ import annotations

import json
from pathlib import Path

from .config import FilterConfig
from .engine import FilterEngine, FilterRunResult
from .profiles import ThresholdProfile
from .readers import FilterTrajectoryReader


class TrajectoryFilterService:
    def filter(
        self,
        input_path: Path,
        output_root: Path,
        config: FilterConfig,
        *,
        reference_path: Path | None = None,
        threshold_profile: Path | None = None,
        input_format: str | None = None,
        lammps_type_map: dict[int, int | str] | None = None,
        assume_type_is_z: bool = False,
        output_format: str = "extxyz",
    ) -> FilterRunResult:
        input_path = Path(input_path).resolve()
        mapping = lammps_type_map or {}
        reader_factory = lambda: FilterTrajectoryReader(
            input_path, input_format, mapping, assume_type_is_z=assume_type_is_z,
        ).iter_frames()
        reference_factory = None
        if reference_path is not None:
            reference = Path(reference_path).resolve()
            reference_factory = lambda: FilterTrajectoryReader(
                reference, None, mapping, assume_type_is_z=assume_type_is_z,
            ).iter_frames()
        profile = None
        if threshold_profile is not None:
            profile = ThresholdProfile.from_dict(
                json.loads(Path(threshold_profile).read_text(encoding="utf-8"))
            )
        return FilterEngine(config, profile).run(
            reader_factory, Path(output_root), reference_factory=reference_factory,
            output_format=output_format,
        )
