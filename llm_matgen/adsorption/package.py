"""Portable, hash-addressable adsorption run artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PackageArtifact:
    kind: str
    path: Path
    sha256: str


def _jsonable(value: Any):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def write_adsorption_artifacts(
    run_dir: Path,
    *,
    references: dict[str, Any],
    retrieval_trace: Any,
    validation: Any,
    dft_handoff: Any,
    proposal_audit: Any | None = None,
) -> tuple[PackageArtifact, ...]:
    root = Path(run_dir).resolve() / "adsorption"
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "references": references,
        "retrieval": retrieval_trace,
        "validation": validation,
        "dft_handoff": dft_handoff,
    }
    if proposal_audit is not None:
        payloads["proposal_audit"] = proposal_audit
    artifacts = []
    for kind, payload in payloads.items():
        path = root / f"{kind}.json"
        data = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(data, encoding="utf-8", newline="\n")
        temporary.replace(path)
        artifacts.append(PackageArtifact(kind, path, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(artifacts)
