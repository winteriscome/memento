# v0.9.2 MemPalace-Inspired Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement layered context injection (P0), local-first embedding (P0), and temporal nexus lifecycle (P1) for Memento v0.9.2.

**Architecture:** Three independent features that share no core logic but touch some common files (cli.py, mcp_server.py). Execute sequentially: Feature 1 → 2 → 3. Each feature is self-contained and produces testable results independently.

**Tech Stack:** Python 3.10+, SQLite, sqlite-vec, pytest

**Spec:** `docs/superpowers/specs/2026-04-10-v092-mempalace-inspired-enhancements-design.md`

---

## File Map

### Feature 1: Layered Context Injection

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/memento/awake.py` | New `awake_recall_by_type()` function |
| Modify | `src/memento/api.py` | Refactor `session_start()` priming to three-layer |
| Modify | `src/memento/mcp_server.py` | Layer-grouped priming prompt formatting |
| Modify | `src/memento/session.py` | `SessionStartResult` — no schema change needed, `layer` added per-memory |
| Create | `tests/test_layered_priming.py` | All priming tests |

### Feature 2: Local Embedding First

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/memento/config.py` | `_defaults()` provider → `"local"` |
| Modify | `src/memento/embedding.py` | `provider_map` adds `"local"` |
| Modify | `src/memento/cli.py` | Setup wizard + doctor updates |
| Modify | `tests/test_config.py` | Update provider assertion |
| Create | `tests/test_local_embedding.py` | Local provider tests |

### Feature 3: Temporal Nexus Lifecycle

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/memento/migration.py` | `migrate_v05_to_v092()` + `invalidated_at` column |
| Modify | `src/memento/epoch.py` | Phase 4 stale-edge scan |
| Modify | `src/memento/repository.py` | `invalidate_nexus()` + resurrection in `apply_nexus_plan()` |
| Modify | `src/memento/mcp_server.py` | `memento_nexus` params + `memento_nexus_invalidate` tool |
| Modify | `src/memento/export.py` | Export/import `invalidated_at` |
| Modify | `src/memento/cli.py` | Nexus CLI `--include-invalidated` + CTE filter |
| Create | `tests/test_nexus_lifecycle.py` | All nexus lifecycle tests |

---

## Feature 1: Layered Context Injection

### Task 1: `awake_recall_by_type()` — Core Query Function

**Files:**
- Create: `tests/test_layered_priming.py`
- Modify: `src/memento/awake.py:59` (add new function before `awake_recall`)

- [ ] **Step 1: Write failing tests for `awake_recall_by_type`**

```python
# tests/test_layered_priming.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_layered_priming.py -v
```
Expected: FAIL — `ImportError: cannot import name 'awake_recall_by_type'`

- [ ] **Step 3: Implement `awake_recall_by_type()`**

Add this function in `src/memento/awake.py` before `awake_recall()` (before line 59):

```python
def awake_recall_by_type(
    conn: sqlite3.Connection,
    types: list[str],
    project: str | None = None,
    limit: int = 50,
    order_by: str = "strength",
) -> list[dict]:
    """Retrieve engrams filtered by type and project for layered priming.

    Project isolation:
    - project is a string → match that project + global (project IS NULL)
    - project is None → only global memories (no project-specific)

    order_by:
    - "strength": for L0 (raw strength, identity stability)
    - "last_accessed": for L1 (ensure recent memories enter candidate pool)
    """
    placeholders = ",".join("?" * len(types))
    order_col = "v.last_accessed" if order_by == "last_accessed" else "v.strength"

    if project is not None:
        sql = f"""
            SELECT v.* FROM view_engrams v
            JOIN engrams e ON v.id = e.id
            LEFT JOIN sessions s ON e.source_session_id = s.id
            WHERE v.type IN ({placeholders})
              AND (s.project = ? OR s.project IS NULL)
            ORDER BY {order_col} DESC
            LIMIT ?
        """
        params = [*types, project, limit]
    else:
        # project=None: only global memories
        sql = f"""
            SELECT v.* FROM view_engrams v
            JOIN engrams e ON v.id = e.id
            LEFT JOIN sessions s ON e.source_session_id = s.id
            WHERE v.type IN ({placeholders})
              AND s.project IS NULL
            ORDER BY {order_col} DESC
            LIMIT ?
        """
        params = [*types, limit]

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_layered_priming.py::TestAwakeRecallByType -v
```
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/memento/awake.py tests/test_layered_priming.py
git commit -m "feat(priming): add awake_recall_by_type with project isolation"
```

---

