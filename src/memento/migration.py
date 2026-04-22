"""v0.3 → v0.5 in-place database migration."""
import hashlib
import sqlite3
from datetime import datetime, timezone

RIGIDITY_DEFAULTS = {
    "preference": 0.7, "convention": 0.7,
    "fact": 0.5, "decision": 0.5,
    "debugging": 0.15, "insight": 0.15,
}

_NEW_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS capture_log (
    id                TEXT PRIMARY KEY,
    content           TEXT NOT NULL,
    type              TEXT DEFAULT 'fact',
    tags              TEXT,
    importance        TEXT DEFAULT 'normal',
    origin            TEXT DEFAULT 'human',
    source_session_id TEXT,
    source_event_id   TEXT,
    content_hash      TEXT NOT NULL,
    embedding         BLOB,
    embedding_dim     INTEGER,
    embedding_pending INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL,
    epoch_id          TEXT,
    disposition       TEXT,
    drop_reason       TEXT
);

CREATE INDEX IF NOT EXISTS idx_capture_unconsumed ON capture_log(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_capture_hash ON capture_log(content_hash);
CREATE INDEX IF NOT EXISTS idx_capture_created ON capture_log(created_at);

CREATE TABLE IF NOT EXISTS nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    target_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    direction            TEXT DEFAULT 'directed',
    type                 TEXT NOT NULL,
    association_strength REAL DEFAULT 0.5,
    created_at           TEXT NOT NULL,
    last_coactivated_at  TEXT,
    CHECK(source_id <> target_id),
    UNIQUE(source_id, target_id, type)
);

CREATE INDEX IF NOT EXISTS idx_nexus_source ON nexus(source_id, type);
CREATE INDEX IF NOT EXISTS idx_nexus_target ON nexus(target_id, type);
CREATE INDEX IF NOT EXISTS idx_nexus_strength ON nexus(source_id, association_strength DESC);

