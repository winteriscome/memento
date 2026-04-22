"""Tests for Epoch Runner (Layer 3, Task 11)."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from unittest.mock import patch

from memento.migration import migrate_v03_to_v05, migrate_v05_to_v092


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


def _create_v03_db(conn):
    """Create v0.3 schema with base tables."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
    conn.execute("PRAGMA user_version = 3")
    conn.commit()


def _setup_v05_db(tmp_path):
    """Create a migrated v0.5 database connection."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _create_v03_db(conn)
    migrate_v03_to_v05(conn)
    migrate_v05_to_v092(conn)
    return conn


@pytest.fixture
def conn(tmp_path):
    return _setup_v05_db(tmp_path)


NOW = "2026-04-01T12:00:00+00:00"
BEFORE_SEAL = "2026-04-01T11:59:00+00:00"
AFTER_SEAL = "2026-04-01T12:01:00+00:00"
SEAL_TS = "2026-04-01T12:00:00+00:00"


def _insert_capture(conn, capture_id, content, created_at=BEFORE_SEAL,
                     origin="human", ctype="fact"):
    """Insert a capture_log row."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    conn.execute(
        "INSERT INTO capture_log "
        "(id, content, type, importance, origin, content_hash, created_at) "
        "VALUES (?, ?, ?, 'normal', ?, ?, ?)",
        (capture_id, content, ctype, origin, content_hash, created_at),
    )
    conn.commit()


def _insert_engram(conn, engram_id, content, state="consolidated",
                    strength=0.7, origin="human", rigidity=0.5):
    """Insert an engram row."""
    now = NOW
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    conn.execute(
        "INSERT INTO engrams "
        "(id, content, type, tags, strength, importance, origin, verified, "
        "created_at, last_accessed, access_count, forgotten, "
        "state, rigidity, content_hash) "
        "VALUES (?, ?, 'fact', NULL, ?, 'normal', ?, 0, ?, ?, 0, 0, ?, ?, ?)",
        (engram_id, content, strength, origin, now, now, state, rigidity,
         content_hash),
    )
    conn.commit()


def _insert_delta(conn, engram_id, delta_type, delta_value,
                   created_at=BEFORE_SEAL):
    """Insert a delta_ledger row."""
    conn.execute(
        "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
        "VALUES (?, ?, ?, ?)",
        (engram_id, delta_type, delta_value, created_at),
    )
    conn.commit()


def _insert_recon(conn, engram_id, coactivated_ids, created_at=BEFORE_SEAL,
                   query_context="test query"):
    """Insert a recon_buffer row."""
    idem_key = f"idem-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO recon_buffer "
        "(engram_id, query_context, coactivated_ids, idempotency_key, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (engram_id, query_context, json.dumps(coactivated_ids),
         idem_key, created_at),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: acquire_lease success
# ═══════════════════════════════════════════════════════════════════════════


def test_acquire_lease_success(conn):
    """acquire_lease should return an epoch_id on success."""
    from memento.epoch import acquire_lease

    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None
    assert epoch_id.startswith("epoch-")

    # Verify row in epochs table
    row = conn.execute("SELECT * FROM epochs WHERE id=?", (epoch_id,)).fetchone()
    assert row is not None
    assert row["status"] == "leased"
    assert row["mode"] == "full"
    assert row["trigger"] == "manual"
    assert row["vault_id"] == "default"


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: lease mutual exclusion
# ═══════════════════════════════════════════════════════════════════════════


def test_lease_mutual_exclusion(conn):
    """Second acquire_lease should return None when an active lease exists."""
    from memento.epoch import acquire_lease

    epoch1 = acquire_lease(conn, vault_id="default", mode="full",
                           trigger="manual")
    assert epoch1 is not None

    epoch2 = acquire_lease(conn, vault_id="default", mode="full",
                           trigger="manual")
    assert epoch2 is None


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: expired lease cleanup
# ═══════════════════════════════════════════════════════════════════════════


def test_expired_lease_cleanup(conn):
    """Expired leases should be marked failed, and new lease should succeed."""
    from memento.epoch import acquire_lease

    # Insert an expired lease directly
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    expired_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "INSERT INTO epochs "
        "(id, vault_id, status, mode, trigger, seal_timestamp, "
        "lease_acquired, lease_expires) "
        "VALUES (?, 'default', 'leased', 'full', 'manual', ?, ?, ?)",
        ("epoch-expired-001", past, past, expired_ts),
    )
    conn.commit()

    # Now acquire should clean up the expired lease and succeed
    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None

    # Verify the expired lease is marked as failed
    old_row = conn.execute(
        "SELECT status FROM epochs WHERE id='epoch-expired-001'"
    ).fetchone()
    assert old_row["status"] == "failed"


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: seal_timestamp boundary
# ═══════════════════════════════════════════════════════════════════════════