### Task 2: L0 + L1 + L2 Orchestration in `session_start()`

**Files:**
- Modify: `src/memento/api.py:159-183`
- Modify: `tests/test_layered_priming.py`

- [ ] **Step 1: Write failing tests for three-layer priming**

Append to `tests/test_layered_priming.py`:

```python
from memento.decay import effective_strength as compute_eff_strength


class TestLayeredPriming:
    """Integration tests for L0/L1/L2 priming in session_start()."""

    def _make_api(self, conn):
        """Create MementoAPI backed by given connection."""
        from memento.api import MementoAPI
        api = MementoAPI.__new__(MementoAPI)
        from memento.core import MementoCore
        api.core = MementoCore.__new__(MementoCore)
        api.core.conn = conn
        from memento.session import SessionService
        api._session_svc = SessionService(conn)
        api._use_awake = True
        return api

    def test_l0_preference_convention_guaranteed(self):
        """L0 must include both preference and convention, not just one type."""
        conn = _make_db()
        # 3 conventions, 0 preferences initially
        _insert_engram(conn, "c1", "use tabs", etype="convention", strength=0.9)
        _insert_engram(conn, "c2", "no magic numbers", etype="convention", strength=0.8)
        _insert_engram(conn, "c3", "PEP8", etype="convention", strength=0.7)
        _insert_engram(conn, "p1", "dark mode", etype="preference", strength=0.6)

        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")

        layers = {m.get("layer") for m in result.priming_memories}
        l0_types = {m["type"] for m in result.priming_memories
                    if m.get("layer") == "L0"}
        assert "L0" in layers
        assert "preference" in l0_types  # preference guaranteed slot
        assert "convention" in l0_types  # convention guaranteed slot

    def test_l1_excludes_debugging(self):
        """L1 must not include debugging type memories."""
        conn = _make_db()
        _insert_engram(conn, "d1", "bug was in parser", etype="debugging", strength=0.9)
        _insert_engram(conn, "f1", "API returns JSON", etype="fact", strength=0.5)

        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")

        l1_types = [m["type"] for m in result.priming_memories
                    if m.get("layer") == "L1"]
        assert "debugging" not in l1_types

    def test_l2_deduplicates_l0_l1(self):
        """L2 must not repeat memories already in L0/L1."""
        conn = _make_db()
        _insert_engram(conn, "c1", "use tabs", etype="convention", strength=0.9)
        _insert_engram(conn, "f1", "db uses WAL", etype="fact", strength=0.8)
        _insert_engram(conn, "f2", "API is REST", etype="fact", strength=0.7)

        api = self._make_api(conn)
        result = api.session_start(project=None, task="db uses WAL")

        ids = [m["id"] for m in result.priming_memories]
        assert len(ids) == len(set(ids))  # no duplicates

    def test_empty_db_fallback(self):
        """Empty DB: L2 gets full budget, no crash."""
        conn = _make_db()
        api = self._make_api(conn)
        result = api.session_start(project=None, task="anything")

        assert result.priming_memories == []

    def test_cross_project_isolation(self):
        """Node.js conventions must NOT appear in Go project priming."""
        conn = _make_db()
        _insert_engram(conn, "n1", "use pnpm", etype="convention",
                       strength=0.95, project="nodejs-app")
        _insert_engram(conn, "g1", "use go modules", etype="convention",
                       strength=0.8, project="go-service")
        _insert_engram(conn, "gl", "write tests", etype="convention",
                       strength=0.7, project=None)

        api = self._make_api(conn)
        result = api.session_start(project="go-service", task="setup")

        ids = {m["id"] for m in result.priming_memories}
        assert "n1" not in ids  # nodejs convention excluded
        assert "g1" in ids or "gl" in ids  # go or global included

    def test_layer_field_present(self):
        """Every priming memory must have a 'layer' field."""
        conn = _make_db()
        _insert_engram(conn, "p1", "dark mode", etype="preference", strength=0.8)
        _insert_engram(conn, "f1", "uses SQLite", etype="fact", strength=0.7)

        api = self._make_api(conn)
        result = api.session_start(project=None, task="test")

        for m in result.priming_memories:
            assert "layer" in m
            assert m["layer"] in ("L0", "L1", "L2")

    def test_priming_max_respected(self):
        """Total priming count must not exceed priming_max."""
        conn = _make_db()
        for i in range(20):
            _insert_engram(conn, f"e{i}", f"memory {i}", etype="fact",
                           strength=0.5 + i * 0.01)

        api = self._make_api(conn)
        result = api.session_start(project=None, task="test", priming_max=5)

        assert len(result.priming_memories) <= 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_layered_priming.py::TestLayeredPriming -v
```
Expected: FAIL — current `session_start` doesn't return `layer` field

