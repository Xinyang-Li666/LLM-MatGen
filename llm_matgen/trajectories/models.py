"""Contracts for multi-frame structure workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Protocol

@dataclass(frozen=True)
class TrajectoryFrame:
    structure: object
    source_index: int
    source_id: str
    metadata: dict[str, object] = field(default_factory=dict)


class FrameReader(Protocol):
    def iter_frames(self) -> Iterator[TrajectoryFrame]: ...
    def count_frames(self) -> int: ...


class SamplingMethod(str, Enum):
    ALL = "all"
    UNIFORM = "uniform"
    RANDOM = "random"
