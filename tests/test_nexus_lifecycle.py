"""Tests for temporal nexus lifecycle (v0.9.2 — Feature 3)."""
import sqlite3
from datetime import datetime, timedelta

import pytest

from memento.db import init_db
from memento.migration import migrate_v03_to_v05


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    migrate_v03_to_v05(conn)
    return conn


class TestNexusMigration:

    def test_adds_invalidated_at_column(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(nexus)").fetchall()}
        assert "invalidated_at" in cols

    def test_existing_nexus_invalidated_at_null(self):
        conn = _make_db()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO engrams (id, content, type, strength, created_at, "
            "last_accessed, state) VALUES (?, ?, 'fact', 0.7, ?, ?, 'consolidated')",
            ("e1", "mem1", now, now),
        )
        conn.execute(
            "INSERT INTO engrams (id, content, type, strength, created_at, "
            "last_accessed, state) VALUES (?, ?, 'fact', 0.7, ?, ?, 'consolidated')",
            ("e2", "mem2", now, now),
        )
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("nex-1", "e1", "e2", "semantic", 0.5, now),
        )
        conn.commit()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-1'").fetchone()
        assert row["invalidated_at"] is None

    def test_migration_idempotent(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        migrate_v05_to_v092(conn)  # no error

    def test_view_nexus_has_invalidated_at(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(view_nexus)").fetchall()}
        assert "invalidated_at" in cols


def _insert_nexus(conn, nid, src, tgt, strength=0.5, invalidated=False):
    now = datetime.now().isoformat()
    inv_at = now if invalidated else None
    conn.execute(
        "INSERT INTO nexus (id, source_id, target_id, type, "
        "association_strength, created_at, invalidated_at) "
        "VALUES (?, ?, ?, 'semantic', ?, ?, ?)",
        (nid, src, tgt, strength, now, inv_at),
    )
    conn.commit()


def _insert_engram_simple(conn, eid):
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO engrams (id, content, type, strength, "
        "created_at, last_accessed, state) "
        "VALUES (?, ?, 'fact', 0.7, ?, ?, 'consolidated')",
        (eid, f"content-{eid}", now, now),
    )
    conn.commit()


class TestNexusInvalidation:

    def test_invalidate_nexus(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        _insert_nexus(conn, "nex-1", "e1", "e2")
        from memento.repository import invalidate_nexus
        invalidate_nexus(conn, "nex-1")
        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-1'").fetchone()
        assert row["invalidated_at"] is not None

    def test_default_query_excludes_invalidated(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        _insert_engram_simple(conn, "e3")
        _insert_nexus(conn, "nex-1", "e1", "e2", invalidated=False)
        _insert_nexus(conn, "nex-2", "e2", "e3", invalidated=True)
        rows = conn.execute(
            "SELECT * FROM nexus WHERE (source_id=? OR target_id=?) "
            "AND invalidated_at IS NULL",
            ("e2", "e2"),
        ).fetchall()
        ids = {r["id"] for r in rows}
        assert "nex-1" in ids
        assert "nex-2" not in ids

    def test_include_invalidated_returns_all(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        _insert_engram_simple(conn, "e3")
        _insert_nexus(conn, "nex-1", "e1", "e2", invalidated=False)
        _insert_nexus(conn, "nex-2", "e2", "e3", invalidated=True)
        rows = conn.execute(
            "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
            ("e2", "e2"),
        ).fetchall()
        ids = {r["id"] for r in rows}
        assert "nex-1" in ids
        assert "nex-2" in ids


class TestAutoInvalidation:

    def test_stale_weak_edge_invalidated(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, last_coactivated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.05, ?, ?)",
            ("nex-stale", "e1", "e2", old_date, old_date),
        )
        conn.commit()
        from memento.epoch import _auto_invalidate_stale_edges
        count = _auto_invalidate_stale_edges(conn)
        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-stale'").fetchone()
        assert row["invalidated_at"] is not None
        assert count == 1

    def test_strong_edge_not_invalidated(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, last_coactivated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.8, ?, ?)",
            ("nex-strong", "e1", "e2", old_date, old_date),
        )
        conn.commit()
        from memento.epoch import _auto_invalidate_stale_edges
        count = _auto_invalidate_stale_edges(conn)
        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-strong'").fetchone()
        assert row["invalidated_at"] is None
        assert count == 0

    def test_recent_weak_edge_not_invalidated(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        recent = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, last_coactivated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.05, ?, ?)",
            ("nex-recent", "e1", "e2", recent, recent),
        )
        conn.commit()
        from memento.epoch import _auto_invalidate_stale_edges
        count = _auto_invalidate_stale_edges(conn)
        assert count == 0


class TestNexusResurrection:

    def test_invalidated_edge_resurrected(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, invalidated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.3, ?, ?)",
            ("nex-dead", "e1", "e2", now, now),
        )
        conn.commit()
        from memento.hebbian import NexusUpdatePlan
        plan = NexusUpdatePlan(
            source_id="e1", target_id="e2", type="semantic",
            strength_delta=0.05, last_coactivated_at=now,
            is_new=False,
        )
        from memento.repository import apply_nexus_plan
        apply_nexus_plan(conn, [plan], "epoch-test")
        row = conn.execute("SELECT * FROM nexus WHERE id='nex-dead'").fetchone()
        assert row["invalidated_at"] is None
        assert row["association_strength"] == pytest.approx(0.35, abs=0.01)


class TestViewNexusRebuild:

    def test_rebuild_preserves_invalidated_at(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, invalidated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.5, ?, ?)",
            ("nex-inv", "e1", "e2", now, now),
        )
        conn.commit()
        from memento.repository import rebuild_view_store
        rebuild_view_store(conn, "epoch-test")
        row = conn.execute(
            "SELECT invalidated_at FROM view_nexus WHERE id='nex-inv'"
        ).fetchone()
        assert row is not None
        assert row["invalidated_at"] == now


class TestNexusExportImport:

    def test_export_includes_invalidated_at(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at, invalidated_at) "
            "VALUES (?, ?, ?, 'semantic', 0.5, ?, ?)",
            ("nex-inv", "e1", "e2", now, now),
        )
        conn.commit()
        from memento.core import MementoCore
        core = MementoCore.__new__(MementoCore)
        core.conn = conn
        from memento.export import export_nexus
        nexus_data = export_nexus(core)
        inv_entry = [n for n in nexus_data if n["id"] == "nex-inv"][0]
        assert "invalidated_at" in inv_entry
        assert inv_entry["invalidated_at"] == now

    def test_import_preserves_invalidated_at(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        _insert_engram_simple(conn, "e1")
        _insert_engram_simple(conn, "e2")
        now = datetime.now().isoformat()
        nexus_data = [{
            "id": "nex-imp",
            "source_id": "e1",
            "target_id": "e2",
            "type": "semantic",
            "association_strength": 0.5,
            "created_at": now,
            "invalidated_at": now,
        }]
        from memento.core import MementoCore
        core = MementoCore.__new__(MementoCore)
        core.conn = conn
        from memento.export import import_memories
        import_memories(core, [], nexus=nexus_data)
        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-imp'").fetchone()
        assert row is not None
        assert row["invalidated_at"] == now