- [ ] **Step 3: Implement three-layer priming in `api.py`**

Replace the priming logic in `session_start()` at `src/memento/api.py:159-183`:

```python
    # ── Priming Constants ──
    L0_BUDGET = 3
    L1_BUDGET = 2
    PRIMING_MAX_DEFAULT = 7
    MIN_L1_THRESHOLD = 0.15

    def session_start(
        self,
        project: str | None = None,
        task: str | None = None,
        metadata: dict | None = None,
        priming_query: str | None = None,
        priming_max: int | None = None,
    ) -> SessionStartResult:
        """创建会话，使用三层 priming 注入上下文。

        L0 (Identity): preference + convention, sorted by raw strength
        L1 (Core): decision/fact/insight, sorted by effective_strength
        L2 (Task): query-based recall, fills remaining budget
        """
        from memento.awake import awake_recall_by_type
        from memento.decay import effective_strength as compute_eff_strength

        if priming_max is None:
            priming_max = self.PRIMING_MAX_DEFAULT

        session_id = self._session_svc.start(
            project=project, task=task, metadata=metadata
        )

        # ── L0: Identity Layer ──
        l0_candidates = awake_recall_by_type(
            self.conn, types=["preference", "convention"],
            project=project, limit=50,
        )
        l0_results = self._select_l0(l0_candidates, budget=self.L0_BUDGET)
        for m in l0_results:
            m["layer"] = "L0"

        # ── L1: Core Memory Layer ──
        l1_candidates = awake_recall_by_type(
            self.conn, types=["decision", "fact", "insight"],
            project=project, limit=50,
            order_by="last_accessed",  # ensure recent memories enter pool
        )
        l1_exclude = {m["id"] for m in l0_results}
        l1_results = self._select_l1(
            l1_candidates, budget=self.L1_BUDGET,
            exclude_ids=l1_exclude,
        )
        for m in l1_results:
            m["layer"] = "L1"

        # ── L2: Task-Relevant Layer ──
        l2_budget = priming_max - len(l0_results) - len(l1_results)
        l2_exclude = l1_exclude | {m["id"] for m in l1_results}
        query = priming_query or task or project or "项目概况"

        l2_results = []
        if l2_budget > 0:
            raw = self.core.recall(
                query, max_results=l2_budget + len(l2_exclude),
                reinforce=False,
            )
            for r in raw:
                if len(l2_results) >= l2_budget:
                    break
                rid = r["id"] if isinstance(r, dict) else r.id
                if rid not in l2_exclude:
                    entry = r if isinstance(r, dict) else r.__dict__
                    entry["layer"] = "L2"
                    l2_results.append(entry)

        priming = l0_results + l1_results + l2_results

        return SessionStartResult(
            session_id=session_id,
            priming_memories=priming,
            project=project,
            task=task,
        )

    def _select_l0(self, candidates: list[dict], budget: int) -> list[dict]:
        """L0: preference top-1 + convention top-1 + wildcard top-1."""
        pref = [c for c in candidates if c.get("type") == "preference"]
        conv = [c for c in candidates if c.get("type") == "convention"]

        selected = []
        if pref:
            selected.append(pref[0])  # already sorted by strength DESC
        if conv:
            selected.append(conv[0])

        selected_ids = {m["id"] for m in selected}
        remaining = [c for c in candidates if c["id"] not in selected_ids]
        if remaining and len(selected) < budget:
            selected.append(remaining[0])

        return selected[:budget]

    def _select_l1(self, candidates: list[dict], budget: int,
                   exclude_ids: set) -> list[dict]:
        """L1: decision/fact/insight, top-2 by effective_strength."""
        from datetime import datetime
        from memento.decay import effective_strength as compute_eff_strength
        from memento.rigidity import RIGIDITY_DEFAULTS

        now = datetime.now()
        scored = []
        for c in candidates:
            if c["id"] in exclude_ids:
                continue
            rigidity = c.get("rigidity") or RIGIDITY_DEFAULTS.get(
                c.get("type", "fact"), 0.5
            )
            eff = compute_eff_strength(
                strength=c["strength"],
                last_accessed=c.get("last_accessed", now.isoformat()),
                access_count=c.get("access_count", 0),
                importance=c.get("importance", "normal"),
                now=now,
                rigidity=rigidity,
            )
            if eff >= self.MIN_L1_THRESHOLD:
                c["_eff_strength"] = eff
                scored.append(c)

        # Group by type, take top-1 per type, then global top-budget
        by_type: dict[str, list] = {}
        for c in scored:
            by_type.setdefault(c["type"], []).append(c)

        per_type_tops = []
        for t, group in by_type.items():
            group.sort(key=lambda x: x["_eff_strength"], reverse=True)
            per_type_tops.append(group[0])

        per_type_tops.sort(key=lambda x: x["_eff_strength"], reverse=True)
        result = per_type_tops[:budget]

        # Clean up internal field
        for r in result:
            r.pop("_eff_strength", None)

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_layered_priming.py -v
```
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add src/memento/api.py tests/test_layered_priming.py
git commit -m "feat(priming): implement L0/L1/L2 three-layer priming orchestration"
```

---

### Task 3: MCP Priming Prompt Layer Formatting

**Files:**
- Modify: `src/memento/mcp_server.py:350-412`
- Modify: `tests/test_layered_priming.py`

- [ ] **Step 1: Write failing test for layer-grouped prompt**

Append to `tests/test_layered_priming.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_layered_priming.py::TestMCPPrimingFormat -v
```
Expected: FAIL — `cannot import name 'format_priming_prompt'`

- [ ] **Step 3: Implement `format_priming_prompt()`**

Add to `src/memento/mcp_server.py` (as a module-level function, near the top after imports):

```python
# ── Priming Prompt Formatting ──

