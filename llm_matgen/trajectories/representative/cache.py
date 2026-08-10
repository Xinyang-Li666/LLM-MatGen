"""Content-addressed descriptor cache with resumable chunk markers."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CacheFingerprint:
    digest: str
    payload: dict[str, Any]

    @property
    def payload_json(self) -> str:
        return _canonical_json(self.payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CacheFingerprint":
        normalized = json.loads(_canonical_json(payload))
        digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
        return cls(digest=digest, payload=normalized)


def fingerprint_payload(payload: dict[str, Any]) -> CacheFingerprint:
    return CacheFingerprint.from_payload(payload)


class DescriptorCache:
    """A cache directory shared by runs; run state only references it."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._fingerprint_path = self.root / "fingerprint.json"

    def initialize(self, fingerprint: CacheFingerprint) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self._fingerprint_path.exists():
            self.validate(fingerprint)
            return
        self._atomic_json_write(
            self._fingerprint_path,
            {"digest": fingerprint.digest, "payload": fingerprint.payload},
        )

    def validate(self, fingerprint: CacheFingerprint) -> None:
        if not self._fingerprint_path.exists():
            raise ValueError("cache fingerprint is missing")
        try:
            stored = json.loads(self._fingerprint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("cache fingerprint is unreadable") from exc
        if stored.get("digest") != fingerprint.digest:
            raise ValueError("cache fingerprint does not match requested input/configuration")

    def create_memmap(self, name: str, shape: tuple[int, ...], dtype: str | np.dtype = "float64") -> np.memmap:
        self._validate_name(name)
        shape = tuple(int(value) for value in shape)
        if not shape or any(value <= 0 for value in shape):
            raise ValueError("memmap shape must contain positive dimensions")
        self.root.mkdir(parents=True, exist_ok=True)
        meta_path = self.root / f"{name}.meta.json"
        data_path = self.root / f"{name}.dat"
        dtype_obj = np.dtype(dtype)
        metadata = {"shape": list(shape), "dtype": dtype_obj.str}
        if meta_path.exists():
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            if existing != metadata:
                raise ValueError(f"memmap metadata mismatch for {name}")
        else:
            self._atomic_json_write(meta_path, metadata)
        return np.memmap(data_path, mode="r+" if data_path.exists() else "w+", dtype=dtype_obj, shape=shape)

    def open_memmap(self, name: str, shape: tuple[int, ...], dtype: str | np.dtype = "float64") -> np.memmap:
        return self.create_memmap(name, shape, dtype)

    def mark_chunk_complete(self, name: str, start: int, stop: int) -> None:
        self._validate_name(name)
        if not (0 <= int(start) < int(stop)):
            raise ValueError("chunk must satisfy 0 <= start < stop")
        chunks = list(self.completed_chunks(name))
        new = (int(start), int(stop))
        if any(max(a, new[0]) < min(b, new[1]) for a, b in chunks):
            raise ValueError("chunk range overlap")
        chunks.append(new)
        chunks.sort()
        path = self.root / f"{name}.chunks.json"
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(json.dumps(chunks, separators=(",", ":")), encoding="utf-8")
        os.replace(part, path)

    def completed_chunks(self, name: str) -> tuple[tuple[int, int], ...]:
        self._validate_name(name)
        path = self.root / f"{name}.chunks.json"
        if not path.exists():
            return ()
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            return tuple((int(item[0]), int(item[1])) for item in values)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid completed chunk metadata for {name}") from exc

    def recompute(self, fingerprint: CacheFingerprint) -> CacheFingerprint:
        payload = dict(fingerprint.payload)
        payload["recompute_nonce"] = time.time_ns()
        result = CacheFingerprint.from_payload(payload)
        self._atomic_json_write(self._fingerprint_path, {"digest": result.digest, "payload": result.payload})
        return result

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("cache artifact name must be a simple filename")

    @staticmethod
    def _atomic_json_write(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(part, path)

