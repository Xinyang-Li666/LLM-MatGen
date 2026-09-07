"""Safe, read-only snapshots of local adsorption case directories."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .base import CaseSourceError, JobSnapshot, RemoteFileSnapshot


class LocalDirectoryCaseSource:
    def __init__(self, root: Path | str, *, chunk_size: int = 1024 * 1024):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        root_path = Path(root)
        if "\x00" in str(root_path):
            raise CaseSourceError("source root cannot contain NUL")
        if not root_path.exists() or not root_path.is_dir():
            raise CaseSourceError(f"source root is not a directory: {root}")
        self.root = root_path.resolve()
        self.chunk_size = chunk_size

    def _file_stat(self, path: Path):
        return path.stat()

    def _resolve_job(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or "\x00" in job_id:
            raise CaseSourceError("job path cannot contain NUL")
        if "\\" in job_id:
            raise CaseSourceError("job path must use POSIX separators")
        relative = Path(job_id)
        if relative.is_absolute() or ".." in relative.parts:
            raise CaseSourceError(f"job path escapes source root: {job_id}")
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise CaseSourceError(f"job path escapes source root: {job_id}") from exc
        if not candidate.exists() or not candidate.is_dir():
            raise CaseSourceError(f"job directory does not exist: {job_id}")
        return candidate

    def _iter_job_dirs(self):
        for current, directories, files in os.walk(self.root, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories if not (current_path / name).is_symlink()
            )
            files = [name for name in files if not (current_path / name).is_symlink()]
            if any(name in {"POSCAR", "OUTCAR"} for name in files):
                yield current_path

    def discover(self) -> tuple[JobSnapshot, ...]:
        jobs = []
        for directory in self._iter_job_dirs():
            job_id = directory.relative_to(self.root).as_posix() or "."
            jobs.append(self.snapshot(job_id))
        return tuple(sorted(jobs, key=lambda item: item.job_id))

    def _snapshot_file(self, path: Path, relative_path: str) -> RemoteFileSnapshot:
        before = self._file_stat(path)
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(self.chunk_size):
                    digest.update(chunk)
        except OSError as exc:
            raise CaseSourceError(f"failed to read case file: {path}") from exc
        after = self._file_stat(path)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise CaseSourceError(f"file changed during snapshot: {relative_path}")
        return RemoteFileSnapshot(
            relative_path=relative_path,
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
            sha256=digest.hexdigest(),
        )

    def snapshot(self, job_id: str) -> JobSnapshot:
        directory = self._resolve_job(job_id)
        files = []
        for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(directory).as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative_path = path.relative_to(directory).as_posix()
            files.append(self._snapshot_file(path, relative_path))
        return JobSnapshot(job_id=job_id or ".", source="local", files=tuple(files))