_LAYER_LABELS = {
    "L0": "[L0-Identity]",
    "L1": "[L1-Core]",
    "L2": "[L2-Context]",
}


def format_priming_prompt(memories: list[dict]) -> str:
    """Format priming memories into a layer-grouped prompt string."""
    if not memories:
        return ""

    lines = []
    current_layer = None
    for m in memories:
        layer = m.get("layer", "L2")
        if layer != current_layer:
            current_layer = layer
        label = _LAYER_LABELS.get(layer, "[L2-Context]")
        content = m.get("content", "")
        lines.append(f"{label} {content}")

    return "\n".join(lines)
```

Then update the priming prompt generation in `memento_session_start` handler and `memento_generate_priming_prompt` to use `format_priming_prompt()` instead of inline formatting.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_layered_priming.py -v
```
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add src/memento/mcp_server.py tests/test_layered_priming.py
git commit -m "feat(priming): add layer-grouped MCP priming prompt formatting"
```

---

## Feature 2: Local Embedding First

### Task 4: Config Default + Provider Map

**Files:**
- Modify: `src/memento/config.py:38` (provider default)
- Modify: `src/memento/embedding.py:148-153` (provider_map)
- Modify: `tests/test_config.py:81-86`
- Create: `tests/test_local_embedding.py`

- [ ] **Step 1: Write failing tests**

Update `tests/test_config.py` line 85:

```python
# Change:
assert cfg["embedding"]["provider"] is None
# To:
assert cfg["embedding"]["provider"] == "local"
```

Create `tests/test_local_embedding.py`:

```python
"""Tests for local-first embedding (v0.9.2 — Feature 2)."""
from unittest.mock import patch

import pytest


class TestLocalProviderInMap:
    """Verify 'local' is in the provider_map."""

    def test_local_in_provider_map(self):
        from memento.embedding import get_embedding

        # When provider is "local" and sentence-transformers is missing,
        # it should return pending (not crash)
        with patch.dict("os.environ", {}, clear=False):
            with patch("memento.config.get_config", return_value={
                "embedding": {"provider": "local", "api_key": None, "model": None},
                "database": {"path": ":memory:"},
                "llm": {},
            }):
                with patch("memento.embedding._embed_local", return_value=None):
                    blob, dim, pending = get_embedding("test")
                    assert pending is True  # local failed gracefully

    def test_local_provider_returns_embedding(self):
        """When local model works, it returns a valid embedding."""
        fake_vec = [0.1] * 384

        with patch("memento.config.get_config", return_value={
            "embedding": {"provider": "local", "api_key": None, "model": None},
            "database": {"path": ":memory:"},
            "llm": {},
        }):
            with patch("memento.embedding._embed_local", return_value=fake_vec):
                blob, dim, pending = get_embedding("test")
                assert pending is False
                assert dim == 384

    def test_local_skips_cloud_scan(self):
        """When provider is 'local', cloud providers are NOT tried."""
        with patch("memento.config.get_config", return_value={
            "embedding": {"provider": "local", "api_key": None, "model": None},
            "database": {"path": ":memory:"},
            "llm": {},
        }):
            with patch("memento.embedding._embed_local", return_value=[0.1] * 384):
                with patch("memento.embedding._embed_zhipu") as mock_zhipu:
                    get_embedding("test")
                    mock_zhipu.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py::TestDefaultConfig::test_default_embedding_provider tests/test_local_embedding.py -v