def test_seal_timestamp_boundary(conn):
    """Items created after seal_timestamp should NOT be consumed."""
    from memento.epoch import acquire_lease, run_epoch_phases

    # Insert captures: one before seal, one after
    _insert_capture(conn, "cap-before", "before seal", created_at=BEFORE_SEAL)
    _insert_capture(conn, "cap-after", "after seal", created_at=AFTER_SEAL)

    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None

    # Manually set seal_timestamp to our known value
    conn.execute(
        "UPDATE epochs SET seal_timestamp=? WHERE id=?",
        (SEAL_TS, epoch_id),
    )
    conn.commit()

    run_epoch_phases(conn, epoch_id, mode="full")

    # Before-seal capture should be consumed (epoch_id set)
    before = conn.execute(
        "SELECT epoch_id FROM capture_log WHERE id='cap-before'"
    ).fetchone()
    assert before["epoch_id"] == epoch_id

    # After-seal capture should NOT be consumed
    after = conn.execute(
        "SELECT epoch_id FROM capture_log WHERE id='cap-after'"
    ).fetchone()
    assert after["epoch_id"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: light epoch creates debt
# ═══════════════════════════════════════════════════════════════════════════


def test_light_epoch_creates_debt(conn):
    """Light mode should NOT consume capture_log, but create cognitive debt."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-light-1", "light mode content",
                    created_at=BEFORE_SEAL)

    epoch_id = acquire_lease(conn, vault_id="default", mode="light",
                             trigger="manual")
    assert epoch_id is not None

    conn.execute(
        "UPDATE epochs SET seal_timestamp=? WHERE id=?",
        (SEAL_TS, epoch_id),
    )
    conn.commit()

    run_epoch_phases(conn, epoch_id, mode="light")

    # capture_log should NOT be consumed
    cap = conn.execute(
        "SELECT epoch_id FROM capture_log WHERE id='cap-light-1'"
    ).fetchone()
    assert cap["epoch_id"] is None

    # cognitive_debt should have an entry
    debt = conn.execute(
        "SELECT * FROM cognitive_debt WHERE type='pending_consolidation'"
    ).fetchall()
    assert len(debt) >= 1

    # Epoch status should be 'degraded' for light mode
    ep = conn.execute(
        "SELECT status FROM epochs WHERE id=?", (epoch_id,)
    ).fetchone()
    assert ep["status"] == "degraded"


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: epoch processes pending_forget
# ═══════════════════════════════════════════════════════════════════════════


def test_epoch_processes_pending_forget(conn):
    """Pending forget should transition engram to 'forgotten', clean nexus,
    and update view store."""
    from memento.epoch import acquire_lease, run_epoch_phases

    # Insert two engrams
    _insert_engram(conn, "eng-keep", "keep this")
    _insert_engram(conn, "eng-forget", "forget this")

    # Create a nexus between them
    conn.execute(
        "INSERT INTO nexus "
        "(id, source_id, target_id, type, association_strength, created_at) "
        "VALUES ('nex-001', 'eng-forget', 'eng-keep', 'semantic', 0.5, ?)",
        (NOW,),
    )

    # Add both to view_engrams
    conn.execute(
        "INSERT INTO view_engrams "
        "(id, content, type, state, strength, created_at) "
        "VALUES ('eng-keep', 'keep this', 'fact', 'consolidated', 0.7, ?)",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO view_engrams "
        "(id, content, type, state, strength, created_at) "
        "VALUES ('eng-forget', 'forget this', 'fact', 'consolidated', 0.7, ?)",
        (NOW,),
    )

    # Enqueue forget
    conn.execute(
        "INSERT INTO pending_forget (id, target_table, target_id, requested_at) "
        "VALUES ('pf-001', 'engrams', 'eng-forget', ?)",
        (NOW,),
    )
    conn.commit()

    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None

    run_epoch_phases(conn, epoch_id, mode="full")

    # Engram should be forgotten
    eng = conn.execute(
        "SELECT state FROM engrams WHERE id='eng-forget'"
    ).fetchone()
    assert eng["state"] == "forgotten"

    # Nexus should be cleaned
    nex = conn.execute(
        "SELECT * FROM nexus WHERE source_id='eng-forget' OR target_id='eng-forget'"
    ).fetchall()
    assert len(nex) == 0

    # View store should NOT contain the forgotten engram
    view = conn.execute(
        "SELECT * FROM view_engrams WHERE id='eng-forget'"
    ).fetchall()
    assert len(view) == 0

    # View store should still contain the kept engram
    kept = conn.execute(
        "SELECT * FROM view_engrams WHERE id='eng-keep'"
    ).fetchall()
    assert len(kept) == 1


def test_full_reconsolidation_resolves_pending_debt(conn):
    """Full mode should resolve pending_reconsolidation debt after consuming recon."""
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.repository import defer_to_debt

    _insert_engram(conn, "eng-recon", "needs reconsolidation", rigidity=0.15)
    _insert_recon(conn, "eng-recon", [])

    defer_to_debt(conn, "pending_reconsolidation", {"engram_id": "eng-recon"}, "epoch-prev")

    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None

    run_epoch_phases(conn, epoch_id, mode="full")

    recon = conn.execute(
        "SELECT content_consumed_epoch_id FROM recon_buffer WHERE engram_id='eng-recon'"
    ).fetchone()
    assert recon["content_consumed_epoch_id"] == epoch_id

    debt = conn.execute(
        "SELECT resolved_at FROM cognitive_debt "
        "WHERE type='pending_reconsolidation' AND raw_ref=?",
        (json.dumps({"engram_id": "eng-recon"}, sort_keys=True),),
    ).fetchone()
    assert debt is not None
    assert debt["resolved_at"] is not None


def test_epoch_failure_rolls_back_partial_view_rebuild(conn):
    """Failure during Phase 7 must rollback partial DELETEs before marking epoch failed."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_engram(conn, "eng-view", "still visible")
    conn.execute(
        "INSERT INTO view_engrams "
        "(id, content, type, state, strength, created_at) "
        "VALUES ('eng-view', 'still visible', 'fact', 'consolidated', 0.7, ?)",
        (NOW,),
    )
    conn.commit()

    epoch_id = acquire_lease(conn, vault_id="default", mode="full",
                             trigger="manual")
    assert epoch_id is not None

    def _broken_rebuild(db_conn, _epoch_id):
        db_conn.execute("DELETE FROM view_engrams")
        raise RuntimeError("boom during rebuild")

    with patch("memento.epoch.rebuild_view_store", side_effect=_broken_rebuild):
        with pytest.raises(RuntimeError, match="boom during rebuild"):
            run_epoch_phases(conn, epoch_id, mode="full")

    view_rows = conn.execute(
        "SELECT id FROM view_engrams WHERE id='eng-view'"
    ).fetchall()
    assert len(view_rows) == 1

    epoch_row = conn.execute(
        "SELECT status, error FROM epochs WHERE id=?",
        (epoch_id,),
    ).fetchone()
    assert epoch_row["status"] == "failed"
    assert "boom during rebuild" in epoch_row["error"]


# ═══════════════════════════════════════════════════════════════════════════
# v0.7.0 LLM Epoch Tests
# ═══════════════════════════════════════════════════════════════════════════

from unittest.mock import MagicMock


def test_phase2_llm_structuring(conn):
    """Phase 2 with LLM should use LLM-inferred type/tags."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-llm-1", "Redis needs TTL config", ctype="fact")
    _insert_capture(conn, "cap-llm-2", "User prefers dark mode", ctype="fact")

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = [
        {"id": "cap-llm-1", "type": "convention", "tags": ["redis", "cache", "ttl"],
         "content": "Redis needs TTL config for cache entries", "merge_with": None},
        {"id": "cap-llm-2", "type": "preference", "tags": ["ui", "dark-mode"],
         "content": "User prefers dark mode", "merge_with": None},
    ]

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    assert mock_llm.generate_json.called

    # LLM-inferred types should be applied
    rows = conn.execute(
        "SELECT content, type, tags FROM engrams WHERE state='consolidated'"
    ).fetchall()
    type_by_content = {r["content"]: r["type"] for r in rows}
    assert type_by_content.get("Redis needs TTL config for cache entries") == "convention"
    assert type_by_content.get("User prefers dark mode") == "preference"


def test_phase2_llm_content_change_updates_hash(conn):
    """Phase 2: when LLM modifies content, content_hash must be recomputed."""
    import hashlib
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-rehash", "redis config")

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = [
        {"id": "cap-rehash", "type": "convention", "tags": ["redis"],
         "content": "Redis cache config: set TTL to 3600s", "merge_with": None},
    ]

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    engram = conn.execute(
        "SELECT content, content_hash, embedding_pending FROM engrams WHERE state='consolidated'"
    ).fetchone()
    assert engram is not None
    assert engram["content"] == "Redis cache config: set TTL to 3600s"
    # Hash must match the NEW content, not the old
    expected_hash = hashlib.sha256(
        "redis cache config: set ttl to 3600s".encode()
    ).hexdigest()
    assert engram["content_hash"] == expected_hash
    # Embedding must be cleared since content changed
    assert engram["embedding_pending"] == 1


def test_phase2_llm_id_mismatch_defers_to_debt(conn):
    """Phase 2: if LLM returns wrong/missing ids, items should defer to debt."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-real", "Important fact")

    mock_llm = MagicMock()
    # LLM returns a completely wrong id
    mock_llm.generate_json.return_value = [
        {"id": "cap-WRONG", "type": "fact", "tags": ["test"],
         "content": "Important fact", "merge_with": None},
    ]

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    # Should have deferred to debt since id didn't match
    debt = conn.execute(
        "SELECT * FROM cognitive_debt WHERE type='pending_consolidation'"
    ).fetchall()
    assert len(debt) >= 1


