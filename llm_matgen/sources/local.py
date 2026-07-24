"""Filesystem structure source constrained to explicitly allowed roots."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from llm_matgen.io.readers import StructureReadError, read_structure
from llm_matgen.sources.models import SourceStructure
from llm_matgen.utils.structure import structure_sha256


class LocalSourceError(ValueError):
    """Raised when a local reference is unsafe or unreadable."""


class LocalStructureSource:
    def __init__(
        self,
        allowed_roots: list[Path],
        *,
        lammps_element_map: dict[int, str] | None = None,
    ):
        if not allowed_roots:
            raise ValueError("at least one allowed root is required")
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        self.lammps_element_map = lammps_element_map

    def get(self, reference: str) -> SourceStructure:
        requested = Path(reference)
        resolved = requested.resolve()
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            raise LocalSourceError(f"path is outside allowed roots: {reference}")
        if not resolved.exists():
            raise LocalSourceError(f"structure file does not exist: {reference}")
        if not resolved.is_file():
            raise LocalSourceError(f"structure path must be a regular file: {reference}")
        try:
            structure = read_structure(
                resolved,
                lammps_element_map=self.lammps_element_map,
            )
        except StructureReadError as exc:
            raise LocalSourceError(f"failed to parse local structure: {resolved.name}") from exc
        structure_hash = structure_sha256(structure)
        return SourceStructure(
            artifact_id=structure_hash,
            source_kind="local",
            source_reference=reference,
            structure_hash=structure_hash,
            retrieved_at=datetime.now(timezone.utc),
            local_path=resolved,
            structure=structure,
        )
