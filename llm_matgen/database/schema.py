"""SQLite schema version and initialization statements."""

SCHEMA_VERSION = 1

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
