"""SQLite schema for the adsorption case index."""

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scan_runs (
    index_revision INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_revisions (
    revision_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    exact_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    audit_json TEXT NOT NULL,
    features_json TEXT,
    artifacts_json TEXT NOT NULL,
    artifact_relative_path TEXT NOT NULL,
    index_revision INTEGER NOT NULL,
    superseded_by TEXT
);
CREATE TABLE IF NOT EXISTS file_evidence (
    revision_id TEXT NOT NULL REFERENCES case_revisions(revision_id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY(revision_id, relative_path)
);
"""
