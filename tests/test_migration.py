"""Tests for v0.3→v0.5 database migration."""
import sqlite3
import hashlib
from pathlib import Path
import pytest


def _create_v03_db(db_path):
    """Create a v0.3-style database with test data."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # v0.3 schema
    conn.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'fact',
            tags TEXT,
            strength REAL DEFAULT 0.7,
            importance TEXT DEFAULT 'normal',
            source TEXT,
            origin TEXT DEFAULT 'human',
            verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0,
            forgotten INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0,
            embedding_dim INTEGER,
            embedding BLOB,
            source_session_id TEXT,
            source_event_id TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_engrams_forgotten ON engrams(forgotten)")
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, project TEXT, task TEXT,
            status TEXT DEFAULT 'active', started_at TEXT NOT NULL,
            ended_at TEXT, summary TEXT, metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE session_events (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            event_type TEXT NOT NULL, payload TEXT,
            fingerprint TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    # Insert test data
    now = "2026-04-01T12:00:00"
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "Redis cache config", "fact", 0.8, "normal", "human", now, now, 0),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e2", "User prefers dark mode", "preference", 0.9, "critical", "human", now, now, 0),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e3", "Old deleted memory", "debugging", 0.1, "low", "agent", now, now, 1),
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    return conn


def test_migration_sets_state_from_forgotten(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # Active engrams → consolidated
    row = conn.execute("SELECT state FROM engrams WHERE id='e1'").fetchone()
    assert row["state"] == "consolidated"

    # Forgotten engrams → forgotten state
    row = conn.execute("SELECT state FROM engrams WHERE id='e3'").fetchone()
    assert row["state"] == "forgotten"


def test_migration_sets_rigidity_by_type(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # fact → 0.5
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e1'").fetchone()
    assert row["rigidity"] == pytest.approx(0.5)

    # preference → 0.7
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e2'").fetchone()
    assert row["rigidity"] == pytest.approx(0.7)

    # debugging → 0.15
    row = conn.execute("SELECT rigidity FROM engrams WHERE id='e3'").fetchone()
    assert row["rigidity"] == pytest.approx(0.15)


def test_migration_fills_content_hash(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    row = conn.execute("SELECT content_hash FROM engrams WHERE id='e1'").fetchone()
    expected = hashlib.sha256("Redis cache config".encode()).hexdigest()
    assert row["content_hash"] == expected


def test_migration_creates_new_tables(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    expected_tables = {
        "capture_log", "nexus", "delta_ledger", "recon_buffer",
        "epochs", "cognitive_debt", "view_engrams", "view_nexus",
        "view_pointer", "runtime_cursors", "pending_forget",
    }
    assert expected_tables.issubset(tables)


def test_migration_populates_view_store(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    migrate_v03_to_v05(conn)

    # Only consolidated engrams in view_engrams
    rows = conn.execute("SELECT id FROM view_engrams").fetchall()
    ids = {r["id"] for r in rows}
    assert ids == {"e1", "e2"}  # e3 is forgotten, not in view

    # view_pointer initialized
    vp = conn.execute("SELECT * FROM view_pointer WHERE id='current'").fetchone()
    assert vp is not None
    assert vp["epoch_id"] is None


def test_migration_sets_user_version(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 5


def test_migration_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    conn = _create_v03_db(db_path)
    conn.close()

    from memento.migration import migrate_v03_to_v05

    conn = sqlite3.connect(str(db_path))
    migrate_v03_to_v05(conn)
    # Running again should be a no-op
    migrate_v03_to_v05(conn)

    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 5
