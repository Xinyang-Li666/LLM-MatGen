"""Transactional SQLite index for audited adsorption case revisions."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .extractor import CaseStatus, ExtractionResult, snapshot_identity
from .schema import SCHEMA, SCHEMA_VERSION


class AdsorptionStoreError(RuntimeError):
    pass


class ScanLockedError(AdsorptionStoreError):
    pass


@dataclass(frozen=True)
class StoredRevision:
    revision_id: str
    case_id: str
    status: CaseStatus
    exact_hash: str
    artifact_relative_path: str
    index_revision: int
    superseded_by: str | None = None


class AdsorptionCaseStore:
    def __init__(self, root: Path | str, *, stale_lock_seconds: float = 3600):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "adsorption-cases.sqlite3"
        self.artifact_root = self.root / "artifacts"
        self.staging_root = self.root / ".staging"
        self.lock_path = self.root / ".scan.lock"
        self.stale_lock_seconds = stale_lock_seconds
        self.artifact_root.mkdir(exist_ok=True)
        self.staging_root.mkdir(exist_ok=True)
        self._initialize()

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._open() as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            connection.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES ('index_revision', '0')")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._open()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def scan_lock(self):
        token = secrets.token_hex(16)
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ScanLockedError("scan already active") from exc
        try:
            os.write(descriptor, json.dumps({"token": token}).encode())
            os.close(descriptor)
            yield
        finally:
            try:
                payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
                if payload.get("token") == token:
                    self.lock_path.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                pass

    def _next_index(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT value FROM metadata WHERE key='index_revision'").fetchone()[0]) + 1

    def scan(self, source, extractor) -> int:
        with self.scan_lock():
            token = secrets.token_hex(8)
            stage = self.staging_root / token
            stage.mkdir()
            try:
                with self._open() as connection:
                    index_revision = self._next_index(connection)
                    connection.execute("BEGIN")
                    snapshots = tuple(source.discover())
                    for snapshot in snapshots:
                        existing = connection.execute(
                            "SELECT * FROM case_revisions WHERE case_id=? AND superseded_by IS NULL ORDER BY index_revision DESC LIMIT 1",
                            (snapshot.job_id,),
                        ).fetchone()
                        if existing and existing["exact_hash"] == self._snapshot_hash(snapshot):
                            continue
                        result: ExtractionResult = extractor.extract(snapshot)
                        artifact_name = result.revision_id.replace(":", "_")
                        artifact_relative = Path("artifacts") / artifact_name
                        staged_artifact = stage / artifact_name
                        staged_artifact.mkdir()
                        (staged_artifact / "case.json").write_text(
                            json.dumps(self._result_json(result), sort_keys=True, indent=2), encoding="utf-8"
                        )
                        final_artifact = self.root / artifact_relative
                        final_artifact.parent.mkdir(parents=True, exist_ok=True)
                        staged_artifact.replace(final_artifact)
                        if existing:
                            connection.execute("UPDATE case_revisions SET superseded_by=? WHERE revision_id=?", (result.revision_id, existing["revision_id"]))
                        connection.execute(
                            "INSERT INTO case_revisions VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                            (result.revision_id, result.case_id, result.exact_hash, result.status.value,
                             json.dumps(asdict(result.audit), sort_keys=True),
                             json.dumps(asdict(result.features), sort_keys=True) if result.features else None,
                             json.dumps(result.artifacts), str(artifact_relative), index_revision),
                        )
                        for item in snapshot.files:
                            connection.execute("INSERT INTO file_evidence VALUES (?,?,?,?,?)", (result.revision_id, item.relative_path, item.size, item.mtime_ns, item.sha256))
                    connection.execute("UPDATE metadata SET value=? WHERE key='index_revision'", (str(index_revision),))
                    connection.commit()
                return index_revision
            except Exception:
                with self._open() as connection:
                    connection.rollback()
                raise
            finally:
                if stage.exists():
                    for child in stage.iterdir():
                        if child.exists():
                            import shutil
                            shutil.rmtree(child, ignore_errors=True)
                    stage.rmdir()

    @staticmethod
    def _snapshot_hash(snapshot) -> str:
        return snapshot_identity(snapshot)

    @staticmethod
    def _result_json(result: ExtractionResult):
        data = asdict(result)
        data["status"] = result.status.value
        return data

    def status(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='index_revision'").fetchone()
            return {"schema_version": SCHEMA_VERSION, "index_revision": int(row[0])}

    def list_revisions(self, *, include_superseded: bool = False) -> list[StoredRevision]:
        with self.connect() as connection:
            query = "SELECT * FROM case_revisions"
            if not include_superseded:
                query += " WHERE superseded_by IS NULL"
            query += " ORDER BY case_id, index_revision"
            return [StoredRevision(row["revision_id"], row["case_id"], CaseStatus(row["status"]), row["exact_hash"], row["artifact_relative_path"], row["index_revision"], row["superseded_by"]) for row in connection.execute(query)]