```
Expected: FAIL — provider is still None, `"local"` not in provider_map

- [ ] **Step 3: Implement config + provider_map changes**

In `src/memento/config.py:38`, change:
```python
"provider": None,
```
to:
```python
"provider": "local",
```

In `src/memento/embedding.py:148-153`, add `"local"` to provider_map:
```python
provider_map = {
    "zhipu": _embed_zhipu, "minimax": _embed_minimax,
    "moonshot": _embed_moonshot, "openai": _embed_openai,
    "gemini": _embed_gemini,
    "local": _embed_local,
}
```

Note: `_embed_local` doesn't take an `api_key` parameter, so also update the dispatch logic at lines 154-157 to handle this:

```python
provider_fn = provider_map.get(configured_provider)
if provider_fn:
    if configured_provider == "local":
        vec = provider_fn(text)
    else:
        vec = provider_fn(text, api_key=configured_key)
    if vec is not None:
        return vec_to_blob(vec), len(vec), False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py tests/test_local_embedding.py -v
```
Expected: ALL PASSED

- [ ] **Step 5: Commit**

```bash
git add src/memento/config.py src/memento/embedding.py tests/test_config.py tests/test_local_embedding.py
git commit -m "feat(embedding): make local the default provider, add to provider_map"
```

---

### Task 5: Setup Wizard + Doctor Updates

**Files:**
- Modify: `src/memento/cli.py:153-191` (setup wizard embedding section)
- Modify: `src/memento/cli.py:332-403` (doctor command)

- [ ] **Step 1: Update setup wizard embedding menu**

In `src/memento/cli.py`, find the setup wizard's embedding provider menu (around line 153-191) and replace the menu options with:

```python
# ── [2/4] Configure Embedding ──
click.echo("\n[2/4] 配置 Embedding...")
emb_provider = "local"  # default
emb_api_key = None

if yes:
    if embedding_provider:
        emb_provider = embedding_provider
        emb_api_key = embedding_api_key
    # else: default "local" stays
else:
    click.echo("  选择 Embedding 提供商:")
    click.echo("    1) 本地模型（无需 API key，适合快速开始）")
    click.echo("    2) zhipu (智谱)")
    click.echo("    3) openai")
    click.echo("    4) 跳过（仅使用全文搜索）")
    choice = click.prompt("  请选择", type=click.IntRange(1, 4), default=1)
    if choice == 1:
        emb_provider = "local"
        click.echo("  ℹ 本地模型适合快速开始。如主要处理中文内容，")
        click.echo("    建议后续配置云端 provider 以获得更稳定的语义检索质量。")
    elif choice == 2:
        emb_provider = "zhipu"
        emb_api_key = click.prompt("  请输入 Zhipu API Key")
    elif choice == 3:
        emb_provider = "openai"
        emb_api_key = click.prompt("  请输入 OpenAI API Key")
    elif choice == 4:
        emb_provider = "none"
```

- [ ] **Step 2: Update doctor command for provider-aware checks**

In the doctor command's embedding section, update to handle `local` and `none`:

```python
# Embedding provider check
emb_cfg = cfg.get("embedding", {})
provider = emb_cfg.get("provider")

if provider == "local":
    try:
        from sentence_transformers import SentenceTransformer
        click.echo("  ✅ Embedding: local (all-MiniLM-L6-v2, 384d)")
    except ImportError:
        click.echo("  ⚠️  Embedding: local provider configured but "
                    "sentence-transformers not installed.")
        click.echo("     Run: pip install memento[local]")
elif provider == "none":
    click.echo("  ✅ Embedding: skipped (full-text search only)")
elif provider is None:
    click.echo("  ⚠️  Embedding: no provider configured, "
                "run `memento setup` to configure")
elif provider in ("zhipu", "minimax", "moonshot", "openai", "gemini"):
    api_key = emb_cfg.get("api_key")
    if api_key:
        click.echo(f"  ✅ Embedding: {provider} (key: {mask_key(api_key)})")
    else:
        click.echo(f"  ⚠️  Embedding: {provider} configured but API key missing")
else:
    click.echo(f"  ⚠️  Embedding: unknown provider '{provider}'")
