"""Common source metadata contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from pymatgen.core import Molecule, Structure


class SourceStructure(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    artifact_id: str
    source_kind: Literal["local", "materials-project"]
    source_reference: str
    structure_hash: str
    database_version: str | None = None
    retrieved_at: datetime
    local_path: Path | None = None
    structure: Structure


class SourceMolecule(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    artifact_id: str
    source_kind: Literal["local", "materials-project"]
    source_reference: str
    molecule_hash: str
    retrieved_at: datetime
    local_path: Path | None = None
    molecule: Molecule


class StructureSource(Protocol):
    def get(self, reference: str) -> SourceStructure: ...

    def get_molecule(self, reference: str) -> SourceMolecule: ...
