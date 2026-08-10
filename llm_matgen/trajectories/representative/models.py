"""Validated contracts for representative trajectory sampling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class SourceSpec:
    """One input trajectory and its format-specific parsing policy."""

    name: str
    path: Path
    input_format: str | None = None
    type_map: dict[int, int | str] = field(default_factory=dict)
    assume_type_is_atomic_number: bool = False
    cleaned: bool = False

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        if not name:
            raise ValueError("source name must not be empty")
        path = Path(self.path)
        if not str(path):
            raise ValueError("source path must not be empty")
        normalized_map: dict[int, int | str] = {}
        for key, value in dict(self.type_map).items():
            type_id = int(key)
            if type_id <= 0:
                raise ValueError("LAMMPS type IDs must be positive")
            normalized_map[type_id] = value
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "type_map", normalized_map)


@dataclass(frozen=True)
class SourceInventory:
    source: SourceSpec
    frame_count: int
    atomic_numbers: tuple[int, ...]
    natom_values: tuple[int, ...]
    sha256: str

    def __post_init__(self) -> None:
        if self.frame_count < 0:
            raise ValueError("frame_count must be non-negative")
        if any(int(number) < 1 or int(number) > 118 for number in self.atomic_numbers):
            raise ValueError("atomic numbers must be between 1 and 118")
        if any(int(count) <= 0 for count in self.natom_values):
            raise ValueError("natom values must be positive")


@dataclass(frozen=True)
class SelectionRecord:
    source_name: str
    source_index: int
    source_timestep: int | float | None
    sampling_rank: int
    fps_distance: float | None
    source_quota: int


@dataclass(frozen=True)
class RepresentativeSamplingRequest:
    sources: tuple[SourceSpec, ...]
    method: Literal["rdf-fps", "soap-fps"]
    count: int
    allocation: Literal["proportional", "global"] = "proportional"
    min_distance: float = 0.0
    output_root: Path = Path("output")
    cache_dir: Path | None = None
    existing_dataset: Path | None = None
    sampling_config: Path | None = None
    resume: bool = False
    recompute: bool = False

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        if not sources:
            raise ValueError("at least one source is required")
        names = [source.name for source in sources]
        if len(names) != len(set(names)):
            raise ValueError("duplicate source names are not allowed")
        method = str(self.method).strip().lower()
        if method not in {"rdf-fps", "soap-fps"}:
            raise ValueError("method must be rdf-fps or soap-fps")
        if isinstance(self.count, bool) or int(self.count) != self.count or int(self.count) <= 0:
            raise ValueError("count must be a positive integer")
        allocation = str(self.allocation).strip().lower()
        if allocation not in {"proportional", "global"}:
            raise ValueError("allocation must be proportional or global")
        if float(self.min_distance) < 0:
            raise ValueError("min_distance must be non-negative")
        if self.resume and self.recompute:
            raise ValueError("resume and recompute are mutually exclusive")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "count", int(self.count))
        object.__setattr__(self, "allocation", allocation)
        object.__setattr__(self, "min_distance", float(self.min_distance))
        object.__setattr__(self, "output_root", Path(self.output_root))
        if self.cache_dir is not None:
            object.__setattr__(self, "cache_dir", Path(self.cache_dir))
        if self.existing_dataset is not None:
            object.__setattr__(self, "existing_dataset", Path(self.existing_dataset))
        if self.sampling_config is not None:
            object.__setattr__(self, "sampling_config", Path(self.sampling_config))


@dataclass(frozen=True)
class RepresentativeSamplingResult:
    run_dir: Path
    selected_path: Path
    selection_path: Path
    summary_path: Path
    manifest_path: Path
    selected_count: int
