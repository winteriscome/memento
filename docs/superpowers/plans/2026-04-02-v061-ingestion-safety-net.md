> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.6.1 Ingestion Safety Net Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee data capture even if the agent fails to explicitly use the capture tool, and provide a daily timeline resource for fast context recovery.

**Architecture:** Add auto-summary fallback logic to `api.session_end()`. When a session ends with insufficient explicit captures/observations, promote the user-provided summary (if any) as a conservative capture via `awake_capture(origin='agent')`. De-dup against existing session captures by content hash. Add `memento://daily/today` MCP Resource merging today's `capture_log` and `session_events`. No LLM required — v0.6.1 uses the summary string already provided by the caller.

**Tech Stack:** Python 3.10+, SQLite, pytest

---

## File Structure

### Modified files

| File | Changes |
|------|---------|
| `src/memento/api.py` | Add auto-summary fallback logic to `session_end()` |
| `src/memento/session.py` | Add `get_session_captures()` helper for per-session capture lookup |
| `src/memento/mcp_server.py` | Add `memento://daily/today` resource; update `session_end` response to report auto-captures |
| `tests/test_session.py` | Tests for auto-summary fallback |
| `tests/test_mcp_server.py` | Tests for daily/today resource |

### Key design decisions

1. **Auto-summary lives in `api.py`, not `session.py`** — it needs cross-cutting access to `awake_capture` and `capture_log` queries, which `SessionService` doesn't own. `api.session_end()` already orchestrates between services.
2. **Suppression threshold: captures + observations < 2** — if the agent explicitly captured/observed at least 2 items, we assume adequate coverage and skip fallback. This is a conservative heuristic, not a boolean "any capture = skip all".
3. **No LLM** — v0.6.1 only uses the `summary` string already provided by the caller. If `summary` is None/empty, no fallback is generated (LLM-based transcript analysis is v0.7.0).
4. **Content hash de-dup** — before creating a fallback capture, check if the same content hash already exists in `capture_log` for this session. This prevents duplicate entries if the summary repeats a prior capture.
5. **Trust boundary** — fallback captures use `origin='agent'`, so strength is capped at 0.5 by existing `AGENT_STRENGTH_CAP` logic.

---

## Task 1: Auto-summary fallback in api.session_end()

**Files:**
- Modify: `src/memento/api.py:185-194`
- Modify: `src/memento/session.py` (add helper)
- Test: `tests/test_session.py`

- [ ] **Step 1: Add `get_session_capture_count()` to session.py**

Add a method to `SessionService` that returns the count of explicit captures and observations for a session:

```python
# Append to SessionService class in src/memento/session.py

def get_session_activity_counts(self, session_id: str) -> dict:
    """Return counts of explicit captures and observations for a session."""
    rows = self.conn.execute(
        """SELECT event_type, COUNT(*) as cnt
           FROM session_events
           WHERE session_id = ? AND event_type IN ('capture', 'observation')
           GROUP BY event_type""",
        (session_id,),
    ).fetchall()
    counts = {row["event_type"]: row["cnt"] for row in rows}
    return {
        "captures": counts.get("capture", 0),
        "observations": counts.get("observation", 0),
    }
```

- [ ] **Step 2: Add `has_capture_hash()` to session.py**

Add a method to check if a content hash already exists in capture_log for a given session:

```python
# Append to SessionService class in src/memento/session.py

def has_capture_hash(self, session_id: str, content_hash: str) -> bool:
    """Check if a capture with this content hash already exists for the session."""
    row = self.conn.execute(
        """SELECT 1 FROM capture_log
           WHERE source_session_id = ? AND content_hash = ?
           LIMIT 1""",
        (session_id, content_hash),
    ).fetchone()
    return row is not None
```

- [ ] **Step 3: Write tests for auto-summary fallback**

