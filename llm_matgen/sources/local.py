"""Filesystem structure source constrained to explicitly allowed roots."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from monty.serialization import loadfn
from pymatgen.core import Molecule

from llm_matgen.io.readers import StructureReadError, read_structure
from llm_matgen.sources.models import SourceMolecule, SourceStructure
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
        resolved = self._resolve_file(reference, "structure")
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

    def _resolve_file(self, reference: str, kind: str) -> Path:
        resolved = Path(reference).resolve()
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            raise LocalSourceError(f"path is outside allowed roots: {reference}")
        if not resolved.exists():
            raise LocalSourceError(f"{kind} file does not exist: {reference}")
        if not resolved.is_file():
            raise LocalSourceError(f"{kind} path must be a regular file: {reference}")
        return resolved

    def get_molecule(self, reference: str) -> SourceMolecule:
        resolved = self._resolve_file(reference, "molecule")
        try:
            molecule = loadfn(resolved) if resolved.suffix.lower() in {".json", ".mson"} else Molecule.from_file(resolved)
        except Exception as exc:
            raise LocalSourceError(f"failed to parse local molecule: {resolved.name}") from exc
        if not isinstance(molecule, Molecule) or not len(molecule) or not np.isfinite(molecule.cart_coords).all():
            raise LocalSourceError(f"local molecule is empty or invalid: {resolved.name}")
        payload = {
            "species": [str(site.specie) for site in molecule],
            "coordinates": np.round(np.asarray(molecule.cart_coords, dtype=float), 12).tolist(),
            "charge": float(molecule.charge),
            "spin_multiplicity": int(molecule.spin_multiplicity),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return SourceMolecule(
            artifact_id=digest,
            source_kind="local",
            source_reference=reference,
            molecule_hash=digest,
            retrieved_at=datetime.now(timezone.utc),
            local_path=resolved,
            molecule=molecule,
        )
