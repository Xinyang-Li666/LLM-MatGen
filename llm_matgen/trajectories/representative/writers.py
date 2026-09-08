"""Atomic, auditable export for representative sampling runs."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ase import Atoms
from ase.io import write

from llm_matgen.trajectories.filtering.models import FilterFrame
from .models import SelectionRecord


def write_outputs(
    selected: Iterable[tuple[FilterFrame, SelectionRecord]],
    output_root: str | Path,
    *,
    formats: tuple[str, ...] = (),
    cache_root: str | Path | None = None,
) -> dict[str, str | int]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir()
    pairs = list(selected)
    atoms_list = [_atoms(frame, record) for frame, record in pairs]
    selected_path = run_dir / "selected.extxyz"
    _atomic_write_extxyz(selected_path, atoms_list)
    selection_path = run_dir / "selection.jsonl"
    _atomic_text_write(selection_path, "".join(json.dumps(_record_dict(record), ensure_ascii=False, sort_keys=True) + "\n" for _, record in pairs))
    summary_path = run_dir / "summary.json"
    _atomic_json_write(summary_path, {"selected_count": len(pairs), "formats": list(formats)})
    manifest = {"selected_path": selected_path.name, "selection_path": selection_path.name, "selected_count": len(pairs), "files": [selected_path.name, selection_path.name, "summary.json"]}
    for index, (atoms, _) in enumerate(zip(atoms_list, pairs)):
        for fmt in formats:
            normalized = fmt.lower()
            extension, directory, ase_format = {
                "poscar": ("vasp", "poscar", "vasp"), "vasp": ("vasp", "poscar", "vasp"),
                "cif": ("cif", "cif", "cif"), "lammps": ("data", "lammps", "lammps-data"),
            }.get(normalized, (None, None, None))
            if extension is None:
                raise ValueError(f"unsupported output format: {fmt}")
            target_dir = run_dir / directory
            target_dir.mkdir(exist_ok=True)
            target = target_dir / f"{index:06d}.{extension}"
            part = target.with_suffix(target.suffix + ".part")
            write(part, atoms, format=ase_format)
            os.replace(part, target)
            manifest["files"].append(str(target.relative_to(run_dir)))
    manifest_path = run_dir / "manifest.json"
    _atomic_json_write(manifest_path, manifest)
    if cache_root is not None:
        cache_path = Path(cache_root)
        reference = {"cache_root": os.path.relpath(cache_path, run_dir), "owned_by_run": False}
        _atomic_json_write(run_dir / "cache-reference.json", reference)
    return {"run_dir": str(run_dir), "selected_path": str(selected_path), "selection_path": str(selection_path), "summary_path": str(summary_path), "manifest_path": str(manifest_path), "selected_count": len(pairs)}


def write_outputs_streaming(
    selected: Iterable[tuple[FilterFrame, SelectionRecord]],
    output_root: str | Path,
    *,
    cache_root: str | Path | None = None,
) -> dict[str, str | int]:
    """Write selected frames one at a time without retaining structures in RAM."""
    root = Path(output_root); root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"; run_dir.mkdir()
    selected_path = run_dir / "selected.extxyz"; selected_part = selected_path.with_suffix(".extxyz.part")
    selection_path = run_dir / "selection.jsonl"; selection_part = selection_path.with_suffix(".jsonl.part")
    count = 0
    with (
        selection_part.open("w", encoding="utf-8", newline="\n") as records,
        selected_part.open("w", encoding="utf-8", newline="\n") as trajectory,
    ):
        for frame, record in selected:
            atoms = _atoms(frame, record)
            write(trajectory, atoms, format="extxyz")
            records.write(json.dumps(_record_dict(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    if count == 0:
        raise ValueError("no frames selected")
    os.replace(selected_part, selected_path); os.replace(selection_part, selection_path)
    summary_path = run_dir / "summary.json"; _atomic_json_write(summary_path, {"selected_count": count, "formats": []})
    manifest = {"selected_path": selected_path.name, "selection_path": selection_path.name, "selected_count": count, "files": [selected_path.name, selection_path.name, "summary.json"]}
    manifest_path = run_dir / "manifest.json"; _atomic_json_write(manifest_path, manifest)
    if cache_root is not None:
        _atomic_json_write(run_dir / "cache-reference.json", {"cache_root": os.path.relpath(Path(cache_root), run_dir), "owned_by_run": False})
    return {"run_dir": str(run_dir), "selected_path": str(selected_path), "selection_path": str(selection_path), "summary_path": str(summary_path), "manifest_path": str(manifest_path), "selected_count": count}


def _atoms(frame: FilterFrame, record: SelectionRecord) -> Atoms:
    atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
    atoms.info.update({"source_name": record.source_name, "source_index": record.source_index, "source_timestep": record.source_timestep, "sampling_rank": record.sampling_rank})
    return atoms


def _record_dict(record: SelectionRecord) -> dict[str, object]:
    return {"source_name": record.source_name, "source_index": record.source_index, "source_timestep": record.source_timestep, "sampling_rank": record.sampling_rank, "fps_distance": record.fps_distance, "source_quota": record.source_quota}


def _atomic_write_extxyz(path: Path, atoms: list[Atoms]) -> None:
    part = path.with_suffix(path.suffix + ".part")
    with part.open("w", encoding="utf-8", newline="\n") as handle:
        write(handle, atoms, format="extxyz")
    os.replace(part, path)


def _atomic_text_write(path: Path, text: str) -> None:
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _atomic_json_write(path: Path, payload: object) -> None:
    _atomic_text_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
