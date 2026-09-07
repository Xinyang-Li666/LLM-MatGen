"""Shared source snapshot contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CaseSourceError(ValueError):
    """Raised when a case source cannot produce a safe, stable snapshot."""


@dataclass(frozen=True)
class RemoteFileSnapshot:
    relative_path: str
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    source: str
    files: tuple[RemoteFileSnapshot, ...]


class CaseSource(Protocol):
    def discover(self) -> tuple[JobSnapshot, ...]: ...

    def snapshot(self, job_id: str) -> JobSnapshot: ...