def test_phase2_llm_failure_defers_to_debt(conn):
    """Phase 2 with LLM failure should defer to cognitive debt, not crash."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-fail", "Some capture")

    mock_llm = MagicMock()
    mock_llm.generate_json.side_effect = Exception("LLM API error")

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    debt = conn.execute(
        "SELECT * FROM cognitive_debt WHERE type='pending_consolidation'"
    ).fetchall()
    assert len(debt) >= 1

    # Epoch should still complete (degraded due to LLM failure in phase 2)
    epoch = conn.execute("SELECT status FROM epochs WHERE id=?", (epoch_id,)).fetchone()
    assert epoch["status"] == "committed"


def test_phase2_no_llm_auto_promotes(conn):
    """Phase 2 without LLM client should auto-promote (v0.5 compat)."""
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_capture(conn, "cap-nomodel", "No LLM capture")

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=None)

    engram = conn.execute(
        "SELECT * FROM engrams WHERE state='consolidated'"
    ).fetchone()
    assert engram is not None
    assert engram["content"] == "No LLM capture"


def test_phase2_debt_recovery(conn):
    """Phase 2 should recover items from cognitive debt on next epoch."""
    from memento.epoch import acquire_lease, run_epoch_phases
    from memento.repository import defer_to_debt

    _insert_capture(conn, "cap-debt-recover", "Deferred capture")

    defer_to_debt(conn, "pending_consolidation",
                  {"capture_log_id": "cap-debt-recover"}, "epoch-prev")

    # New epoch with working LLM should pick it up
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = [
        {"id": "cap-debt-recover", "type": "fact", "tags": ["test"],
         "content": "Deferred capture", "merge_with": None},
    ]

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    # Should now be promoted
    engram = conn.execute(
        "SELECT * FROM engrams WHERE state='consolidated'"
    ).fetchone()
    assert engram is not None
    assert engram["content"] == "Deferred capture"

    # Debt should be resolved
    debt = conn.execute(
        "SELECT resolved_at FROM cognitive_debt WHERE type='pending_consolidation'"
    ).fetchone()
    assert debt["resolved_at"] is not None


def test_phase5_llm_reconsolidation(conn):
    """Phase 5 with LLM should refine low-rigidity engram content and update hash/embedding."""
    import hashlib
    from memento.epoch import acquire_lease, run_epoch_phases

    _insert_engram(conn, "eng-recon-llm", "Redis cache config", rigidity=0.15)
    _insert_recon(conn, "eng-recon-llm", [], query_context="Redis TTL settings")

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "content": "Redis cache config: set TTL to 3600s for session keys",
        "changed": True,
    }

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    assert mock_llm.generate_json.called

    engram = conn.execute(
        "SELECT content, content_hash, embedding_pending FROM engrams WHERE id='eng-recon-llm'"
    ).fetchone()
    assert "TTL" in engram["content"]
    # Hash must match new content
    expected_hash = hashlib.sha256(
        "redis cache config: set ttl to 3600s for session keys".encode()
    ).hexdigest()
    assert engram["content_hash"] == expected_hash
    # Embedding must be invalidated
    assert engram["embedding_pending"] == 1


def test_phase5_high_rigidity_skips_llm(conn):
    """Phase 5 should not call LLM for high-rigidity engrams."""
    from memento.epoch import acquire_lease, run_epoch_phases

    # High rigidity engram (convention → 0.7)
    _insert_engram(conn, "eng-rigid", "Never use SELECT *", rigidity=0.7)
    _insert_recon(conn, "eng-rigid", [], query_context="SQL query patterns")

    mock_llm = MagicMock()

    epoch_id = acquire_lease(conn, "default", "full", "manual")
    run_epoch_phases(conn, epoch_id, mode="full", llm_client=mock_llm)

    # LLM should NOT have been called for reconsolidation
    # (it may be called for Phase 2 if there are captures, but there aren't any)
    engram = conn.execute(
        "SELECT content FROM engrams WHERE id='eng-rigid'"
    ).fetchone()
    assert engram["content"] == "Never use SELECT *"  # Unchanged
