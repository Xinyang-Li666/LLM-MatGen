"""Deterministic quality gates and audit records for adsorption cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .sources.base import JobSnapshot


class CaseStatus(str, Enum):
    ELIGIBLE = "eligible"
    REJECTED_IONIC_UNCONVERGED = "rejected_ionic_unconverged"
    REJECTED_ELECTRONIC_UNCONVERGED = "rejected_electronic_unconverged"
    REJECTED_FATAL_WARNING = "rejected_fatal_warning"
    REJECTED_INCOMPLETE = "rejected_incomplete"


@dataclass(frozen=True)
class CaseAudit:
    stable_files: bool
    rejection_reasons: tuple[str, ...]
    quality_gate_version: str = "case-quality-1"


@dataclass(frozen=True)
class CaseFeatureSet:
    job_id: str
    artifact_count: int
    source: str


@dataclass(frozen=True)
class ExtractionResult:
    case_id: str
    revision_id: str
    status: CaseStatus
    audit: CaseAudit
    features: CaseFeatureSet | None
    artifacts: tuple[str, ...]
    exact_hash: str


def _identity(snapshot: JobSnapshot) -> str:
    payload = {
        "job_id": snapshot.job_id,
        "source": snapshot.source,
        "files": [
            {
                "path": item.relative_path,
                "size": item.size,
                "mtime_ns": item.mtime_ns,
                "sha256": item.sha256,
            }
            for item in snapshot.files
        ],
        "metadata": snapshot.metadata,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CaseExtractor:
    def extract(self, snapshot: JobSnapshot) -> ExtractionResult:
        exact_hash = _identity(snapshot)
        revision_id = f"{snapshot.job_id}:{exact_hash[:16]}"
        paths = tuple(item.relative_path for item in snapshot.files)
        artifacts = tuple(path for path in paths if path.upper() != "OUTCAR")
        metadata: dict[str, Any] = snapshot.metadata or {}

        status = CaseStatus.ELIGIBLE
        reasons: list[str] = []
        stable = bool(metadata.get("stable", True))
        if not stable:
            status, reasons = CaseStatus.REJECTED_INCOMPLETE, ["unstable_files"]
        elif metadata.get("fatal_warning"):
            status, reasons = CaseStatus.REJECTED_FATAL_WARNING, ["fatal_marker"]
        elif metadata.get("electronic_converged", True) is False:
            status, reasons = CaseStatus.REJECTED_ELECTRONIC_UNCONVERGED, ["electronic_not_converged"]
        elif metadata.get("ionic_converged", True) is False:
            status, reasons = CaseStatus.REJECTED_IONIC_UNCONVERGED, ["ionic_not_converged"]
        elif metadata.get("run_type") in {"neb", "static", "frequency"}:
            status, reasons = CaseStatus.REJECTED_INCOMPLETE, [f"{metadata['run_type']}_run"]
        elif not any(path.lower().startswith("clean_slab/") for path in paths):
            status, reasons = CaseStatus.REJECTED_INCOMPLETE, ["clean_parent_missing"]

        audit = CaseAudit(stable_files=stable, rejection_reasons=tuple(reasons))
        features = (
            CaseFeatureSet(snapshot.job_id, len(artifacts), snapshot.source)
            if status is CaseStatus.ELIGIBLE
            else None
        )
        return ExtractionResult(
            case_id=snapshot.job_id,
            revision_id=revision_id,
            status=status,
            audit=audit,
            features=features,
            artifacts=artifacts,
            exact_hash=exact_hash,
        )