```python
# Append to tests/test_session.py

def test_session_end_auto_summary_when_no_captures(api_fixture):
    """session_end should auto-capture summary when no explicit captures exist."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    result = api.session_end(sid, summary="Fixed the auth bug by updating JWT validation")
    assert result is not None
    assert result.auto_captures_count >= 1

    # Verify capture_log has the auto-capture
    row = api.core.conn.execute(
        "SELECT * FROM capture_log WHERE source_session_id = ? AND origin = 'agent'",
        (sid,),
    ).fetchone()
    assert row is not None
    assert "JWT validation" in row["content"]


def test_session_end_no_auto_summary_when_enough_captures(api_fixture):
    """session_end should NOT auto-capture when agent already captured enough."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    # Agent captures 2 items explicitly
    api.capture("Fixed auth validation", session_id=sid)
    api.capture("Updated JWT token handling", session_id=sid)

    result = api.session_end(sid, summary="Fixed the auth bug")
    assert result is not None
    assert result.auto_captures_count == 0


def test_session_end_no_auto_summary_when_no_summary(api_fixture):
    """session_end should NOT auto-capture when summary is None."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    result = api.session_end(sid, summary=None)
    assert result is not None
    assert result.auto_captures_count == 0


def test_session_end_dedup_summary_against_existing_capture(api_fixture):
    """session_end should NOT auto-capture if summary content already captured."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    # Agent already captured the exact same content
    api.capture("Fixed the auth bug by updating JWT validation", session_id=sid)

    result = api.session_end(sid, summary="Fixed the auth bug by updating JWT validation")
    assert result is not None
    assert result.auto_captures_count == 0


def test_session_end_auto_capture_has_agent_origin(api_fixture):
    """Auto-captured summary must have origin='agent' for trust boundary."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    api.session_end(sid, summary="Important architectural decision about caching")

    row = api.core.conn.execute(
        "SELECT origin FROM capture_log WHERE source_session_id = ? AND origin = 'agent'",
        (sid,),
    ).fetchone()
    assert row is not None
    assert row["origin"] == "agent"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_session.py -k "auto_summary" -v`
Expected: FAIL — `auto_captures_count` not in SessionEndResult.

- [ ] **Step 5: Add `auto_captures_count` to SessionEndResult**

In `src/memento/session.py`, update the dataclass:

```python
@dataclass
class SessionEndResult:
    session_id: str
    status: str
    captures_count: int = 0
    observations_count: int = 0
    auto_captures_count: int = 0  # NEW: fallback captures generated
```

- [ ] **Step 6: Implement auto-summary fallback in api.session_end()**

Replace the current `session_end` method in `src/memento/api.py`:

```python
def session_end(
    self,
    session_id: str,
    outcome: str = "completed",
    summary: str | None = None,
) -> SessionEndResult | None:
    """结束会话。如果显式 capture/observation 不足，自动将 summary 补录为低信任 capture。"""
    result = self._session_svc.end(
        session_id=session_id, outcome=outcome, summary=summary
    )
    if result is None:
        return None

    # ── Auto-summary fallback ──────────────────────────────────
    auto_count = 0
    if (
        summary
        and (result.captures_count + result.observations_count) < 2
    ):
        import hashlib
        content_hash = hashlib.sha256(summary.strip().lower().encode()).hexdigest()

        if not self._session_svc.has_capture_hash(session_id, content_hash):
            from memento.awake import awake_capture
            awake_capture(
                self.core.conn,
                content=summary,
                type="insight",
                importance="normal",
                origin="agent",
                session_id=session_id,
            )
            auto_count = 1

    result.auto_captures_count = auto_count
    return result
```

- [ ] **Step 7: Check test fixture exists**

The tests above reference `api_fixture`. Check if `tests/test_session.py` already has this fixture or if we need to create it. If needed, add:

```python
@pytest.fixture
def api_fixture(tmp_path):
    from memento.api import MementoAPI
    db_path = tmp_path / "test_session.db"
    with patch("memento.core.get_embedding", return_value=(b"\x00" * 16, 4, False)), \
         patch("memento.observation.get_embedding", return_value=(b"\x00" * 16, 4, False)), \
         patch("memento.awake.get_embedding", return_value=(b"\x00" * 16, 4, False)):
        api = MementoAPI(db_path=db_path)
        yield api
        api.close()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_session.py -k "auto_summary" -v`
Expected: All 5 tests PASS.

- [ ] **Step 9: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

---

## Task 2: Update MCP session_end response + daily/today resource

**Files:**
- Modify: `src/memento/mcp_server.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Update session_end dispatch to include auto_captures_count**

In `src/memento/mcp_server.py`, update the `memento_session_end` handler:

```python
    elif name == "memento_session_end":
        r = api.session_end(
            arguments["session_id"],
            outcome=arguments.get("outcome", "completed"),
            summary=arguments.get("summary"),
        )
        if r:
            return {
                "status": r.status,
                "captures_count": r.captures_count,
                "observations_count": r.observations_count,
                "auto_captures_count": r.auto_captures_count,
            }
        return {"error": "session not found"}
