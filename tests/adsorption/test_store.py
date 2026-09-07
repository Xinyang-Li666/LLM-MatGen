import json
from pathlib import Path

import pytest


def _snapshot(job_id="case", signature="a"):
    from llm_matgen.adsorption.sources.base import JobSnapshot, RemoteFileSnapshot

    files = tuple(RemoteFileSnapshot(name, len(name), 1, (signature + name).ljust(64, "0")) for name in ("POSCAR", "CONTCAR", "INCAR", "OUTCAR", "clean_slab/POSCAR"))
    return JobSnapshot(job_id, "local", files, {})


class _Source:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def discover(self):
        return tuple(self.snapshots)


class _Extractor:
    def __init__(self):
        self.calls = 0

    def extract(self, snapshot):
        from llm_matgen.adsorption.extractor import CaseExtractor

        self.calls += 1
        return CaseExtractor().extract(snapshot)


def test_schema_wal_short_connections_and_scan_lock(tmp_path: Path):
    from llm_matgen.adsorption.store import AdsorptionCaseStore, ScanLockedError

    store = AdsorptionCaseStore(tmp_path / "cases")
    with store.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"metadata", "scan_runs", "case_revisions", "file_evidence"} <= tables
    with store.scan_lock():
        with pytest.raises(ScanLockedError):
            with store.scan_lock():
                pass


def test_scan_skips_unchanged_and_creates_new_revision_for_changed_snapshot(tmp_path: Path):
    from llm_matgen.adsorption.store import AdsorptionCaseStore

    store = AdsorptionCaseStore(tmp_path / "cases")
    extractor = _Extractor()
    source = _Source([_snapshot(signature="a")])
    assert store.scan(source, extractor) == 1
    assert store.scan(source, extractor) == 2
    assert extractor.calls == 1
    source.snapshots[:] = [_snapshot(signature="b")]
    assert store.scan(source, extractor) == 3
    assert extractor.calls == 2
    assert len(store.list_revisions()) == 1
    assert len(store.list_revisions(include_superseded=True)) == 2


def test_scan_failure_rolls_back_revision_and_staging(tmp_path: Path):
    from llm_matgen.adsorption.store import AdsorptionCaseStore

    class Exploding:
        def extract(self, _snapshot):
            raise RuntimeError("controlled")

    store = AdsorptionCaseStore(tmp_path / "cases")
    with pytest.raises(RuntimeError, match="controlled"):
        store.scan(_Source([_snapshot()]), Exploding())
    assert store.status()["index_revision"] == 0
    assert store.list_revisions(include_superseded=True) == []
    assert not list(store.staging_root.iterdir())


def test_artifact_is_staged_under_store_root(tmp_path: Path):
    from llm_matgen.adsorption.store import AdsorptionCaseStore

    store = AdsorptionCaseStore(tmp_path / "cases")
    store.scan(_Source([_snapshot()]), _Extractor())
    revision = store.list_revisions()[0]
    artifact = store.root / revision.artifact_relative_path / "case.json"
    assert artifact.is_file()
    assert json.loads(artifact.read_text(encoding="utf-8"))["case_id"] == "case"
