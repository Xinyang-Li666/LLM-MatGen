import sqlite3
from pathlib import Path

import pytest


def test_new_store_initializes_versioned_schema_and_pragmas(tmp_path: Path):
    from llm_matgen.database.store import LocalStore
    from llm_matgen.database.schema import SCHEMA_VERSION

    store = LocalStore(tmp_path / "cache.db")
    with store.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_store_uses_short_lived_connections(tmp_path: Path):
    from llm_matgen.database.store import LocalStore

    store = LocalStore(tmp_path / "cache.db")
    with store.connect() as first:
        first_id = id(first)
    with store.connect() as second:
        assert id(second) != first_id or first is not second


def test_store_rejects_missing_readonly_and_corrupt_database(tmp_path: Path):
    from llm_matgen.database.store import DatabaseError, LocalStore

    with pytest.raises(DatabaseError, match="read-only"):
        LocalStore(tmp_path / "missing.db", read_only=True)
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(DatabaseError, match="corrupt"):
        LocalStore(corrupt)
