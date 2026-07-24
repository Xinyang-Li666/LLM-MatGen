"""SQLite schema version and initialization statements."""

SCHEMA_VERSION = 1

INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    material_id TEXT NOT NULL,
    source_db_version TEXT,
    structure_hash TEXT,
    formula TEXT NOT NULL,
    elements_json TEXT NOT NULL,
    n_elements INTEGER NOT NULL CHECK (n_elements > 0),
    properties_json TEXT NOT NULL,
    property_origins_json TEXT NOT NULL,
    raw_json TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(material_id, source_db_version, structure_hash, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_material ON material_snapshots(material_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_formula ON material_snapshots(formula);
"""
