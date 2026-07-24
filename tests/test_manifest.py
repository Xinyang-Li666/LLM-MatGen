from datetime import datetime, timezone
from pathlib import Path

import pytest


def test_manifest_writes_run_metadata_lineage_artifacts_and_disclaimer(tmp_path: Path):
    from llm_matgen.io.manifest import (
        ManifestArtifact,
        ManifestStore,
        ManifestStructure,
        RunManifest,
    )

    manifest = RunManifest(
        run_id="run-0001",
        created_at=datetime.now(timezone.utc),
        software_version="0.1.0",
        input_source="fixture",
        parameters={"seed": 7},
        structures=[
            ManifestStructure(
                structure_id="child-1",
                parent_structure_id="parent-1",
                formula="LiCoO2",
                n_atoms=4,
                actual_parameters={"concentration": 0.25},
                site_mapping={"site-1": "site-2"},
                check_issues=[{"code": "close-contact", "level": "warning"}],
            )
        ],
        artifacts=[
            ManifestArtifact(
                structure_id="child-1",
                format="poscar",
                path="child-1.vasp",
                sha256="a" * 64,
            )
        ],
        warnings=["geometry warning"],
    )
    path = ManifestStore(tmp_path).write_atomic(manifest)

    assert path == tmp_path / "run-0001" / "manifest.json"
    restored = RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
    assert restored.responsibility_disclaimer
    assert restored.structures[0].parent_structure_id == "parent-1"
    assert restored.artifacts[0].sha256 == "a" * 64


def test_manifest_rejects_duplicate_run_id_and_writes_no_partial_file(tmp_path: Path):
    from llm_matgen.io.manifest import ManifestStore, RunManifest

    manifest = RunManifest(
        run_id="run-0001",
        created_at=datetime.now(timezone.utc),
        software_version="0.1.0",
        input_source="fixture",
    )
    store = ManifestStore(tmp_path)
    store.write_atomic(manifest)

    with pytest.raises(FileExistsError):
        store.write_atomic(manifest)

    assert not list((tmp_path / "run-0001").glob("*.tmp"))


def test_manifest_rejects_invalid_digest_id_and_nonempty_run_directory(tmp_path: Path):
    from llm_matgen.io.manifest import ManifestArtifact, ManifestStore, RunManifest

    with pytest.raises(ValueError, match="sha256"):
        ManifestArtifact(
            structure_id="s",
            format="poscar",
            path="s.vasp",
            sha256="not-a-digest",
        )

    invalid = RunManifest(
        run_id="../escape",
        created_at=datetime.now(timezone.utc),
        software_version="0.1.0",
        input_source="fixture",
    )
    with pytest.raises(ValueError, match="safe"):
        ManifestStore(tmp_path).write_atomic(invalid)

    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "artifact.vasp").write_text("data", encoding="utf-8")
    manifest = RunManifest(
        run_id="busy",
        created_at=datetime.now(timezone.utc),
        software_version="0.1.0",
        input_source="fixture",
    )
    with pytest.raises(FileExistsError, match="not empty"):
        ManifestStore(tmp_path).write_atomic(manifest)