```

- [ ] **Step 3: Run existing tests + manual verification**

```bash
pytest tests/ -k "setup or doctor or config" -v
```
Expected: ALL PASSED

- [ ] **Step 4: Commit**

```bash
git add src/memento/cli.py
git commit -m "feat(cli): update setup wizard and doctor for local-first embedding"
```

---

## Feature 3: Temporal Nexus Lifecycle

### Task 6: Database Migration — `invalidated_at` Column

**Files:**
- Modify: `src/memento/migration.py` (add `migrate_v05_to_v092`)
- Create: `tests/test_nexus_lifecycle.py`

- [ ] **Step 1: Write failing tests for migration**

```python
# tests/test_nexus_lifecycle.py
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
    """Tests for migrate_v05_to_v092."""

    def test_adds_invalidated_at_column(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(nexus)").fetchall()}
        assert "invalidated_at" in cols

    def test_existing_nexus_invalidated_at_null(self):
        """Existing nexus records get invalidated_at = NULL (active)."""
        conn = _make_db()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO nexus (id, source_id, target_id, type, "
            "association_strength, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("nex-1", "e1", "e2", "semantic", 0.5, now),
        )
        # Need dummy engrams for FK
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
        conn.commit()

        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)

        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-1'").fetchone()
        assert row["invalidated_at"] is None

    def test_migration_idempotent(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)
        migrate_v05_to_v092(conn)  # second call should not error

    def test_view_nexus_has_invalidated_at(self):
        conn = _make_db()
        from memento.migration import migrate_v05_to_v092
        migrate_v05_to_v092(conn)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(view_nexus)").fetchall()}
        assert "invalidated_at" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_nexus_lifecycle.py::TestNexusMigration -v
```
Expected: FAIL — `cannot import name 'migrate_v05_to_v092'`

- [ ] **Step 3: Implement migration**

Add to `src/memento/migration.py` after `migrate_v03_to_v05`:

```python
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
```

Also wire it into `init_db()` in `src/memento/db.py` (after the existing `migrate_v03_to_v05` call at line 182):

```python
from memento.migration import migrate_v05_to_v092
migrate_v05_to_v092(conn)
```

And into `MementoAPI.__init__` in `src/memento/api.py` (after `migrate_v03_to_v05` call at line 152):

```python
from memento.migration import migrate_v05_to_v092
migrate_v05_to_v092(self.conn)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_nexus_lifecycle.py::TestNexusMigration -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/memento/migration.py src/memento/db.py src/memento/api.py tests/test_nexus_lifecycle.py
git commit -m "feat(nexus): add invalidated_at column via migrate_v05_to_v092"
```

---

### Task 7: Manual Invalidation + Default Query Filtering

**Files:**
- Modify: `src/memento/repository.py:255` (add `invalidate_nexus`)
- Modify: `src/memento/cli.py:1189-1212` (add `--include-invalidated`, filter CTE)
- Modify: `src/memento/mcp_server.py:200-211` (update tool + add new tool)
- Modify: `tests/test_nexus_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_nexus_lifecycle.py`:

```python
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
    """Tests for manual invalidation and default query filtering."""

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

        # Default query: only active
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

        # Include invalidated
        rows = conn.execute(
            "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
            ("e2", "e2"),
        ).fetchall()
        ids = {r["id"] for r in rows}
        assert "nex-1" in ids
        assert "nex-2" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_nexus_lifecycle.py::TestNexusInvalidation -v
```
Expected: FAIL — `cannot import name 'invalidate_nexus'`

- [ ] **Step 3: Implement `invalidate_nexus()` in repository.py**

Add to `src/memento/repository.py`:

```python
def invalidate_nexus(conn: sqlite3.Connection, nexus_id: str) -> bool:
    """Mark a nexus edge as invalidated. Returns True if found and updated."""
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE nexus SET invalidated_at = ? WHERE id = ? AND invalidated_at IS NULL",
        (now, nexus_id),
    )
    changed = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return changed > 0
```

- [ ] **Step 4: Update CLI nexus command to filter invalidated edges**

In `src/memento/cli.py:1179-1230`, add `--include-invalidated` option and filter:

Add the option to the command decorator:
```python
@click.option("--include-invalidated", is_flag=True, default=False,
              help="包含已失效的关联")
```

In the depth=1 query, add filter:
```python
if not include_invalidated:
    rows = conn.execute(
        "SELECT * FROM nexus WHERE (source_id=? OR target_id=?) "
        "AND invalidated_at IS NULL",
        (engram_id, engram_id),
    ).fetchall()
else:
    rows = conn.execute(
        "SELECT * FROM nexus WHERE source_id=? OR target_id=?",
        (engram_id, engram_id),
    ).fetchall()
