"""Run-level provenance manifests."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_matgen.generators.models import JsonValue

DISCLAIMER = (
    "LLM-MatGen only generates structure files. It does not guarantee "
    "stability, synthesizability, relaxation convergence, or publication quality."
)


class ManifestStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure_id: str
    parent_structure_id: str
    parent_structure_ids: dict[str, str] = Field(default_factory=dict)
    formula: str
    n_atoms: int
    actual_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    site_mapping: dict[str, str | None] = Field(default_factory=dict)
    check_issues: list[dict[str, JsonValue]] = Field(default_factory=list)


class ManifestArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure_id: str
    format: str
    path: str
    sha256: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("sha256 must be a lowercase 64-character hex digest")
        return value


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    software_version: str
    input_source: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    structures: list[ManifestStructure] = Field(default_factory=list)
    artifacts: list[ManifestArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    responsibility_disclaimer: str = DISCLAIMER


class ManifestStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def write_atomic(self, manifest: RunManifest, *, allow_existing_dir: bool = False) -> Path:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", manifest.run_id) is None or ".." in manifest.run_id:
            raise ValueError("run_id must be a safe relative directory name")
        run_dir = self.root / manifest.run_id
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            raise FileExistsError(f"manifest already exists: {manifest_path}")
        if run_dir.exists():
            if any(run_dir.iterdir()) and not allow_existing_dir:
                raise FileExistsError(f"run directory is not empty: {run_dir}")
        else:
            run_dir.mkdir(parents=True, exist_ok=False)
        temporary_path = run_dir / "manifest.json.tmp"
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(manifest.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, manifest_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            try:
                run_dir.rmdir()
            except OSError:
                pass
            raise
        return manifest_path
