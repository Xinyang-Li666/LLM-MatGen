"""Transactional, ordered SQLite schema migrations."""
from __future__ import annotations
import sqlite3
from llm_matgen.database.schema import SCHEMA_VERSION, INITIAL_SCHEMA

def migrate(connection: sqlite3.Connection, target: int = SCHEMA_VERSION) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > target:
        raise RuntimeError(f"database schema version {current} is newer than supported {target}")
    if current == target:
        return
    with connection:
        if current == 0 and target >= 1:
            connection.executescript(INITIAL_SCHEMA)
            connection.execute("PRAGMA user_version = 1")
        else:
            raise RuntimeError(f"no migration path from schema version {current} to {target}")
