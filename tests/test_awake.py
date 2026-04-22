"""Tests for awake track — fast read/write path in Worker DB thread."""
import sqlite3
import json
import uuid
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
    # Insert some engrams for recall/verify/pin tests
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
    conn.execute("PRAGMA user_version = 3")
    conn.commit()

    from memento.migration import migrate_v03_to_v05
    migrate_v03_to_v05(conn)

    conn.row_factory = sqlite3.Row
    return conn


# ── awake_capture ──────────────────────────────────────────


def test_capture_writes_capture_log_not_engrams():
    conn = _make_v05_db()
    from memento.awake import awake_capture

    engram_count_before = conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]

    with patch("memento.awake.get_embedding", return_value=(b"\x00" * 16, 4, False)):
        result = awake_capture(conn, "new memory content", type="fact", tags=["redis", "cache"])

    assert result["state"] == "buffered"
    assert "capture_log_id" in result

    # capture_log should have the row
    row = conn.execute("SELECT * FROM capture_log WHERE id=?", (result["capture_log_id"],)).fetchone()
    assert row is not None
    assert row["content"] == "new memory content"
    assert row["epoch_id"] is None
    assert row["embedding_pending"] == 0

    # engrams should NOT have a new row
    engram_count_after = conn.execute("SELECT COUNT(*) FROM engrams").fetchone()[0]
    assert engram_count_after == engram_count_before


def test_capture_tags_list_serialized():
    conn = _make_v05_db()
    from memento.awake import awake_capture

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        result = awake_capture(conn, "tagged memory", tags=["a", "b"])

    row = conn.execute("SELECT tags FROM capture_log WHERE id=?", (result["capture_log_id"],)).fetchone()
    assert row["tags"] == json.dumps(["a", "b"])


def test_capture_tags_string_kept():
    conn = _make_v05_db()
    from memento.awake import awake_capture

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        result = awake_capture(conn, "tagged memory", tags="a,b")

    row = conn.execute("SELECT tags FROM capture_log WHERE id=?", (result["capture_log_id"],)).fetchone()
    assert row["tags"] == "a,b"


def test_capture_embedding_pending_on_failure():
    conn = _make_v05_db()
    from memento.awake import awake_capture

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        result = awake_capture(conn, "no embedding")

    row = conn.execute(
        "SELECT embedding_pending, embedding FROM capture_log WHERE id=?",
        (result["capture_log_id"],),
    ).fetchone()
    assert row["embedding_pending"] == 1
    assert row["embedding"] is None


def test_capture_content_hash():
    conn = _make_v05_db()
    from memento.awake import awake_capture
    import hashlib

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        result = awake_capture(conn, "  Hello World  ")

    row = conn.execute(
        "SELECT content_hash FROM capture_log WHERE id=?",
        (result["capture_log_id"],),
    ).fetchone()
    expected = hashlib.sha256("hello world".encode()).hexdigest()
    assert row["content_hash"] == expected


# ── awake_recall ───────────────────────────────────────────


def test_recall_dual_source_with_provisional():
    conn = _make_v05_db()
    from memento.awake import awake_capture, awake_recall

    # Add a hot buffer entry matching "Redis"
    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        awake_capture(conn, "Redis sentinel setup", type="fact")

    results = awake_recall(conn, "Redis")

    # Should find both view_engrams hit and capture_log hit
    assert len(results) >= 2

    view_hit = [r for r in results if not r["provisional"]]
    buffer_hit = [r for r in results if r["provisional"]]
    assert len(view_hit) >= 1
    assert len(buffer_hit) >= 1

    # Buffer hit score should be downweighted
    for bh in buffer_hit:
        assert bh["score"] <= 0.5  # capture_log default strength * 0.5


def test_recall_pulse_event_for_view_hits():
    conn = _make_v05_db()
    from memento.awake import awake_recall

    pulse_queue = Queue()
    results = awake_recall(conn, "Redis", pulse_queue=pulse_queue)

    # Should have a PulseEvent for the view_engrams hit
    assert not pulse_queue.empty()
    event = pulse_queue.get()
    assert event["event_type"] == "recall_hit"
    assert event["engram_id"] == "e1"
    assert "idempotency_key" in event


def test_recall_no_pulse_for_buffer_hits():
    conn = _make_v05_db()
    from memento.awake import awake_capture, awake_recall

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        awake_capture(conn, "unique_buffer_only_content")

    pulse_queue = Queue()
    results = awake_recall(conn, "unique_buffer_only_content", pulse_queue=pulse_queue)

    # Only buffer hits, no pulse events
    assert all(r["provisional"] for r in results)
    assert pulse_queue.empty()


def test_recall_max_results():
    conn = _make_v05_db()
    from memento.awake import awake_recall

    results = awake_recall(conn, "mode", max_results=1)
    assert len(results) <= 1


def test_recall_returns_staleness_and_extended_fields():
    """Recall results must include staleness_level, tags, and origin."""
    conn = _make_v05_db()
    from memento.awake import awake_recall

    results = awake_recall(conn, "Redis")
    assert len(results) > 0

    for r in results:
        assert "staleness_level" in r
        assert r["staleness_level"] in ("fresh", "stale", "very_stale")
        assert "tags" in r
        assert "origin" in r


