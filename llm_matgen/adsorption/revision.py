"""Audited manual revision sidecars (v2) with v1 migration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

from llm_matgen.utils.structure import structure_sha256


class _RevisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionChange(_RevisionModel):
    atom_index: int = Field(ge=0)
    old_frac_coords: tuple[float, float, float]
    new_frac_coords: tuple[float, float, float]


class RevisionSidecarV1(_RevisionModel):
    version: int = 1
    parent_hash: str
    child_hash: str
    atom_index: int = Field(ge=0)
    old_frac_coords: tuple[float, float, float]
    new_frac_coords: tuple[float, float, float]
    reason: str = "manual"
    timestamp: str | None = None


class RevisionSidecarV2(_RevisionModel):
    version: int = 2
    parent_hash: str
    child_hash: str
    changes: tuple[RevisionChange, ...] = Field(min_length=1)
    reason: str = "manual"
    timestamp: str | None = None

    @model_validator(mode="after")
    def unique_indices(self):
        indices = [change.atom_index for change in self.changes]
        if len(indices) != len(set(indices)):
            raise ValueError("duplicate atom index in revision changes")
        return self


def normalize_revision(sidecar: RevisionSidecarV1 | RevisionSidecarV2) -> RevisionSidecarV2:
    if isinstance(sidecar, RevisionSidecarV2):
        return sidecar
    return RevisionSidecarV2(
        parent_hash=sidecar.parent_hash,
        child_hash=sidecar.child_hash,
        changes=(RevisionChange(atom_index=sidecar.atom_index, old_frac_coords=sidecar.old_frac_coords, new_frac_coords=sidecar.new_frac_coords),),
        reason=sidecar.reason,
        timestamp=sidecar.timestamp,
    )


@dataclass(frozen=True)
class ImportedRevision:
    path: Path
    parent_hash: str
    child_hash: str


class RevisionImporter:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def import_revision(self, parent: Structure, child: Structure, sidecar: RevisionSidecarV1 | RevisionSidecarV2) -> ImportedRevision:
        revision = normalize_revision(sidecar)
        parent_hash = structure_sha256(parent)
        child_hash = structure_sha256(child)
        if revision.parent_hash != parent_hash or revision.child_hash != child_hash:
            raise ValueError("revision structure hash does not match parent or child")
        if len(parent) != len(child) or [str(site.specie) for site in parent] != [str(site.specie) for site in child]:
            raise ValueError("revision may only change declared atom coordinates")
        if not np.allclose(parent.lattice.matrix, child.lattice.matrix) or parent.pbc != child.pbc:
            raise ValueError("revision may not change lattice or periodic boundary conditions")
        changed = set()
        for change in revision.changes:
            if change.atom_index >= len(parent):
                raise ValueError("revision atom index is out of range")
            if not np.allclose(parent.frac_coords[change.atom_index], change.old_frac_coords, atol=1e-8):
                raise ValueError("revision old coordinate does not match parent")
            if not np.allclose(child.frac_coords[change.atom_index], change.new_frac_coords, atol=1e-8):
                raise ValueError("revision new coordinate does not match child")
            changed.add(change.atom_index)
        actual_changed = {index for index in range(len(parent)) if not np.allclose(parent.frac_coords[index], child.frac_coords[index], atol=1e-8)}
        if changed != actual_changed:
            raise ValueError("revision changes do not exactly describe coordinate changes")
        destination = self.root / child_hash
        if destination.exists():
            raise FileExistsError(f"revision destination already exists: {destination}")
        staging = self.root / f".staging-{hashlib.sha256(child_hash.encode()).hexdigest()[:12]}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            Poscar(child).write_file(staging / "child.POSCAR")
            (staging / "child.mson").write_text(child.to(fmt="json"), encoding="utf-8")
            (staging / "sidecar.json").write_text(revision.model_dump_json(indent=2), encoding="utf-8")
            manifest = {"version": 2, "parent_hash": parent_hash, "child_hash": child_hash, "reason": revision.reason, "timestamp": revision.timestamp or datetime.now(timezone.utc).isoformat()}
            (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            staging.replace(destination)
        except Exception:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return ImportedRevision(destination, parent_hash, child_hash)