```

In the depth=2 CTE, add `AND n.invalidated_at IS NULL` to the JOIN condition (unless `include_invalidated`).

- [ ] **Step 5: Update MCP `memento_nexus` tool and add `memento_nexus_invalidate`**

In `src/memento/mcp_server.py`, update the `memento_nexus` tool schema (around line 200-211) to add new properties:

```python
"include_invalidated": {"type": "boolean", "default": False},
"since": {"type": "string", "description": "ISO 8601, filter last_coactivated_at >= since"},
"until": {"type": "string", "description": "ISO 8601, filter last_coactivated_at <= until"},
```

Add new tool definition:
```python
Tool(
    name="memento_nexus_invalidate",
    description="标记一条 nexus 关联为已失效。",
    inputSchema={
        "type": "object",
        "properties": {
            "nexus_id": {"type": "string", "description": "Nexus edge ID"},
        },
        "required": ["nexus_id"],
    },
),
```

Add handler for `memento_nexus_invalidate` in the `call_tool` dispatch:
```python
elif name == "memento_nexus_invalidate":
    nexus_id = arguments["nexus_id"]
    from memento.repository import invalidate_nexus
    success = invalidate_nexus(api.core.conn, nexus_id)
    return [TextContent(
        type="text",
        text=json.dumps({"invalidated": success, "nexus_id": nexus_id}),
    )]
