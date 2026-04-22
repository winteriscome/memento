"""Tests for layered priming (v0.9.2 — Feature 1)."""
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from memento.db import init_db
from memento.migration import migrate_v03_to_v05


def _make_db():
    """Create in-memory DB with full schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    migrate_v03_to_v05(conn)
    return conn


def _insert_engram(conn, eid, content, etype="fact", strength=0.7,
                   importance="normal", project=None, hours_ago=0):
    """Insert an engram + session + view_engrams row for testing."""
    now = datetime.now()
    created = (now - timedelta(hours=hours_ago)).isoformat()
    session_id = None

    if project is not None:
        session_id = f"ses-{eid}"
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, project, status, started_at) "
            "VALUES (?, ?, 'active', ?)",
            (session_id, project, created),
        )

    conn.execute(
        "INSERT INTO engrams "
        "(id, content, type, strength, importance, origin, state, rigidity, "
        " access_count, created_at, last_accessed, source_session_id) "
        "VALUES (?, ?, ?, ?, ?, 'human', 'consolidated', 0.5, "
        " 1, ?, ?, ?)",
        (eid, content, etype, strength, importance, created, created, session_id),
    )
    conn.execute(
        "INSERT INTO view_engrams "
        "(id, content, type, state, strength, importance, origin, verified, "
        " rigidity, access_count, created_at, last_accessed) "
        "VALUES (?, ?, ?, 'consolidated', ?, ?, 'human', 0, "
        " 0.5, 1, ?, ?)",
        (eid, content, etype, strength, importance, created, created),
    )
    conn.commit()


class TestAwakeRecallByType:
    """Tests for awake_recall_by_type()."""

    def test_filters_by_type(self):
        conn = _make_db()
        _insert_engram(conn, "e1", "use pnpm", etype="convention", strength=0.9)
        _insert_engram(conn, "e2", "prefer dark mode", etype="preference", strength=0.8)
        _insert_engram(conn, "e3", "db uses WAL", etype="fact", strength=0.9)

        from memento.awake import awake_recall_by_type
        results = awake_recall_by_type(conn, types=["convention", "preference"])

        result_ids = {r["id"] for r in results}
        assert "e1" in result_ids
        assert "e2" in result_ids
        assert "e3" not in result_ids  # fact excluded

    def test_project_isolation(self):
        conn = _make_db()
        _insert_engram(conn, "e1", "use pnpm", etype="convention",
                       strength=0.9, project="nodejs-app")
        _insert_engram(conn, "e2", "use go modules", etype="convention",
                       strength=0.9, project="go-service")
        _insert_engram(conn, "e3", "always test", etype="convention",
                       strength=0.8, project=None)  # global

        from memento.awake import awake_recall_by_type
        results = awake_recall_by_type(
            conn, types=["convention"], project="go-service",
        )

        result_ids = {r["id"] for r in results}
        assert "e2" in result_ids   # matches project
        assert "e3" in result_ids   # global memory
        assert "e1" not in result_ids  # wrong project

    def test_project_none_only_global(self):
        """When project=None, only global memories (no project-specific)."""
        conn = _make_db()
        _insert_engram(conn, "e1", "nodejs rule", etype="convention",
                       strength=0.9, project="nodejs-app")
        _insert_engram(conn, "e2", "global rule", etype="convention",
                       strength=0.8, project=None)

        from memento.awake import awake_recall_by_type
        results = awake_recall_by_type(conn, types=["convention"], project=None)

        result_ids = {r["id"] for r in results}
        assert "e2" in result_ids
        assert "e1" not in result_ids

    def test_ordered_by_strength_desc(self):
        conn = _make_db()
        _insert_engram(conn, "e1", "weak", etype="preference", strength=0.3)
        _insert_engram(conn, "e2", "strong", etype="preference", strength=0.9)

        from memento.awake import awake_recall_by_type
        results = awake_recall_by_type(conn, types=["preference"])

        assert results[0]["id"] == "e2"
        assert results[1]["id"] == "e1"

    def test_respects_limit(self):
        conn = _make_db()
        for i in range(10):
            _insert_engram(conn, f"e{i}", f"pref {i}", etype="preference",
                           strength=0.5 + i * 0.01)

        from memento.awake import awake_recall_by_type
        results = awake_recall_by_type(conn, types=["preference"], limit=3)
        assert len(results) <= 3


class TestLayeredPriming:
    """Integration tests for L0/L1/L2 priming in session_start()."""

    def _make_api(self, conn):
        from memento.api import MementoAPI
        api = MementoAPI.__new__(MementoAPI)
        from memento.core import MementoCore
        api.core = MementoCore.__new__(MementoCore)
        api.core.conn = conn
        from memento.session import SessionService
        api._session_svc = SessionService(conn)
        api._use_awake = True
        api.conn = conn
        return api

    def test_l0_preference_convention_guaranteed(self):
        conn = _make_db()
        _insert_engram(conn, "c1", "use tabs", etype="convention", strength=0.9)
        _insert_engram(conn, "c2", "no magic numbers", etype="convention", strength=0.8)
        _insert_engram(conn, "c3", "PEP8", etype="convention", strength=0.7)
        _insert_engram(conn, "p1", "dark mode", etype="preference", strength=0.6)
        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")
        layers = {m.get("layer") for m in result.priming_memories}
        l0_types = {m["type"] for m in result.priming_memories if m.get("layer") == "L0"}
        assert "L0" in layers
        assert "preference" in l0_types
        assert "convention" in l0_types

    def test_l1_excludes_debugging(self):
        conn = _make_db()
        _insert_engram(conn, "d1", "bug was in parser", etype="debugging", strength=0.9)
        _insert_engram(conn, "f1", "API returns JSON", etype="fact", strength=0.5)
        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")
        l1_types = [m["type"] for m in result.priming_memories if m.get("layer") == "L1"]
        assert "debugging" not in l1_types

    def test_l2_deduplicates_l0_l1(self):
        conn = _make_db()
        _insert_engram(conn, "c1", "use tabs", etype="convention", strength=0.9)
        _insert_engram(conn, "f1", "db uses WAL", etype="fact", strength=0.8)
        _insert_engram(conn, "f2", "API is REST", etype="fact", strength=0.7)
        api = self._make_api(conn)
        result = api.session_start(project=None, task="db uses WAL")
        ids = [m["id"] for m in result.priming_memories]
        assert len(ids) == len(set(ids))

    def test_empty_db_fallback(self):
        conn = _make_db()
        api = self._make_api(conn)
        result = api.session_start(project=None, task="anything")
        assert result.priming_memories == []

    def test_cross_project_isolation(self):
        conn = _make_db()
        _insert_engram(conn, "n1", "use pnpm", etype="convention", strength=0.95, project="nodejs-app")
        _insert_engram(conn, "g1", "use go modules", etype="convention", strength=0.8, project="go-service")
        _insert_engram(conn, "gl", "write tests", etype="convention", strength=0.7, project=None)
        api = self._make_api(conn)
        result = api.session_start(project="go-service", task="setup")
        ids = {m["id"] for m in result.priming_memories}
        assert "n1" not in ids
        assert "g1" in ids or "gl" in ids

    def test_layer_field_present(self):
        conn = _make_db()
        _insert_engram(conn, "p1", "dark mode", etype="preference", strength=0.8)
        _insert_engram(conn, "f1", "uses SQLite", etype="fact", strength=0.7)
        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")
        for m in result.priming_memories:
            assert "layer" in m
            assert m["layer"] in ("L0", "L1", "L2")

    def test_priming_max_respected(self):
        conn = _make_db()
        for i in range(20):
            _insert_engram(conn, f"e{i}", f"memory {i}", etype="fact", strength=0.5 + i * 0.01)
        api = self._make_api(conn)
        result = api.session_start(project=None, task="test", priming_max=5)
        assert len(result.priming_memories) <= 5


class TestMCPPrimingFormat:
    """Tests for MCP priming prompt layer formatting."""

    def test_format_priming_with_layers(self):
        from memento.mcp_server import format_priming_prompt

        memories = [
            {"id": "e1", "content": "use tabs", "type": "convention", "layer": "L0"},
            {"id": "e2", "content": "dark mode", "type": "preference", "layer": "L0"},
            {"id": "e3", "content": "db uses WAL", "type": "fact", "layer": "L1"},
            {"id": "e4", "content": "discussed epoch", "type": "fact", "layer": "L2"},
        ]
        prompt = format_priming_prompt(memories)

        assert "[L0-Identity]" in prompt
        assert "[L1-Core]" in prompt
        assert "[L2-Context]" in prompt
        assert "use tabs" in prompt

    def test_format_priming_empty(self):
        from memento.mcp_server import format_priming_prompt
        prompt = format_priming_prompt([])
        assert prompt == ""

    def test_format_priming_no_layer_field(self):
        """Memories without layer field should still work (backward compat)."""
        from memento.mcp_server import format_priming_prompt

        memories = [
            {"id": "e1", "content": "old memory", "type": "fact"},
        ]
        prompt = format_priming_prompt(memories)
        assert "old memory" in prompt