CREATE TABLE IF NOT EXISTS delta_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id   TEXT NOT NULL,
    delta_type  TEXT NOT NULL,
    delta_value REAL NOT NULL,
    epoch_id    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delta_unconsumed ON delta_ledger(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_delta_engram ON delta_ledger(engram_id);

CREATE TABLE IF NOT EXISTS recon_buffer (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id                 TEXT NOT NULL,
    query_context             TEXT,
    coactivated_ids           TEXT,
    idempotency_key           TEXT UNIQUE,
    nexus_consumed_epoch_id   TEXT,
    content_consumed_epoch_id TEXT,
    created_at                TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recon_nexus_unconsumed ON recon_buffer(nexus_consumed_epoch_id) WHERE nexus_consumed_epoch_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_recon_content_unconsumed ON recon_buffer(content_consumed_epoch_id) WHERE content_consumed_epoch_id IS NULL;

CREATE TABLE IF NOT EXISTS epochs (
    id               TEXT PRIMARY KEY,
    vault_id         TEXT NOT NULL DEFAULT 'default',
    status           TEXT NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'full',
    trigger          TEXT NOT NULL DEFAULT 'manual',
    seal_timestamp   TEXT NOT NULL,
    lease_acquired   TEXT NOT NULL,
    lease_expires    TEXT NOT NULL,
    llm_base_url     TEXT,
    llm_model        TEXT,
    stats            TEXT,
    started_at       TEXT,
    committed_at     TEXT,
    error            TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_epoch_active ON epochs(vault_id) WHERE status IN ('leased', 'running');

CREATE TABLE IF NOT EXISTS cognitive_debt (
    id                 TEXT PRIMARY KEY,
    type               TEXT NOT NULL,
    raw_ref            TEXT NOT NULL,
    priority           REAL DEFAULT 0.5,
    accumulated_epochs INTEGER DEFAULT 0,
    created_at         TEXT NOT NULL,
    resolved_at        TEXT
);

CREATE TABLE IF NOT EXISTS view_engrams (
    id            TEXT PRIMARY KEY,
    content       TEXT NOT NULL,
    type          TEXT,
    tags          TEXT,
    state         TEXT NOT NULL,
    strength      REAL NOT NULL,
    importance    TEXT,
    origin        TEXT,
    verified      INTEGER,
    rigidity      REAL,
    access_count  INTEGER,
    created_at    TEXT,
    last_accessed TEXT,
    content_hash  TEXT,
    embedding     BLOB,
    embedding_dim INTEGER
);

CREATE TABLE IF NOT EXISTS view_nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    target_id            TEXT NOT NULL,
    direction            TEXT,
    type                 TEXT NOT NULL,
    association_strength REAL
);

CREATE TABLE IF NOT EXISTS view_pointer (
    id           TEXT PRIMARY KEY DEFAULT 'current',
    epoch_id     TEXT,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_cursors (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_forget (
    id           TEXT PRIMARY KEY,
    target_table TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    UNIQUE(target_table, target_id)
);
"""


def migrate_v03_to_v05(conn: sqlite3.Connection) -> None:
    """Migrate a v0.3 database to v0.5 schema in-place."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 5:
        return  # Already migrated

    now = datetime.now(timezone.utc).isoformat()

    # Add new columns to engrams
    _ensure_column(conn, "engrams", "state", "TEXT DEFAULT 'consolidated'")
    _ensure_column(conn, "engrams", "rigidity", "REAL DEFAULT 0.5")
    _ensure_column(conn, "engrams", "content_hash", "TEXT")
    _ensure_column(conn, "engrams", "last_state_changed_epoch_id", "TEXT")

    # Create indexes on new columns
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_engrams_state ON engrams(state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_engrams_content_hash ON engrams(content_hash)"
    )

    # Create all new tables
    conn.executescript(_NEW_TABLES_SQL)

    # Migrate state from forgotten flag
    conn.execute("UPDATE engrams SET state = 'forgotten' WHERE forgotten = 1")
    conn.execute("UPDATE engrams SET state = 'consolidated' WHERE forgotten = 0")

    # Set rigidity by type
    for engram_type, rigidity in RIGIDITY_DEFAULTS.items():
        conn.execute(
            "UPDATE engrams SET rigidity = ? WHERE type = ?",
            (rigidity, engram_type),
        )

    # Backfill content_hash
    rows = conn.execute("SELECT id, content FROM engrams").fetchall()
    for row in rows:
        content_hash = hashlib.sha256(row[1].encode()).hexdigest()
        conn.execute(
            "UPDATE engrams SET content_hash = ? WHERE id = ?",
            (content_hash, row[0]),
        )

    # Populate view_engrams from consolidated engrams
    conn.execute("DELETE FROM view_engrams")
    conn.execute("""
        INSERT INTO view_engrams
            (id, content, type, tags, state, strength, importance, origin,
             verified, rigidity, access_count, created_at, last_accessed,
             content_hash, embedding, embedding_dim)
        SELECT
            id, content, type, tags, state, strength, importance, origin,
            verified, rigidity, access_count, created_at, last_accessed,
            content_hash, embedding, embedding_dim
        FROM engrams WHERE state = 'consolidated'
    """)

    # Initialize view_pointer
    conn.execute(
        "INSERT OR REPLACE INTO view_pointer (id, epoch_id, refreshed_at) "
        "VALUES ('current', NULL, ?)",
        (now,),
    )

    # Initialize runtime_cursors
    conn.execute(
        "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) "
        "VALUES ('decay_watermark', ?, ?)",
        (now, now),
    )

    conn.execute("PRAGMA user_version = 5")
    conn.commit()


def migrate_v05_to_v092(conn: sqlite3.Connection) -> None:
    """v0.5 → v0.9.2 schema migration. Adds temporal lifecycle to nexus."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 92:
        return

    # 1. nexus: add invalidated_at
    _ensure_column(conn, "nexus", "invalidated_at", "TEXT")

    # 2. view_nexus: add invalidated_at
    _ensure_column(conn, "view_nexus", "invalidated_at", "TEXT")

    conn.execute("PRAGMA user_version = 92")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Add column if it doesn't exist."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