```

Update the `memento_nexus` handler to pass through new filter params:
```python
elif name == "memento_nexus":
    engram_id = arguments["engram_id"]
    depth = arguments.get("depth", 1)
    include_inv = arguments.get("include_invalidated", False)
    since = arguments.get("since")
    until = arguments.get("until")
    inv_filter = "" if include_inv else "AND n.invalidated_at IS NULL"
    time_filters = ""
    time_params = []
    if since:
        time_filters += " AND n.last_coactivated_at >= ?"
        time_params.append(since)
    if until:
        time_filters += " AND n.last_coactivated_at <= ?"
        time_params.append(until)
    # Use inv_filter and time_filters in the nexus query
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_nexus_lifecycle.py -v
```
Expected: ALL PASSED

- [ ] **Step 7: Commit**

```bash
git add src/memento/repository.py src/memento/cli.py src/memento/mcp_server.py tests/test_nexus_lifecycle.py
git commit -m "feat(nexus): add manual invalidation, default active-only filtering"
```

---

### Task 8: Auto-Invalidation in Epoch Phase 4 + Resurrection

**Files:**
- Modify: `src/memento/epoch.py:265-298` (Phase 4 stale-edge scan)
- Modify: `src/memento/repository.py:255-298` (resurrection in `apply_nexus_plan`)
- Modify: `tests/test_nexus_lifecycle.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_nexus_lifecycle.py`:

```python
class TestAutoInvalidation:
    """Tests for Epoch Phase 4 stale-edge auto-invalidation."""

    def test_stale_weak_edge_invalidated(self):
        """Edge with low strength and old coactivation gets invalidated."""
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
        """Edge with high strength is not auto-invalidated even if old."""
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
        """Recent edge is not invalidated even if weak."""
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
    """Tests for edge resurrection on re-coactivation."""

    def test_invalidated_edge_resurrected(self):
        """Coactivation of invalidated edge restores it to active."""
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
        assert row["invalidated_at"] is None  # resurrected
        assert row["association_strength"] == pytest.approx(0.35, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_nexus_lifecycle.py::TestAutoInvalidation tests/test_nexus_lifecycle.py::TestNexusResurrection -v
```
Expected: FAIL — `cannot import name '_auto_invalidate_stale_edges'`

- [ ] **Step 3: Implement auto-invalidation in epoch.py**

Add to `src/memento/epoch.py` (as a standalone function):

```python
# ── Nexus Lifecycle Constants ──
NEXUS_ARCHIVE_THRESHOLD = 0.1
NEXUS_STALE_DAYS = 90


def _auto_invalidate_stale_edges(conn: sqlite3.Connection) -> int:
    """Auto-invalidate weak, stale nexus edges. Returns count of invalidated edges."""
    now = datetime.now()
    cutoff = (now - timedelta(days=NEXUS_STALE_DAYS)).isoformat()

    stale_edges = conn.execute(
        """SELECT id FROM nexus
           WHERE invalidated_at IS NULL
             AND association_strength < ?
             AND last_coactivated_at < ?""",
        (NEXUS_ARCHIVE_THRESHOLD, cutoff),
    ).fetchall()

    now_iso = now.isoformat()
    for edge in stale_edges:
        conn.execute(
            "UPDATE nexus SET invalidated_at = ? WHERE id = ?",
            (now_iso, edge["id"]),
        )

    if stale_edges:
        conn.commit()

    return len(stale_edges)
```

Then call `_auto_invalidate_stale_edges(conn)` at the end of `_phase4_nexus_updates()` (after `apply_nexus_plan`).

- [ ] **Step 4: Implement resurrection in repository.py**

Modify `apply_nexus_plan()` in `src/memento/repository.py:268-289`. Before the `if plan.is_new:` block, add a check for invalidated edges:

```python
for plan in plans:
    # Check for invalidated edge that should be resurrected
    existing_inv = conn.execute(
        "SELECT id, invalidated_at FROM nexus "
        "WHERE source_id=? AND target_id=? AND type=? AND invalidated_at IS NOT NULL",
        (plan.source_id, plan.target_id, plan.type),
    ).fetchone()

    if existing_inv:
        # Resurrect: clear invalidated_at, update strength and coactivation
        conn.execute(
            """UPDATE nexus SET
                invalidated_at = NULL,
                last_coactivated_at = ?,
                association_strength = MIN(association_strength + ?, 1.0)
            WHERE id = ?""",
            (plan.last_coactivated_at, plan.strength_delta, existing_inv["id"]),
        )
    elif plan.is_new:
        # ... existing new nexus creation code ...
    else:
        # ... existing update code ...
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_nexus_lifecycle.py -v
```
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add src/memento/epoch.py src/memento/repository.py tests/test_nexus_lifecycle.py
git commit -m "feat(nexus): add auto-invalidation in epoch + resurrection on coactivation"
```

---

### Task 9: Export/Import `invalidated_at` Support

**Files:**
- Modify: `src/memento/export.py:74-92` (export)
- Modify: `src/memento/export.py:171-211` (import)
- Modify: `tests/test_nexus_lifecycle.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_nexus_lifecycle.py`:

```python
class TestNexusExportImport:
    """Tests for export/import preserving invalidated_at."""

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
        import_memories(core, [], nexus_data)

        row = conn.execute("SELECT invalidated_at FROM nexus WHERE id='nex-imp'").fetchone()
        assert row is not None
        assert row["invalidated_at"] == now
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_nexus_lifecycle.py::TestNexusExportImport -v
```
Expected: FAIL — `invalidated_at` not in exported dict / not in INSERT

- [ ] **Step 3: Update export_nexus()**

In `src/memento/export.py:74-92`, add `invalidated_at` to the exported dict:

```python
return [
    {
        "id": r["id"],
        "source_id": r["source_id"],
        "target_id": r["target_id"],
        "direction": r["direction"],
        "type": r["type"],
        "association_strength": r["association_strength"],
        "created_at": r["created_at"],
        "last_coactivated_at": r["last_coactivated_at"],
        "invalidated_at": r["invalidated_at"],  # NEW
    }
    for r in rows
]
```

- [ ] **Step 4: Update import section**

In `src/memento/export.py:171-211`, update the INSERT to include `invalidated_at`:

```python
core.conn.execute(
    """INSERT OR IGNORE INTO nexus
        (id, source_id, target_id, direction, type,
         association_strength, created_at, last_coactivated_at,
         invalidated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (
        n["id"],
        n["source_id"],
        n["target_id"],
        n.get("direction", "directed"),
        n["type"],
        n.get("association_strength", 0.5),
        n.get("created_at", datetime.now().isoformat()),
        n.get("last_coactivated_at"),
        n.get("invalidated_at"),  # NEW — preserves None or ISO string
    ),
)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_nexus_lifecycle.py -v
```
Expected: ALL PASSED

- [ ] **Step 6: Commit**

```bash
git add src/memento/export.py tests/test_nexus_lifecycle.py
git commit -m "feat(nexus): export/import preserves invalidated_at field"
```

---

### Task 10: Final Integration — Run Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: ALL PASSED (or only pre-existing failures unrelated to v0.9.2)

- [ ] **Step 2: Verify no import cycles**

```bash
python -c "from memento.api import MementoAPI; print('OK')"
python -c "from memento.mcp_server import format_priming_prompt; print('OK')"
python -c "from memento.migration import migrate_v05_to_v092; print('OK')"
```
Expected: All print "OK"

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git status
# If clean, skip. Otherwise fix and commit.
```

- [ ] **Step 4: Tag version**

```bash
# Only after all tests pass
git tag v0.9.2
```
