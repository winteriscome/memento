"""Shared test fixtures for Memento test suite."""

import struct
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def db_path(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def mock_embedding():
    """Mock embedding across all modules that call get_embedding.

    Returns a fixed 4-dimensional embedding blob.
    Patches: memento.core, memento.observation, memento.awake.
    """
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2, \
         patch("memento.awake.get_embedding") as m3:
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)
        m3.return_value = (fake_blob, 4, False)
        yield


@pytest.fixture
def v05_db(tmp_path, mock_embedding):
    """Create a fully migrated v0.5 database.

    Returns (db_path, conn) tuple. Connection has WAL mode and foreign keys enabled.
    """
    import sqlite3
    from memento.migration import migrate_v03_to_v05

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Create v0.3 schema
    conn.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY, content TEXT NOT NULL,
            type TEXT DEFAULT 'fact', tags TEXT,
            strength REAL DEFAULT 0.7, importance TEXT DEFAULT 'normal',
            source TEXT, origin TEXT DEFAULT 'human',
            verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 0, forgotten INTEGER DEFAULT 0,
            embedding_pending INTEGER DEFAULT 0, embedding_dim INTEGER,
            embedding BLOB, source_session_id TEXT, source_event_id TEXT
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
    conn.execute("PRAGMA user_version = 3")
    conn.commit()

    migrate_v03_to_v05(conn)
    conn.commit()

    yield db_path, conn
    conn.close()
