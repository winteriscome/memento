"""Tests for Repository (Persistence Layer, Task 7)."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from memento.state_machine import TransitionPlan, DropDecision
from memento.delta_fold import StrengthUpdatePlan
from memento.hebbian import NexusUpdatePlan


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


@pytest.fixture
def conn(tmp_path):
    """Create a migrated v0.5 database connection."""
    from memento.migration import migrate_v03_to_v05, migrate_v05_to_v092

    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    _create_v03_db(c)
    migrate_v03_to_v05(c)
    migrate_v05_to_v092(c)
    return c


NOW = "2026-04-01T12:00:00+00:00"
EPOCH_ID = "epoch-test-001"


def _insert_capture_log(conn, capture_id="cap-1", content="Test memory",
                        type_="fact", origin="human"):
    """Insert a capture_log row for testing."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    conn.execute(
        "INSERT INTO capture_log (id, content, type, tags, importance, origin, "
        "content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (capture_id, content, type_, "test,repo", "normal", origin,
         content_hash, NOW),
    )
    conn.commit()


def _insert_engram(conn, engram_id="eng-1", content="Existing engram",
                   type_="fact", state="consolidated", strength=0.7,
                   origin="human"):
    """Insert an engram row for testing."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    conn.execute(
        "INSERT INTO engrams (id, content, type, tags, strength, importance, "
        "origin, verified, created_at, last_accessed, access_count, forgotten, "
        "state, rigidity, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (engram_id, content, type_, "test", strength, "normal", origin, 0,
         NOW, NOW, 0, 0, state, 0.5, content_hash),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_l2_to_l3
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyL2ToL3:
    def test_creates_engram_from_capture(self, conn):
        from memento.repository import apply_l2_to_l3

        _insert_capture_log(conn, "cap-1", "Redis uses port 6379", "fact", "human")

        plan = TransitionPlan(
            engram_id=None,
            capture_log_id="cap-1",
            from_state="buffered",
            to_state="consolidated",
            transition="T1",
            reason="promote to L3",
            epoch_id=EPOCH_ID,
        )
        capture_item = dict(conn.execute(
            "SELECT * FROM capture_log WHERE id='cap-1'"
        ).fetchone())

        engram_id = apply_l2_to_l3(conn, plan, capture_item)

        # Engram created
        engram = conn.execute(
            "SELECT * FROM engrams WHERE id=?", (engram_id,)
        ).fetchone()
        assert engram is not None
        assert engram["content"] == "Redis uses port 6379"
        assert engram["state"] == "consolidated"
        assert engram["strength"] == pytest.approx(0.7)  # human origin

        # capture_log marked promoted
        cap = conn.execute(
            "SELECT * FROM capture_log WHERE id='cap-1'"
        ).fetchone()
        assert cap["epoch_id"] == EPOCH_ID
        assert cap["disposition"] == "promoted"

    def test_agent_origin_gets_lower_strength(self, conn):
        from memento.repository import apply_l2_to_l3

        _insert_capture_log(conn, "cap-a", "Agent observation", "fact", "agent")

        plan = TransitionPlan(
            engram_id=None, capture_log_id="cap-a",
            from_state="buffered", to_state="consolidated",
            transition="T1", reason="promote", epoch_id=EPOCH_ID,
        )
        capture_item = dict(conn.execute(
            "SELECT * FROM capture_log WHERE id='cap-a'"
        ).fetchone())

        engram_id = apply_l2_to_l3(conn, plan, capture_item)
        engram = conn.execute(
            "SELECT strength FROM engrams WHERE id=?", (engram_id,)
        ).fetchone()
        assert engram["strength"] == pytest.approx(0.5)  # agent cap

    def test_rigidity_set_by_type(self, conn):
        from memento.repository import apply_l2_to_l3

        _insert_capture_log(conn, "cap-p", "Always use tabs", "preference", "human")

        plan = TransitionPlan(
            engram_id=None, capture_log_id="cap-p",
            from_state="buffered", to_state="consolidated",
            transition="T1", reason="promote", epoch_id=EPOCH_ID,
        )
        capture_item = dict(conn.execute(
            "SELECT * FROM capture_log WHERE id='cap-p'"
        ).fetchone())

        engram_id = apply_l2_to_l3(conn, plan, capture_item)
        engram = conn.execute(
            "SELECT rigidity FROM engrams WHERE id=?", (engram_id,)
        ).fetchone()
        assert engram["rigidity"] == pytest.approx(0.7)  # preference default


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_drop_decisions
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyDropDecisions:
    def test_marks_capture_log_dropped(self, conn):
        from memento.repository import apply_drop_decisions

        _insert_capture_log(conn, "cap-d1", "Noise data")
        _insert_capture_log(conn, "cap-d2", "Duplicate data")

        drops = [
            DropDecision(capture_log_id="cap-d1", reason="noise", epoch_id=EPOCH_ID),
            DropDecision(capture_log_id="cap-d2", reason="duplicate", epoch_id=EPOCH_ID),
        ]
        apply_drop_decisions(conn, drops)

        for cap_id, reason in [("cap-d1", "noise"), ("cap-d2", "duplicate")]:
            row = conn.execute(
                "SELECT * FROM capture_log WHERE id=?", (cap_id,)
            ).fetchone()
            assert row["epoch_id"] == EPOCH_ID
            assert row["disposition"] == "dropped"
            assert row["drop_reason"] == reason


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_pending_forgets
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyPendingForgets:
    def test_forgets_engram_and_cleans_up(self, conn):
        from memento.repository import apply_pending_forgets

        # Setup: engram with nexus, delta_ledger, recon_buffer
        _insert_engram(conn, "eng-f1", "To be forgotten")
        _insert_engram(conn, "eng-f2", "Linked engram")

        # Nexus (should CASCADE on engram state change — but we handle manually)
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("nex-1", "eng-f1", "eng-f2", "semantic", NOW),
        )
        # Delta ledger (unconsumed)
        conn.execute(
            "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("eng-f1", "reinforce", 0.1, NOW),
        )
        # Delta ledger (consumed — should NOT be cleaned)
        conn.execute(
            "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, epoch_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("eng-f1", "decay", -0.05, "old-epoch", NOW),
        )
        # Recon buffer (unconsumed)
        conn.execute(
            "INSERT INTO recon_buffer (engram_id, query_context, coactivated_ids, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("eng-f1", "query", '["eng-f2"]', NOW),
        )
        # Recon buffer (consumed — should still be cleaned for forget)
        conn.execute(
            "INSERT INTO recon_buffer (engram_id, query_context, coactivated_ids, "
            "nexus_consumed_epoch_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("eng-f1", "old query", '["eng-f2"]', "old-epoch", NOW),
        )
        # Pending forget request
        conn.execute(
            "INSERT INTO pending_forget (id, target_table, target_id, requested_at) "
            "VALUES (?, ?, ?, ?)",
            ("pf-1", "engrams", "eng-f1", NOW),
        )
        conn.commit()

        count, forgotten_ids = apply_pending_forgets(conn, EPOCH_ID)

        assert count == 1
        assert "eng-f1" in forgotten_ids

        # Engram state → forgotten
        engram = conn.execute(
            "SELECT state FROM engrams WHERE id='eng-f1'"
        ).fetchone()
        assert engram["state"] == "forgotten"

        # Nexus deleted by CASCADE
        nexus = conn.execute("SELECT * FROM nexus WHERE id='nex-1'").fetchone()
        assert nexus is None

        # Unconsumed delta_ledger cleaned
        unconsumed = conn.execute(
            "SELECT * FROM delta_ledger WHERE engram_id='eng-f1' AND epoch_id IS NULL"
        ).fetchone()
        assert unconsumed is None

        # Consumed delta_ledger preserved
        consumed = conn.execute(
            "SELECT * FROM delta_ledger WHERE engram_id='eng-f1' AND epoch_id IS NOT NULL"
        ).fetchone()
        assert consumed is not None

        # ALL recon_buffer rows cleaned (regardless of consumption state)
        recon = conn.execute(
            "SELECT * FROM recon_buffer WHERE engram_id='eng-f1'"
        ).fetchall()
        assert len(recon) == 0

        # pending_forget entry consumed
        pf = conn.execute("SELECT * FROM pending_forget WHERE id='pf-1'").fetchone()
        assert pf is None

    def test_forgets_capture_log(self, conn):
        from memento.repository import apply_pending_forgets

        _insert_capture_log(conn, "cap-forget", "Capture to forget")
        conn.execute(
            "INSERT INTO pending_forget (id, target_table, target_id, requested_at) "
            "VALUES (?, ?, ?, ?)",
            ("pf-c1", "capture_log", "cap-forget", NOW),
        )
        conn.commit()

        count, forgotten_ids = apply_pending_forgets(conn, EPOCH_ID)

        assert count == 1
        cap = conn.execute(
            "SELECT * FROM capture_log WHERE id='cap-forget'"
        ).fetchone()
        assert cap["disposition"] == "dropped"
        assert cap["drop_reason"] == "user_forget"

    def test_no_pending_forgets(self, conn):
        from memento.repository import apply_pending_forgets

        count, forgotten_ids = apply_pending_forgets(conn, EPOCH_ID)
        assert count == 0
        assert forgotten_ids == []


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_strength_plan
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyStrengthPlan:
    def test_updates_strength_and_access_count(self, conn):
        from memento.repository import apply_strength_plan

        _insert_engram(conn, "eng-s1", strength=0.5)

        # Insert delta_ledger rows
        conn.execute(
            "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("eng-s1", "reinforce", 0.1, NOW),
        )
        ledger_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        plans = [
            StrengthUpdatePlan(
                engram_id="eng-s1",
                old_strength=0.5,
                new_strength=0.6,
                access_count_delta=1,
                update_last_accessed=True,
                source_ledger_ids=[ledger_id],
            ),
        ]
        apply_strength_plan(conn, plans, EPOCH_ID)

        engram = conn.execute(
            "SELECT strength, access_count FROM engrams WHERE id='eng-s1'"
        ).fetchone()
        assert engram["strength"] == pytest.approx(0.6)
        assert engram["access_count"] == 1

        # delta_ledger marked consumed
        dl = conn.execute(
            "SELECT epoch_id FROM delta_ledger WHERE id=?", (ledger_id,)
        ).fetchone()
        assert dl["epoch_id"] == EPOCH_ID

    def test_decay_only_no_last_accessed_update(self, conn):
        from memento.repository import apply_strength_plan

        _insert_engram(conn, "eng-s2", strength=0.7)
        conn.execute(
            "INSERT INTO delta_ledger (engram_id, delta_type, delta_value, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("eng-s2", "decay", -0.05, NOW),
        )
        ledger_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        original_last_accessed = conn.execute(
            "SELECT last_accessed FROM engrams WHERE id='eng-s2'"
        ).fetchone()["last_accessed"]

        plans = [
            StrengthUpdatePlan(
                engram_id="eng-s2",
                old_strength=0.7,
                new_strength=0.65,
                access_count_delta=0,
                update_last_accessed=False,
                source_ledger_ids=[ledger_id],
            ),
        ]
        apply_strength_plan(conn, plans, EPOCH_ID)

        engram = conn.execute(
            "SELECT strength, last_accessed FROM engrams WHERE id='eng-s2'"
        ).fetchone()
        assert engram["strength"] == pytest.approx(0.65)
        assert engram["last_accessed"] == original_last_accessed


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_nexus_plan
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyNexusPlan:
    def test_creates_new_nexus(self, conn):
        from memento.repository import apply_nexus_plan

        _insert_engram(conn, "eng-n1")
        _insert_engram(conn, "eng-n2")

        # Insert recon_buffer
        conn.execute(
            "INSERT INTO recon_buffer (engram_id, query_context, coactivated_ids, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("eng-n1", "test query", '["eng-n2"]', NOW),
        )
        recon_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        plans = [
            NexusUpdatePlan(
                source_id="eng-n1",
                target_id="eng-n2",
                type="semantic",
                strength_delta=0.05,
                last_coactivated_at=NOW,
                is_new=True,
                source_recon_ids=[recon_id],
            ),
        ]
        apply_nexus_plan(conn, plans, EPOCH_ID)

        nexus = conn.execute(
            "SELECT * FROM nexus WHERE source_id='eng-n1' AND target_id='eng-n2'"
        ).fetchone()
        assert nexus is not None
        assert nexus["association_strength"] == pytest.approx(0.55)  # default 0.5 + 0.05

        # recon_buffer marked consumed
        recon = conn.execute(
            "SELECT nexus_consumed_epoch_id FROM recon_buffer WHERE id=?", (recon_id,)
        ).fetchone()
        assert recon["nexus_consumed_epoch_id"] == EPOCH_ID

    def test_updates_existing_nexus_capped(self, conn):
        from memento.repository import apply_nexus_plan

        _insert_engram(conn, "eng-n3")
        _insert_engram(conn, "eng-n4")

        # Pre-existing nexus at 0.95
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, association_strength, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("nex-exist", "eng-n3", "eng-n4", "semantic", 0.95, NOW),
        )
        conn.commit()

        plans = [
            NexusUpdatePlan(
                source_id="eng-n3",
                target_id="eng-n4",
                type="semantic",
                strength_delta=0.1,
                last_coactivated_at=NOW,
                is_new=False,
                source_recon_ids=[],
            ),
        ]
        apply_nexus_plan(conn, plans, EPOCH_ID)

        nexus = conn.execute(
            "SELECT association_strength FROM nexus WHERE id='nex-exist'"
        ).fetchone()
        assert nexus["association_strength"] == pytest.approx(1.0)  # capped


# ═══════════════════════════════════════════════════════════════════════════
# Test: apply_transition_plan
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyTransitionPlan:
    def test_updates_engram_state(self, conn):
        from memento.repository import apply_transition_plan

        _insert_engram(conn, "eng-t1", state="consolidated")

        plan = TransitionPlan(
            engram_id="eng-t1",
            capture_log_id=None,
            from_state="consolidated",
            to_state="archived",
            transition="T6",
            reason="low frequency",
            epoch_id=EPOCH_ID,
        )
        apply_transition_plan(conn, plan)

        engram = conn.execute(
            "SELECT state, last_state_changed_epoch_id FROM engrams WHERE id='eng-t1'"
        ).fetchone()
        assert engram["state"] == "archived"
        assert engram["last_state_changed_epoch_id"] == EPOCH_ID


# ═══════════════════════════════════════════════════════════════════════════
# Test: rebuild_view_store
# ═══════════════════════════════════════════════════════════════════════════


class TestRebuildViewStore:
    def test_only_consolidated_in_view(self, conn):
        from memento.repository import rebuild_view_store

        _insert_engram(conn, "eng-v1", state="consolidated")
        _insert_engram(conn, "eng-v2", state="archived")
        _insert_engram(conn, "eng-v3", state="forgotten")
        _insert_engram(conn, "eng-v4", content="Second consolidated",
                       state="consolidated")

        # Add nexus between consolidated engrams
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, association_strength, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("nex-v1", "eng-v1", "eng-v4", "semantic", 0.8, NOW),
        )
        # Nexus involving non-consolidated — should NOT appear in view
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, association_strength, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("nex-v2", "eng-v1", "eng-v2", "semantic", 0.6, NOW),
        )
        conn.commit()

        rebuild_view_store(conn, EPOCH_ID)

        # Only consolidated engrams in view_engrams
        view_rows = conn.execute("SELECT id FROM view_engrams").fetchall()
        view_ids = {r["id"] for r in view_rows}
        assert view_ids == {"eng-v1", "eng-v4"}

        # Only nexus between consolidated engrams in view_nexus
        view_nexus = conn.execute("SELECT id FROM view_nexus").fetchall()
        vnex_ids = {r["id"] for r in view_nexus}
        assert vnex_ids == {"nex-v1"}

        # View pointer updated
        vp = conn.execute(
            "SELECT epoch_id FROM view_pointer WHERE id='current'"
        ).fetchone()
        assert vp["epoch_id"] == EPOCH_ID

    def test_view_store_is_idempotent(self, conn):
        from memento.repository import rebuild_view_store

        _insert_engram(conn, "eng-idem", state="consolidated")
        rebuild_view_store(conn, "epoch-1")
        rebuild_view_store(conn, "epoch-2")

        rows = conn.execute("SELECT id FROM view_engrams").fetchall()
        assert len(rows) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Test: update_decay_watermark
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateDecayWatermark:
    def test_updates_watermark(self, conn):
        from memento.repository import update_decay_watermark

        new_wm = "2026-04-02T00:00:00+00:00"
        update_decay_watermark(conn, new_wm)

        row = conn.execute(
            "SELECT value FROM runtime_cursors WHERE key='decay_watermark'"
        ).fetchone()
        assert row["value"] == new_wm


# ═══════════════════════════════════════════════════════════════════════════
# Test: defer_to_debt / resolve_debt
# ═══════════════════════════════════════════════════════════════════════════


class TestCognitiveDebt:
    def test_defer_creates_debt(self, conn):
        from memento.repository import defer_to_debt

        raw_ref = {"engram_id": "eng-1", "reason": "needs abstraction"}
        defer_to_debt(conn, "abstraction", raw_ref, EPOCH_ID)

        row = conn.execute(
            "SELECT * FROM cognitive_debt WHERE type='abstraction'"
        ).fetchone()
        assert row is not None
        assert row["accumulated_epochs"] == 0
        assert row["resolved_at"] is None

    def test_defer_increments_existing(self, conn):
        from memento.repository import defer_to_debt

        raw_ref = {"engram_id": "eng-1", "reason": "needs abstraction"}
        defer_to_debt(conn, "abstraction", raw_ref, "epoch-1")
        defer_to_debt(conn, "abstraction", raw_ref, "epoch-2")

        rows = conn.execute(
            "SELECT * FROM cognitive_debt WHERE type='abstraction'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["accumulated_epochs"] == 1

    def test_resolve_debt(self, conn):
        from memento.repository import defer_to_debt, resolve_debt

        raw_ref = {"engram_id": "eng-1", "reason": "needs abstraction"}
        defer_to_debt(conn, "abstraction", raw_ref, EPOCH_ID)
        resolve_debt(conn, "abstraction", raw_ref)

        row = conn.execute(
            "SELECT resolved_at FROM cognitive_debt WHERE type='abstraction'"
        ).fetchone()
        assert row["resolved_at"] is not None
