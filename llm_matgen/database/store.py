"""Short-lived SQLite connections with explicit schema initialization."""

from __future__ import annotations

import sqlite3
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Sequence
from uuid import UUID

from llm_matgen.database.schema import INITIAL_SCHEMA, SCHEMA_VERSION
from llm_matgen.database.models import LocalMaterialQuery, MaterialSnapshot, PropertySet

@dataclass
class BatchResult:
    inserted: int = 0
    existing: int = 0
    failed: list[str] | None = None

    def __post_init__(self):
        if self.failed is None:
            self.failed = []


class DatabaseError(RuntimeError):
    pass


class LocalStore:
    def __init__(
        self,
        path: Path,
        *,
        read_only: bool = False,
        busy_timeout_ms: int = 5000,
    ):
        self.path = Path(path).resolve()
        self.read_only = read_only
        self.busy_timeout_ms = busy_timeout_ms
        if read_only and not self.path.is_file():
            raise DatabaseError(f"read-only database does not exist: {self.path}")
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._initialize()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"database is corrupt or unreadable: {self.path}") from exc
        except OSError as exc:
            raise DatabaseError(f"database path is not writable: {self.path}") from exc

    def _open(self) -> sqlite3.Connection:
        if self.read_only:
            connection = sqlite3.connect(
                f"file:{self.path.as_posix()}?mode=ro",
                uri=True,
                timeout=self.busy_timeout_ms / 1000,
            )
        else:
            connection = sqlite3.connect(
                self.path,
                timeout=self.busy_timeout_ms / 1000,
            )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        if not self.read_only:
            connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise DatabaseError(
                    f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
                )
            if version == 0:
                if self.read_only:
                    raise DatabaseError("read-only database has no initialized schema")
                with connection:
                    connection.executescript(INITIAL_SCHEMA)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = self._open()
        except sqlite3.DatabaseError:
            raise
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _dump(snapshot: MaterialSnapshot) -> tuple:
        return (str(snapshot.snapshot_id), snapshot.material_id, snapshot.source_db_version,
                snapshot.structure_hash, snapshot.formula, json.dumps(snapshot.elements),
                snapshot.n_elements, json.dumps(snapshot.properties.root, allow_nan=False),
                json.dumps(snapshot.property_origins, allow_nan=False),
                json.dumps(snapshot.raw_json, allow_nan=False) if snapshot.raw_json is not None else None,
                snapshot.fetched_at.astimezone(timezone.utc).isoformat())

    @staticmethod
    def _load(row) -> MaterialSnapshot:
        return MaterialSnapshot(snapshot_id=UUID(row[0]), material_id=row[1], source_db_version=row[2],
            structure_hash=row[3], formula=row[4], elements=json.loads(row[5]), n_elements=row[6],
            properties=PropertySet(json.loads(row[7])), property_origins=json.loads(row[8]),
            raw_json=json.loads(row[9]) if row[9] is not None else None,
            fetched_at=datetime.fromisoformat(row[10]))

    def insert_snapshot(self, snapshot: MaterialSnapshot) -> UUID:
        with self.connect() as conn, conn:
            key = (snapshot.material_id, snapshot.source_db_version, snapshot.structure_hash,
                   snapshot.fetched_at.astimezone(timezone.utc).isoformat())
            existing = conn.execute("SELECT snapshot_id FROM material_snapshots WHERE material_id=? AND source_db_version IS ? AND structure_hash IS ? AND fetched_at=?", key).fetchone()
            if existing:
                return UUID(existing[0])
            cur = conn.execute("""INSERT OR IGNORE INTO material_snapshots
                (snapshot_id,material_id,source_db_version,structure_hash,formula,elements_json,n_elements,properties_json,property_origins_json,raw_json,fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", self._dump(snapshot))
            if cur.rowcount == 0:
                row = conn.execute("SELECT snapshot_id FROM material_snapshots WHERE material_id=? AND source_db_version IS ? AND structure_hash IS ? AND fetched_at=?", key).fetchone()
                return UUID(row[0])
            return snapshot.snapshot_id

    def insert_batch(self, snapshots: Sequence[MaterialSnapshot], *, atomic: bool = True) -> BatchResult:
        result = BatchResult()
        with self.connect() as conn:
            try:
                if atomic: conn.execute("BEGIN")
                for snapshot in snapshots:
                    try:
                        before = conn.total_changes
                        conn.execute("INSERT OR IGNORE INTO material_snapshots (snapshot_id,material_id,source_db_version,structure_hash,formula,elements_json,n_elements,properties_json,property_origins_json,raw_json,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", self._dump(snapshot))
                        if conn.total_changes == before: result.existing += 1
                        else: result.inserted += 1
                    except Exception as exc:
                        if atomic: raise
                        result.failed.append(str(exc))
                if atomic: conn.commit()
            except Exception:
                conn.rollback(); raise
        return result

    def get_snapshot(self, snapshot_id: UUID) -> MaterialSnapshot | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM material_snapshots WHERE snapshot_id=?", (str(snapshot_id),)).fetchone()
        return self._load(row) if row else None

    def get_latest(self, material_id: str) -> MaterialSnapshot | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM material_snapshots WHERE material_id=? ORDER BY fetched_at DESC, COALESCE(source_db_version,'') DESC, snapshot_id DESC LIMIT 1", (material_id,)).fetchone()
        return self._load(row) if row else None

    def query(self, query: LocalMaterialQuery) -> list[MaterialSnapshot]:
        clauses, params = [], []
        if query.n_elements is not None: clauses.append("n_elements=?"); params.append(query.n_elements)
        if query.formula_pattern is not None: clauses.append("formula GLOB ?"); params.append(query.formula_pattern)
        if query.band_gap_min is not None: clauses.append("json_extract(properties_json, '$.band_gap') >= ?"); params.append(query.band_gap_min)
        if query.band_gap_max is not None: clauses.append("json_extract(properties_json, '$.band_gap') <= ?"); params.append(query.band_gap_max)
        if query.formation_energy_max is not None: clauses.append("json_extract(properties_json, '$.formation_energy') <= ?"); params.append(query.formation_energy_max)
        if query.elements:
            for element in query.elements:
                clauses.append("EXISTS (SELECT 1 FROM json_each(material_snapshots.elements_json) WHERE value=?)"); params.append(element)
        sql = "SELECT * FROM material_snapshots" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY fetched_at DESC, snapshot_id DESC"
        with self.connect() as conn: rows = conn.execute(sql + " LIMIT ?", [*params, query.limit]).fetchall()
        snapshots = [self._load(r) for r in rows]
        if not query.all_snapshots:
            latest = {}
            for s in snapshots: latest.setdefault(s.material_id, s)
            snapshots = list(latest.values())
        return snapshots[:query.limit]

    def delete_snapshot(self, snapshot_id: UUID) -> bool:
        with self.connect() as conn, conn:
            return conn.execute("DELETE FROM material_snapshots WHERE snapshot_id=?", (str(snapshot_id),)).rowcount > 0

    def export_json(self, path: Path, snapshot_ids: Sequence[UUID] | None = None) -> None:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM material_snapshots" + (" WHERE snapshot_id IN (%s)" % ",".join("?"*len(snapshot_ids)) if snapshot_ids else ""), [str(x) for x in snapshot_ids] if snapshot_ids else []).fetchall()
        payload = {"schema_version": SCHEMA_VERSION, "snapshots": [self._load(r).model_dump(mode="json") for r in rows]}
        payload["checksum"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def import_json(self, path: Path) -> BatchResult:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION: raise DatabaseError("unsupported archive schema version")
        checksum = payload.pop("checksum", None)
        actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if checksum != actual: raise DatabaseError("archive checksum mismatch")
        snapshots = [MaterialSnapshot.model_validate(item) for item in payload.get("snapshots", [])]
        return self.insert_batch(snapshots, atomic=False)
