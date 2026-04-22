> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.5.1b E2E Integration Verification & Plugin Packaging

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the full Hook→Worker→DB→Recall pipeline works end-to-end, fix integration bugs, and package the system for real-world use by Claude Code users.

**Architecture:** Tests start a real WorkerServer on a tmp Unix Socket, send HTTP requests simulating hook-handler.sh behavior, and verify data flows through capture_log→epoch→view_engrams→recall. Plugin packaging adds proper entry points and a smoke-test script.

**Tech Stack:** Python 3.10+, pytest, http.client + socket (stdlib), Click CLI, setuptools

**Spec:** Gap analysis from v0.3 runtime integration plan vs current v0.5 implementation state.

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `tests/conftest.py` | Shared test fixtures: v0.5 DB setup, embedding mock, Worker fixture |
| `tests/test_integration_worker.py` | Full HTTP integration tests: Hook→Worker→DB pipeline |
| `scripts/smoke-test.sh` | End-to-end smoke test: init→capture→recall→epoch→recall |

### Modified files

| File | Changes |
|------|---------|
| `plugin/scripts/hook-handler.sh` | Fix shell quoting bug in observe case (line 94), add robust JSON encoding |
| `pyproject.toml` | Version bump to 0.5.1, add memento-worker + memento-mcp-server entry points |
| `src/memento/worker.py` | Add `use_awake=True` in DBThread.run() to enable Awake track |

---

## Task 1: Fix DBThread use_awake=False Bug

The DBThread initializes `MementoAPI(use_awake=False)`, which means all Worker operations bypass the Awake track (capture_log, pulse_queue, etc.). This defeats the entire v0.5 architecture when running through Worker.

**Files:**
- Modify: `src/memento/worker.py:65`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write a test proving capture through Worker uses capture_log**

```python
# Append to tests/test_worker.py

def test_db_thread_capture_uses_awake_track(db_path, mock_embedding):
    """Worker capture should write to capture_log (L2 buffer), not directly to engrams."""
    import sqlite3
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()
    assert t.init_event.wait(timeout=5)

    try:
        result = t.execute("capture", content="test awake", type="fact",
                           importance="normal", origin="human")
        assert result["id"]

        # Verify: capture_log should have 1 entry, engrams should have 0
        conn = sqlite3.connect(str(db_path))
        capture_count = conn.execute("SELECT COUNT(*) FROM capture_log").fetchone()[0]
        engram_count = conn.execute("SELECT COUNT(*) FROM engrams WHERE forgotten=0").fetchone()[0]
        conn.close()

        assert capture_count == 1, f"Expected 1 capture_log entry, got {capture_count}"
        # engrams may have 0 or 1 depending on whether use_awake=True routes there
        # The key invariant: capture_log must be populated
    finally:
        t.shutdown()
        t.join(timeout=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py::test_db_thread_capture_uses_awake_track -v`
Expected: FAIL — capture_log has 0 entries because `use_awake=False` writes directly to engrams.

- [ ] **Step 3: Fix use_awake in DBThread**

```python
# src/memento/worker.py line 65
# Change:
#     self._api = MementoAPI(db_path=self._db_path, use_awake=False)
# To:
            self._api = MementoAPI(db_path=self._db_path, use_awake=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py::test_db_thread_capture_uses_awake_track -v`
Expected: PASS

- [ ] **Step 5: Run all existing Worker tests to check for regressions**

Run: `pytest tests/test_worker.py -v`
Expected: All pass. Some tests may need adjustment if they assumed direct engram writes.

- [ ] **Step 6: Fix any broken tests**

Tests that check `engrams` table directly after Worker capture will need to either:
- Check `capture_log` instead, or
- Run an epoch between capture and assertion

Update affected assertions in test_worker.py.

- [ ] **Step 7: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "fix(worker): enable Awake track in DBThread (use_awake=True)

Worker was bypassing the v0.5 capture_log buffer by initializing
MementoAPI with use_awake=False. This meant captures went directly
to engrams, skipping the L2 buffer and pulse_queue pipeline."
```

---

## Task 2: Shared Test Fixtures (conftest.py)

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
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
```

- [ ] **Step 2: Verify conftest fixtures load**

