"""Short-lived SQLite connections with explicit schema initialization."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from llm_matgen.database.schema import INITIAL_SCHEMA, SCHEMA_VERSION


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