def test_recall_like_fallback_when_vec_unavailable():
    """When VEC_AVAILABLE=False and no FTS, LIKE fallback still returns results."""
    conn = _make_v05_db()
    from memento.awake import awake_recall

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        with patch("memento.db.VEC_AVAILABLE", False):
            results = awake_recall(conn, "Redis")

    assert len(results) > 0
    assert any("Redis" in r["content"] for r in results)
    # All results should still have staleness_level
    for r in results:
        assert r["staleness_level"] in ("fresh", "stale", "very_stale")


def test_recall_fallback_vec_unavailable():
    """VEC_AVAILABLE=False: should skip vector, fall through to FTS/LIKE."""
    conn = _make_v05_db()
    from memento.awake import awake_recall

    with patch("memento.awake.get_embedding", return_value=(b"\x00" * 16, 4, False)):
        with patch("memento.db.VEC_AVAILABLE", False):
            results = awake_recall(conn, "Redis")

    assert len(results) > 0
    assert any("Redis" in r["content"] for r in results)
    for r in results:
        assert "staleness_level" in r


def test_recall_fallback_embedding_unavailable():
    """Embedding returns None/pending: should skip vector, use FTS/LIKE."""
    conn = _make_v05_db()
    from memento.awake import awake_recall

    # get_embedding returns (None, 0, True) — pending/unavailable
    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        results = awake_recall(conn, "Redis")

    assert len(results) > 0
    assert any("Redis" in r["content"] for r in results)


def test_recall_fallback_fts_exception():
    """FTS MATCH raises exception: should fall through to LIKE."""
    conn = _make_v05_db()
    from memento.awake import awake_recall

    # Drop engrams_fts to force FTS path to fail, exercising the except branch
    conn.execute("DROP TABLE IF EXISTS engrams_fts")
    conn.commit()

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        results = awake_recall(conn, "Redis")

    # Should still find via LIKE fallback
    assert len(results) > 0
    assert any("Redis" in r["content"] for r in results)


def test_recall_buffer_hits_always_fresh():
    """Capture_log (provisional) hits should always have staleness_level='fresh'."""
    conn = _make_v05_db()
    from memento.awake import awake_capture, awake_recall

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        awake_capture(conn, "unique_fresh_test_content")
        results = awake_recall(conn, "unique_fresh_test_content")

    buffer_hits = [r for r in results if r["provisional"]]
    assert len(buffer_hits) > 0
    for r in buffer_hits:
        assert r["staleness_level"] == "fresh"


# ── awake_forget ───────────────────────────────────────────


def test_forget_capture_log_target():
    conn = _make_v05_db()
    from memento.awake import awake_capture, awake_forget

    with patch("memento.awake.get_embedding", return_value=(None, 0, True)):
        cap = awake_capture(conn, "to be forgotten")

    result = awake_forget(conn, cap["capture_log_id"])
    assert result["status"] == "pending"

    pf = conn.execute(
        "SELECT target_table, target_id FROM pending_forget WHERE target_id=?",
        (cap["capture_log_id"],),
    ).fetchone()
    assert pf["target_table"] == "capture_log"


def test_forget_engram_target():
    conn = _make_v05_db()
    from memento.awake import awake_forget

    result = awake_forget(conn, "e1")
    assert result["status"] == "pending"

    pf = conn.execute(
        "SELECT target_table FROM pending_forget WHERE target_id=?",
        ("e1",),
    ).fetchone()
    assert pf["target_table"] == "engrams"


# ── awake_verify ───────────────────────────────────────────


def test_verify_updates_both_tables():
    conn = _make_v05_db()
    from memento.awake import awake_verify

    result = awake_verify(conn, "e1")
    assert result["status"] == "verified"

    engram = conn.execute("SELECT verified FROM engrams WHERE id='e1'").fetchone()
    assert engram["verified"] == 1

    view = conn.execute("SELECT verified FROM view_engrams WHERE id='e1'").fetchone()
    assert view["verified"] == 1


# ── awake_pin ──────────────────────────────────────────────


def test_pin_updates_both_tables():
    conn = _make_v05_db()
    from memento.awake import awake_pin

    result = awake_pin(conn, "e1", 0.8)
    assert result["status"] == "pinned"
    assert result["rigidity"] == 0.8

    engram = conn.execute("SELECT rigidity FROM engrams WHERE id='e1'").fetchone()
    assert engram["rigidity"] == pytest.approx(0.8)

    view = conn.execute("SELECT rigidity FROM view_engrams WHERE id='e1'").fetchone()
    assert view["rigidity"] == pytest.approx(0.8)


def test_pin_clamps_value():
    conn = _make_v05_db()
    from memento.awake import awake_pin

    result_high = awake_pin(conn, "e1", 1.5)
    assert result_high["rigidity"] == 1.0

    result_low = awake_pin(conn, "e1", -0.3)
    assert result_low["rigidity"] == 0.0
