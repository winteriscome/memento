"""Tests for subconscious track — background thread consuming PulseEvents."""
import sqlite3
import uuid
from datetime import datetime, timezone
from queue import Queue
from unittest.mock import patch

import pytest


def _make_v05_db():
    """Create an in-memory v0.5 database for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Minimal v0.3 tables
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
    # Insert test engrams
    now = "2026-04-01T12:00:00+00:00"
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, access_count, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", "Redis cache config", "fact", 0.8, "normal", "human", now, now, 2, 0),
    )
    conn.execute(
        "INSERT INTO engrams (id, content, type, strength, importance, origin, "
        "created_at, last_accessed, access_count, forgotten) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e2", "User prefers dark mode", "preference", 0.9, "critical", "human", now, now, 5, 0),
    )
    conn.execute("PRAGMA user_version = 3")
    conn.commit()

    from memento.migration import migrate_v03_to_v05, migrate_v05_to_v092
    migrate_v03_to_v05(conn)
    migrate_v05_to_v092(conn)

    conn.row_factory = sqlite3.Row
    return conn


# ── drain_pulse_events ────────────────────────────────────────


def test_drain_pulse_events_creates_delta_and_recon():
    conn = _make_v05_db()
    from memento.repository import rebuild_view_store

    # Rebuild view_engrams so e1 and e2 are visible
    rebuild_view_store(conn, epoch_id="epoch-test")

    pulse_queue = Queue()
    pulse_queue.put({
        "event_type": "recall_hit",
        "engram_id": "e1",
        "query_context": "redis config",
        "coactivated_ids": [],
        "timestamp": "2026-04-01T12:05:00+00:00",
        "idempotency_key": str(uuid.uuid4()),
    })

    from memento.subconscious import SubconsciousTrack

    # Create a conn_factory
    def conn_factory():
        # Return a new connection to the same in-memory db is not possible,
        # so we'll just pass the existing conn directly in tests
        return conn

    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})

    # Call _drain_pulse_events directly (no background thread)
    track._drain_pulse_events(conn)

    # Check delta_ledger has a reinforce entry
    delta = conn.execute(
        "SELECT * FROM delta_ledger WHERE engram_id='e1' AND delta_type='reinforce'"
    ).fetchone()
    assert delta is not None
    assert delta["delta_value"] > 0.0

    # Check recon_buffer has an entry
    recon = conn.execute("SELECT * FROM recon_buffer WHERE engram_id='e1'").fetchone()
    assert recon is not None
    assert recon["query_context"] == "redis config"


def test_drain_pulse_events_idempotency():
    conn = _make_v05_db()
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    idempotency_key = str(uuid.uuid4())
    pulse_queue = Queue()

    # Put the same event twice (same idempotency_key)
    for _ in range(2):
        pulse_queue.put({
            "event_type": "recall_hit",
            "engram_id": "e1",
            "query_context": "redis config",
            "coactivated_ids": [],
            "timestamp": "2026-04-01T12:05:00+00:00",
            "idempotency_key": idempotency_key,
        })

    from memento.subconscious import SubconsciousTrack

    def conn_factory():
        return conn

    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})
    track._drain_pulse_events(conn)

    delta_count = conn.execute(
        "SELECT COUNT(*) FROM delta_ledger WHERE engram_id='e1'"
    ).fetchone()[0]
    assert delta_count == 1

    # recon_buffer should have 1 entry (idempotency_key UNIQUE)
    recon_count = conn.execute(
        "SELECT COUNT(*) FROM recon_buffer WHERE engram_id='e1'"
    ).fetchone()[0]
    assert recon_count == 1


def test_drain_pulse_events_multiple_events():
    conn = _make_v05_db()
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    pulse_queue = Queue()
    pulse_queue.put({
        "event_type": "recall_hit",
        "engram_id": "e1",
        "query_context": "redis",
        "coactivated_ids": ["e2"],
        "timestamp": "2026-04-01T12:05:00+00:00",
        "idempotency_key": str(uuid.uuid4()),
    })
    pulse_queue.put({
        "event_type": "recall_hit",
        "engram_id": "e2",
        "query_context": "dark mode",
        "coactivated_ids": ["e1"],
        "timestamp": "2026-04-01T12:06:00+00:00",
        "idempotency_key": str(uuid.uuid4()),
    })

    from memento.subconscious import SubconsciousTrack

    def conn_factory():
        return conn

    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})
    track._drain_pulse_events(conn)

    # Should have deltas for both e1 and e2
    e1_delta = conn.execute(
        "SELECT * FROM delta_ledger WHERE engram_id='e1'"
    ).fetchone()
    assert e1_delta is not None

    e2_delta = conn.execute(
        "SELECT * FROM delta_ledger WHERE engram_id='e2'"
    ).fetchone()
    assert e2_delta is not None

    # Should have recon_buffer entries for both
    e1_recon = conn.execute(
        "SELECT * FROM recon_buffer WHERE engram_id='e1'"
    ).fetchone()
    assert e1_recon is not None

    e2_recon = conn.execute(
        "SELECT * FROM recon_buffer WHERE engram_id='e2'"
    ).fetchone()
    assert e2_recon is not None


def test_drain_pulse_events_skip_missing_engram():
    """Test that we skip PulseEvents for engrams not in view_engrams."""
    conn = _make_v05_db()
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    pulse_queue = Queue()
    pulse_queue.put({
        "event_type": "recall_hit",
        "engram_id": "non_existent",
        "query_context": "missing",
        "coactivated_ids": [],
        "timestamp": "2026-04-01T12:05:00+00:00",
        "idempotency_key": str(uuid.uuid4()),
    })

    from memento.subconscious import SubconsciousTrack

    def conn_factory():
        return conn

    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})

    # Should not raise an error, just skip
    track._drain_pulse_events(conn)

    # delta_ledger should be empty
    delta_count = conn.execute("SELECT COUNT(*) FROM delta_ledger").fetchone()[0]
    assert delta_count == 0

    # recon_buffer should be empty
    recon_count = conn.execute("SELECT COUNT(*) FROM recon_buffer").fetchone()[0]
    assert recon_count == 0


# ── run_decay_cycle ───────────────────────────────────────────


def test_run_decay_cycle_creates_deltas():
    conn = _make_v05_db()

    # Move last_accessed back 48 hours so decay is large enough
    # to exceed MIN_DECAY_DELTA even with rigidity
    conn.execute(
        "UPDATE engrams SET last_accessed = '2026-03-30T12:00:00+00:00'"
    )
    conn.commit()

    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    # Set decay_watermark to 24 hours ago
    watermark = "2026-03-31T12:00:00+00:00"
    conn.execute(
        "UPDATE runtime_cursors SET value=? WHERE key='decay_watermark'",
        (watermark,),
    )
    conn.commit()

    from memento.subconscious import SubconsciousTrack

    def conn_factory():
        return conn

    pulse_queue = Queue()
    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})

    # Call _run_decay_cycle with a fixed timestamp (48h after last_accessed)
    with patch("memento.subconscious.datetime") as mock_dt:
        from datetime import datetime, timezone
        mock_dt.now.return_value = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat

        track._run_decay_cycle(conn)

    # Should have decay deltas for active engrams
    decay_deltas = conn.execute(
        "SELECT * FROM delta_ledger WHERE delta_type='decay'"
    ).fetchall()
    assert len(decay_deltas) > 0

    # delta_value should be negative (decay)
    for delta in decay_deltas:
        assert delta["delta_value"] < 0.0

    # decay_watermark should be updated
    new_watermark = conn.execute(
        "SELECT value FROM runtime_cursors WHERE key='decay_watermark'"
    ).fetchone()[0]
    assert new_watermark == "2026-04-01T12:00:00+00:00"


def test_run_decay_cycle_respects_min_delta():
    """Test that decay cycle only creates deltas above MIN_DECAY_DELTA."""
    conn = _make_v05_db()
    from memento.repository import rebuild_view_store
    rebuild_view_store(conn, epoch_id="epoch-test")

    # Set decay_watermark to 1 second ago (very small decay)
    watermark = "2026-04-01T11:59:59+00:00"
    conn.execute(
        "UPDATE runtime_cursors SET value=? WHERE key='decay_watermark'",
        (watermark,),
    )
    conn.commit()

    from memento.subconscious import SubconsciousTrack

    def conn_factory():
        return conn

    pulse_queue = Queue()
    track = SubconsciousTrack(conn_factory, pulse_queue, config={"decay_interval": 300})

    with patch("memento.subconscious.datetime") as mock_dt:
        from datetime import datetime, timezone
        mock_dt.now.return_value = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.fromisoformat = datetime.fromisoformat

        track._run_decay_cycle(conn)

    # Should have no deltas (below MIN_DECAY_DELTA threshold)
    decay_count = conn.execute(
        "SELECT COUNT(*) FROM delta_ledger WHERE delta_type='decay'"
    ).fetchone()[0]
    assert decay_count == 0



def _insert_recon(conn, engram_id, nexus_consumed=None, content_consumed=None, created_at="2026-04-01T00:00:00+00:00"):
    conn.execute(
        "INSERT INTO recon_buffer (engram_id, query_context, coactivated_ids, idempotency_key, "
        "created_at, nexus_consumed_epoch_id, content_consumed_epoch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (engram_id, "ctx", "[]", str(uuid.uuid4()),
         created_at, nexus_consumed, content_consumed),
    )
    conn.commit()


def test_clean_recon_buffer_deletes_fully_consumed_old_entries():
    conn = _make_v05_db()
    old_ts = "2026-01-01T00:00:00+00:00"
    _insert_recon(conn, "e1", nexus_consumed="epoch-1", content_consumed="epoch-2", created_at=old_ts)

    from memento.subconscious import SubconsciousTrack
    track = SubconsciousTrack(lambda: conn, Queue(), {})
    track._clean_recon_buffer(conn)

    count = conn.execute("SELECT COUNT(*) FROM recon_buffer").fetchone()[0]
    assert count == 0


def test_clean_recon_buffer_keeps_partially_consumed():
    conn = _make_v05_db()
    old_ts = "2026-01-01T00:00:00+00:00"
    _insert_recon(conn, "e1", nexus_consumed="epoch-1", content_consumed=None, created_at=old_ts)

    from memento.subconscious import SubconsciousTrack
    track = SubconsciousTrack(lambda: conn, Queue(), {})
    track._clean_recon_buffer(conn)

    count = conn.execute("SELECT COUNT(*) FROM recon_buffer").fetchone()[0]
    assert count == 1


def test_clean_recon_buffer_keeps_recent_fully_consumed():
    conn = _make_v05_db()
    recent_ts = datetime.now(timezone.utc).isoformat()
    _insert_recon(conn, "e1", nexus_consumed="epoch-1", content_consumed="epoch-2", created_at=recent_ts)

    from memento.subconscious import SubconsciousTrack
    track = SubconsciousTrack(lambda: conn, Queue(), {})
    track._clean_recon_buffer(conn)

    count = conn.execute("SELECT COUNT(*) FROM recon_buffer").fetchone()[0]
    assert count == 1