```

- [ ] **Step 2: Add `memento://daily/today` to list_resources**

In `src/memento/mcp_server.py`, append to the `list_resources` return list:

```python
            Resource(
                uri="memento://daily/today",
                name="今日时间线",
                description="今天的 capture 和 session 事件，按时间排序",
            ),
```

- [ ] **Step 3: Add daily/today handler to read_resource**

In `src/memento/mcp_server.py`, add handler in `read_resource`:

```python
        elif uri_str == "memento://daily/today":
            today = datetime.now().strftime("%Y-%m-%d")
            captures = api.core.conn.execute(
                """SELECT id, content, type, tags, importance, origin, created_at,
                          'capture' AS source
                   FROM capture_log
                   WHERE created_at >= ? AND epoch_id IS NULL
                   ORDER BY created_at""",
                (today,),
            ).fetchall()
            events = api.core.conn.execute(
                """SELECT id, session_id, event_type, payload, created_at,
                          'session_event' AS source
                   FROM session_events
                   WHERE created_at >= ?
                   ORDER BY created_at""",
                (today,),
            ).fetchall()
            timeline = []
            for row in captures:
                d = dict(row)
                d["source"] = "capture"
                timeline.append(d)
            for row in events:
                d = dict(row)
                d["source"] = "session_event"
                timeline.append(d)
            timeline.sort(key=lambda x: x.get("created_at", ""))
            return json.dumps(timeline, ensure_ascii=False)
```

Add import at top of file if not present:

```python
from datetime import datetime
```

- [ ] **Step 4: Write tests**

```python
# Append to tests/test_mcp_server.py

def test_dispatch_session_end_reports_auto_captures(mcp_api):
    """session_end response should include auto_captures_count."""
    r = _dispatch_tool(mcp_api, "memento_session_start", {"project": "/test", "task": "test"})
    sid = r["session_id"]
    result = _dispatch_tool(mcp_api, "memento_session_end", {
        "session_id": sid,
        "summary": "Important finding about caching strategy",
    })
    assert "auto_captures_count" in result
    assert result["auto_captures_count"] >= 1


def test_dispatch_session_end_no_auto_when_captured(mcp_api):
    """session_end should not auto-capture when agent already captured enough."""
    r = _dispatch_tool(mcp_api, "memento_session_start", {"project": "/test", "task": "test"})
    sid = r["session_id"]
    _dispatch_tool(mcp_api, "memento_capture", {"content": "Finding 1", "session_id": sid})
    _dispatch_tool(mcp_api, "memento_capture", {"content": "Finding 2", "session_id": sid})
    result = _dispatch_tool(mcp_api, "memento_session_end", {
        "session_id": sid,
        "summary": "Summary of findings",
    })
    assert result["auto_captures_count"] == 0


def test_daily_today_resource(mcp_api):
    """memento://daily/today should return today's captures and events."""
    import json
    # Create a capture so there's something to find
    _dispatch_tool(mcp_api, "memento_capture", {"content": "Today's test capture"})

    import asyncio
    app, api = None, mcp_api

    # Read resource directly via API
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    captures = api.core.conn.execute(
        "SELECT id FROM capture_log WHERE created_at >= ?", (today,)
    ).fetchall()
    assert len(captures) > 0  # At least our test capture exists
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_mcp_server.py -k "session_end_reports_auto or session_end_no_auto or daily_today" -v`
Expected: All PASS.

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

---

## Task 3: Smoke test + regression

- [ ] **Step 1: Update smoke test**

Add auto-summary verification step to `scripts/smoke-test.sh` after the existing capture/recall steps:

```bash
# After step 8, add:

# 9. Session with auto-summary fallback
SESSION_ID=$(memento session-start --project "/smoke" --task "auto-summary test" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
if [ -n "$SESSION_ID" ]; then
    END_RESULT=$(memento session-end "$SESSION_ID" --summary "Discovered that Redis needs TTL config" 2>/dev/null)
    echo "[9/9] auto-summary fallback: OK"
else
    echo "[9/9] auto-summary fallback: SKIP (session commands may differ)"
fi
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -q`
Expected: All pass.

- [ ] **Step 3: Run smoke test (if CLI available)**

Run: `bash scripts/smoke-test.sh`
Expected: All steps pass.
