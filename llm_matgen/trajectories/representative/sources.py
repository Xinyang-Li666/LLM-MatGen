"""Source configuration and streaming inventory for representative sampling."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from llm_matgen.trajectories.filtering.readers import FilterTrajectoryReader

from .models import SourceFrame, SourceInventory, SourceSpec


def load_source_config(path: Path) -> tuple[SourceSpec, ...]:
    """Load a UTF-8 source config and resolve paths relative to that config."""

    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("source config must contain a non-empty sources list")
    sources: list[SourceSpec] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise ValueError("each source config entry must be an object")
        raw_path = raw.get("path")
        if not raw_path:
            raise ValueError("source path must not be empty")
        source_path = Path(str(raw_path))
        if not source_path.is_absolute():
            source_path = (config_path.parent / source_path).resolve()
        sources.append(SourceSpec(
            name=str(raw.get("name", "")),
            path=source_path,
            input_format=raw.get("input_format"),
            type_map={int(key): value for key, value in dict(raw.get("type_map", {})).items()},
            assume_type_is_atomic_number=bool(raw.get("assume_type_is_atomic_number", False)),
            cleaned=bool(raw.get("cleaned", False)),
        ))
    names = [source.name for source in sources]
    if len(names) != len(set(names)):
        raise ValueError("duplicate source names are not allowed")
    return tuple(sources)


def iter_source_frames(source: SourceSpec) -> Iterator[SourceFrame]:
    """Yield one source-tagged frame at a time without materializing the trajectory."""

    reader = FilterTrajectoryReader(
        source.path,
        input_format=source.input_format,
        lammps_type_map=source.type_map,
        assume_type_is_z=source.assume_type_is_atomic_number,
    )
    for frame in reader.iter_frames():
        yield SourceFrame(source=source, frame=frame)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_sources(
    sources: Sequence[SourceSpec],
    *,
    allowed_atomic_numbers: set[int] | None = None,
    forbidden_atomic_numbers: set[int] | None = None,
) -> tuple[SourceInventory, ...]:
    """Scan sources once, validating elements and collecting reproducibility metadata."""

    forbidden = set(forbidden_atomic_numbers or ())
    allowed = None if allowed_atomic_numbers is None else set(allowed_atomic_numbers)
    inventories: list[SourceInventory] = []
    seen_names: set[str] = set()
    for source in sources:
        if source.name in seen_names:
            raise ValueError("duplicate source names are not allowed")
        seen_names.add(source.name)
        if not source.path.is_file():
            raise FileNotFoundError(source.path)
        frame_count = 0
        atomic_numbers: set[int] = set()
        natom_values: set[int] = set()
        for tagged in iter_source_frames(source):
            frame = tagged.frame
            numbers = {int(value) for value in frame.atomic_numbers}
            forbidden_found = numbers & forbidden
            if forbidden_found:
                labels = ", ".join(_symbol(number) for number in sorted(forbidden_found))
                raise ValueError(
                    f"source {source.name} frame {frame.source_index} contains forbidden element {labels}"
                )
            if allowed is not None:
                unknown = numbers - allowed
                if unknown:
                    labels = ", ".join(_symbol(number) for number in sorted(unknown))
                    raise ValueError(
                        f"source {source.name} frame {frame.source_index} contains element(s) not allowed: {labels}"
                    )
            frame_count += 1
            atomic_numbers.update(numbers)
            natom_values.add(frame.natoms)
        warnings = () if source.cleaned else ("input_not_declared_clean",)
        inventories.append(SourceInventory(
            source=source,
            frame_count=frame_count,
            atomic_numbers=tuple(sorted(atomic_numbers)),
            natom_values=tuple(sorted(natom_values)),
            sha256=_file_sha256(source.path),
            warnings=warnings,
        ))
    return tuple(inventories)


def _symbol(atomic_number: int) -> str:
    from ase.data import chemical_symbols

    if 0 < atomic_number < len(chemical_symbols):
        return chemical_symbols[atomic_number]
    return f"Z{atomic_number}"