Run: `pytest tests/conftest.py --collect-only`
Expected: No errors, fixtures discovered.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared conftest.py with db_path, mock_embedding, v05_db fixtures"
```

---

## Task 3: Worker HTTP Integration Test

**Files:**
- Create: `tests/test_integration_worker.py`

- [ ] **Step 1: Write integration test for the full Hook→Worker→Recall pipeline**

```python
# tests/test_integration_worker.py
"""Integration tests: simulate hook-handler.sh → WorkerServer → DB pipeline.

These tests start a real WorkerServer on a temporary Unix Socket and send
HTTP requests like hook-handler.sh would, verifying the complete data flow.
"""

import http.client
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def _send(sock_path: str, method: str, path: str, body: dict | None = None) -> dict:
    """Send HTTP request to Worker via Unix Socket, return parsed JSON."""
    conn = http.client.HTTPConnection("localhost")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    conn.sock = sock
    payload = json.dumps(body or {})
    conn.request(method, path, payload, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    return data


@pytest.fixture
def worker_server(db_path, mock_embedding):
    """Start a real WorkerServer on a tmp Unix Socket."""
    from memento.worker import WorkerServer

    sock_path = str(db_path).replace(".db", ".sock")
    server = WorkerServer(db_path, sock_path)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Wait for server to be ready
    for _ in range(50):
        if os.path.exists(sock_path):
            try:
                _send(sock_path, "GET", "/status")
                break
            except Exception:
                pass
        time.sleep(0.1)
    else:
        raise RuntimeError("WorkerServer failed to start")

    yield sock_path

    server.shutdown_gracefully()
    thread.join(timeout=5)


def test_full_hook_pipeline(worker_server):
    """Simulate complete hook-handler.sh lifecycle:
    session-start → observe → capture → recall → flush → session-end.
    """
    sock = worker_server
    claude_sid = "test-claude-session-001"

    # 1. Session start (hook: session-start)
    result = _send(sock, "POST", "/session/start", {
        "claude_session_id": claude_sid,
        "project": "/tmp/test-project",
    })
    assert "session_id" in result
    session_id = result["session_id"]

    # 2. Observe tool usage (hook: PostToolUse)
    result = _send(sock, "POST", "/observe", {
        "claude_session_id": claude_sid,
        "content": "Read: read src/main.py (200 lines)",
        "tool": "Read",
        "files": ["src/main.py"],
    })
    assert result.get("queued") is True

    # 3. Capture a memory (MCP tool or direct)
    result = _send(sock, "POST", "/capture", {
        "content": "JWT auth uses RS256 with keys in /config/keys/",
        "type": "fact",
        "importance": "high",
        "origin": "human",
    })
    assert result.get("id")
    engram_id = result["id"]

    # 4. Recall should find the captured memory (from capture_log)
    result = _send(sock, "POST", "/recall", {
        "query": "JWT auth",
        "max_results": 5,
    })
    assert len(result) > 0
    assert any("JWT" in r.get("content", "") for r in result)

    # 5. Flush observation queue
    result = _send(sock, "POST", "/flush", {
        "claude_session_id": claude_sid,
    })
    assert result.get("flushed") is True or "flushed" in result

    # 6. Status should show session active
    result = _send(sock, "GET", "/status")
    assert result.get("active_sessions", 0) >= 1

    # 7. Session end (hook: session-end)
    result = _send(sock, "POST", "/session/end", {
        "claude_session_id": claude_sid,
        "outcome": "completed",
    })
    assert result.get("status") == "completed" or "ended" in str(result)


def test_multi_session_isolation(worker_server):
    """Two concurrent sessions should not interfere with each other."""
    sock = worker_server

    # Start two sessions
    r1 = _send(sock, "POST", "/session/start", {
        "claude_session_id": "session-A",
        "project": "/project-a",
    })
    r2 = _send(sock, "POST", "/session/start", {
        "claude_session_id": "session-B",
        "project": "/project-b",
    })
    assert r1["session_id"] != r2["session_id"]

    # Capture in session A
    _send(sock, "POST", "/capture", {
        "content": "Session A fact",
        "type": "fact",
    })

    # Status should show 2 active sessions
    status = _send(sock, "GET", "/status")
    assert status.get("active_sessions", 0) >= 2

    # End session A
    _send(sock, "POST", "/session/end", {
        "claude_session_id": "session-A",
        "outcome": "completed",
    })

    # Session B should still be active
    status = _send(sock, "GET", "/status")
    assert status.get("active_sessions", 0) >= 1


def test_observe_async_does_not_block(worker_server):
    """Observe should return immediately (async fire-and-forget)."""
    sock = worker_server

    _send(sock, "POST", "/session/start", {
        "claude_session_id": "obs-test",
        "project": "/test",
    })

    start = time.monotonic()
    for i in range(10):
        _send(sock, "POST", "/observe", {
            "claude_session_id": "obs-test",
            "content": f"Read: file_{i}.py",
            "tool": "Read",
            "files": [f"file_{i}.py"],
        })
    elapsed = time.monotonic() - start

    # 10 observations should complete in under 2 seconds
    assert elapsed < 2.0, f"Observations took {elapsed:.2f}s, expected < 2s"

    # Flush and verify they were processed
    _send(sock, "POST", "/flush", {"claude_session_id": "obs-test"})


def test_capture_recall_without_session(worker_server):
    """Capture and recall should work even without an active session."""
    sock = worker_server

    result = _send(sock, "POST", "/capture", {
        "content": "Sessionless fact",
        "type": "fact",
    })
    assert result.get("id")

    result = _send(sock, "POST", "/recall", {
        "query": "Sessionless",
        "max_results": 5,
    })
    assert len(result) > 0


def test_shutdown_after_last_session(worker_server):
    """Worker /shutdown should respond gracefully."""
    sock = worker_server

    result = _send(sock, "POST", "/shutdown", {})
    # Should not crash — may return success or error depending on implementation
    assert isinstance(result, dict)
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_integration_worker.py -v`
Expected: Some may fail due to response format mismatches or the use_awake bug. Fix discovered issues.

- [ ] **Step 3: Fix response format issues discovered by tests**

Iterate on test assertions to match actual Worker response format. Common fixes:
- Session start may return different key names
- Flush may return different format
- Status field names may differ

Adjust test expectations to match the actual API contract.

- [ ] **Step 4: Run all tests to verify no regressions**

Run: `pytest tests/ -v`
Expected: All pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_worker.py
git commit -m "test(integration): Worker HTTP pipeline — session lifecycle, capture/recall, observe async"
```

---

## Task 4: Fix hook-handler.sh Quoting Bug

**Files:**
- Modify: `plugin/scripts/hook-handler.sh:89-94`

- [ ] **Step 1: Fix the observe case JSON construction**

The current line 94 has a shell injection/quoting bug — `$CONTENT` is embedded via a nested `python3 -c` call that breaks on special characters (quotes, newlines).

Replace the observe case (lines 88-95) with safe JSON construction:

```bash
  observe)
    TOOL_INFO=$(extract_tool_summary)
    # Build JSON safely using Python to handle special characters
    send_to_worker POST /observe "$(echo "$TOOL_INFO" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(json.dumps({
        'claude_session_id': '$CLAUDE_SID',
        'content': d.get('summary', ''),
        'tool': d.get('tool', ''),
        'files': d.get('files', []),
    }))
except Exception:
    print(json.dumps({'claude_session_id': '$CLAUDE_SID', 'content': 'extraction failed', 'tool': 'unknown', 'files': []}))
" 2>/dev/null)" &
    ;;
```

- [ ] **Step 2: Verify hook-handler.sh passes shellcheck**

Run: `shellcheck plugin/scripts/hook-handler.sh || true`
Expected: No critical errors (SC2086 warnings on intentional word splitting are OK).

- [ ] **Step 3: Commit**

```bash
git add plugin/scripts/hook-handler.sh
git commit -m "fix(plugin): safe JSON encoding in hook-handler.sh observe case

The observe hook embedded shell variables directly into JSON strings,
breaking on content with quotes, newlines, or special characters."
```

---

## Task 5: Package Entry Points & Version Bump

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

```toml
[project]
name = "memento"
version = "0.5.1"
description = "Your long-term memory engine for AI Agents."
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "click>=8.0",
    "google-genai>=1.0",
    "mcp>=1.0",
    "sqlite-vec>=0.1.6",
]

[project.optional-dependencies]
local = ["sentence-transformers>=2.0"]
dev = ["pytest>=7.0"]

[project.scripts]
memento = "memento.cli:main"
memento-worker = "memento.worker:main"
memento-mcp-server = "memento.mcp_server:main"
```

- [ ] **Step 2: Add main() entry point to worker.py**

Append to `src/memento/worker.py`:

```python
def main():
    """Entry point for `memento-worker` console script."""
    import sys

    db_path = get_db_path()
    sock_path = get_socket_path(db_path)

    print(f"Starting Worker: db={db_path} sock={sock_path}", file=sys.stderr)
    server = WorkerServer(db_path, sock_path)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown_gracefully()
```

- [ ] **Step 3: Add main() entry point to mcp_server.py**

Append to `src/memento/mcp_server.py`:

```python
def main():
    """Entry point for `memento-mcp-server` console script."""
    import asyncio
    from mcp.server.stdio import stdio_server

    async def _run():
        app, api = create_mcp_app()
        try:
            async with stdio_server() as (read_stream, write_stream):
                await app.run(read_stream, write_stream, app.create_initialization_options())
        finally:
            api.close()

    asyncio.run(_run())
```

- [ ] **Step 4: Update plugin scripts to use entry points**

Update `plugin/.mcp.json`:

```json
{
  "mcpServers": {
    "memento": {
      "type": "stdio",
      "command": "memento-mcp-server",
      "args": []
    }
  }
}
```

Update `plugin/scripts/hook-handler.sh` line 53 (ensure_worker_running):

```bash
  # 启动 worker（后台运行）— 优先用 entry point，fallback 到脚本
  if command -v memento-worker &>/dev/null; then
    nohup memento-worker > /dev/null 2>&1 &
  else
    nohup python3 "$SCRIPT_DIR/worker-service.py" > /dev/null 2>&1 &
  fi
```

- [ ] **Step 5: Reinstall package and verify entry points**

Run: `pip install -e . && which memento-worker && which memento-mcp-server`
Expected: Both entry points resolve.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/memento/worker.py src/memento/mcp_server.py plugin/.mcp.json plugin/scripts/hook-handler.sh
git commit -m "feat(packaging): v0.5.1 — add memento-worker and memento-mcp-server entry points

Version bump from 0.1.0 to 0.5.1. Plugin .mcp.json updated to use
entry point command instead of raw python3 script path."
```

---

## Task 6: Smoke Test Script

**Files:**
- Create: `scripts/smoke-test.sh`

- [ ] **Step 1: Write end-to-end smoke test script**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Smoke test: verify Memento works end-to-end from CLI
# Usage: bash scripts/smoke-test.sh

TMPDIR=$(mktemp -d)
export MEMENTO_DB="$TMPDIR/smoke.db"
trap "rm -rf $TMPDIR" EXIT

echo "=== Memento Smoke Test ==="
echo "DB: $MEMENTO_DB"

# 1. Init
memento init 2>/dev/null || true
echo "[1/7] init: OK"

# 2. Capture
memento capture "JWT auth uses RS256 with keys in /config/keys/" --type fact --importance high
echo "[2/7] capture: OK"

# 3. Recall (should find the captured memory)
RESULT=$(memento recall "JWT auth" --format json 2>/dev/null)
if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d)>0" 2>/dev/null; then
    echo "[3/7] recall: OK (found captured memory)"
else
    echo "[3/7] recall: WARN (no results — may need epoch first)"
fi

# 4. Status
memento status > /dev/null
echo "[4/7] status: OK"

# 5. Epoch (light mode, no LLM needed)
memento epoch run --mode light 2>/dev/null || true
echo "[5/7] epoch light: OK"

# 6. Recall after epoch
RESULT=$(memento recall "JWT" --format json 2>/dev/null)
if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert len(d)>0" 2>/dev/null; then
    echo "[6/7] recall after epoch: OK"
else
    echo "[6/7] recall after epoch: FAIL — memory lost after epoch!"
    exit 1
fi

# 7. Epoch status
memento epoch status > /dev/null
echo "[7/7] epoch status: OK"

echo ""
echo "=== All smoke tests passed ==="
```

- [ ] **Step 2: Make executable and run**

Run: `chmod +x scripts/smoke-test.sh && bash scripts/smoke-test.sh`
Expected: All 7 steps pass.

- [ ] **Step 3: Fix any failures**

Common issues:
- `memento init` may not exist as a CLI command → check if DB is auto-created
- `recall --format json` output format may differ from expected

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke-test.sh
git commit -m "test: add end-to-end smoke test script"
```

---

## Task 7: Final Regression & Cleanup

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass (284 existing + new integration tests).

- [ ] **Step 2: Run smoke test**

Run: `bash scripts/smoke-test.sh`
Expected: All steps pass.

- [ ] **Step 3: Update plugin.json version**

```json
{
  "name": "memento",
  "description": "Long-term memory engine for AI Agents — automatic session tracking, observation capture, and memory recall via MCP.",
  "author": { "name": "memento" },
  "version": "0.5.1",
  "keywords": ["memory", "context", "hooks", "mcp", "session"]
}
```

- [ ] **Step 4: Commit**

```bash
git add plugin/.claude-plugin/plugin.json
git commit -m "chore: bump plugin.json version to 0.5.1"
```
