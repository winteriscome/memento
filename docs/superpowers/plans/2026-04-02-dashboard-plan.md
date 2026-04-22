# Memento Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Web Dashboard to Memento for browsing, searching, and managing memories via a browser UI.

**Architecture:** FastAPI backend serving Vue 3 SPA (no build step, local vendor files). Backend uses `LocalAPI` from `src/memento/api.py` for all data access. CLI entry via `memento dashboard` command.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, Vue 3 (CDN-free local vendor), Vue Router (hash mode), vanilla CSS.

**Spec:** `docs/superpowers/specs/2026-04-02-dashboard-design.md`

---

## File Structure

```
src/memento/dashboard/
├── __init__.py          # Package init
├── server.py            # FastAPI app creation + uvicorn launcher
├── routes.py            # All API route handlers
└── static/
    ├── index.html       # SPA entry point
    ├── app.js           # Vue 3 application
    ├── style.css        # Styles
    └── vendor/
        ├── vue.global.prod.js         # Vue 3.5.x production build
        └── vue-router.global.prod.js  # Vue Router 4.x production build
```

Existing files modified:
- `src/memento/cli.py` — add `dashboard` subcommand
- `src/memento/api.py` — add `list_engrams()` and `list_pending_captures()` methods
- `pyproject.toml` — add `[dashboard]` optional dependency + update `package-data`

Test files:
- `tests/test_dashboard.py` — API route tests

---

## Phase 1: Infrastructure

### Task 1: Add dashboard optional dependency and package-data

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

Add `dashboard` optional dependency group and update package-data:

```toml
[project.optional-dependencies]
local = ["sentence-transformers>=2.0"]
dev = ["pytest>=7.0"]
dashboard = ["fastapi>=0.100", "uvicorn[standard]>=0.20"]

[tool.setuptools.package-data]
memento = ["scripts/*.sh", "dashboard/static/**"]
```

- [ ] **Step 2: Install dashboard dependencies**

Run: `cd /Users/maizi/data/work/memento && pip install -e ".[dashboard]"`
Expected: Successfully installed fastapi and uvicorn

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat(dashboard): add optional dependency group and package-data"
```

---

### Task 2: Create dashboard package skeleton and FastAPI server

**Files:**
- Create: `src/memento/dashboard/__init__.py`
- Create: `src/memento/dashboard/server.py`
- Create: `src/memento/dashboard/routes.py`

- [ ] **Step 1: Write the test**

Create `tests/test_dashboard.py`:

```python
"""Dashboard API route tests."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """Create a FastAPI test client with a temporary database."""
    import tempfile
    import os
    from pathlib import Path
    from memento.db import get_connection, init_db

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()

        with patch.dict(os.environ, {"MEMENTO_DB": str(db_path)}):
            from memento.dashboard.server import create_app
            from fastapi.testclient import TestClient
            app = create_app()
            yield TestClient(app)


def test_app_serves_index(client):
    """GET / should return the SPA index.html."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Memento" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_app_serves_index -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'memento.dashboard'`

- [ ] **Step 3: Create the package files**

Create `src/memento/dashboard/__init__.py`:

```python
"""Memento Web Dashboard — local management panel."""
```

Create `src/memento/dashboard/routes.py`:

```python
"""Dashboard API routes."""
from fastapi import APIRouter, HTTPException

from memento.api import LocalAPI

router = APIRouter(prefix="/api")


def _get_api() -> LocalAPI:
    """Create a LocalAPI instance for the request."""
    return LocalAPI()


@router.get("/status")
def get_status():
    """System status (equivalent to `memento status`)."""
    api = _get_api()
    stats = api.status()
    api.close()
    return {
        "total": stats.total,
        "active": stats.active,
        "forgotten": stats.forgotten,
        "unverified_agent": stats.unverified_agent,
        "with_embedding": stats.with_embedding,
        "pending_embedding": stats.pending_embedding,
        "total_sessions": stats.total_sessions,
        "active_sessions": stats.active_sessions,
        "completed_sessions": stats.completed_sessions,
        "total_observations": stats.total_observations,
        "by_state": stats.by_state,
        "pending_capture": stats.pending_capture,
        "pending_delta": stats.pending_delta,
        "cognitive_debt_count": stats.cognitive_debt_count,
        "last_epoch_committed_at": stats.last_epoch_committed_at,
    }
```

Create `src/memento/dashboard/server.py`:

```python
"""FastAPI application and server launcher."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from memento.dashboard.routes import router

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Memento Dashboard", version="0.1.0")
    app.include_router(router)

    # Serve static files (Vue SPA)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


def run_server(port: int = 8230, open_browser: bool = True):
    """Start the dashboard server."""
    import uvicorn
    import webbrowser
    import threading

    url = f"http://localhost:{port}"

    if open_browser:
        # Open browser after a short delay to let server start
        def _open():
            import time
            time.sleep(1)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    print(f"🧠 Memento Dashboard: {url}")
    print("   Press Ctrl+C to stop.")
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
```

- [ ] **Step 4: Create a minimal index.html**

Create `src/memento/dashboard/static/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memento Dashboard</title>
</head>
<body>
    <div id="app">
        <h1>Memento Dashboard</h1>
        <p>Loading...</p>
    </div>
</body>
</html>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_app_serves_index -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/memento/dashboard/ tests/test_dashboard.py
git commit -m "feat(dashboard): add FastAPI server skeleton with static serving"
```

---

### Task 3: Add `memento dashboard` CLI command

**Files:**
- Modify: `src/memento/cli.py`

- [ ] **Step 1: Add the dashboard command**

Add at the end of `cli.py`, before the `if __name__ == "__main__":` block:

```python
@main.command()
@click.option("--port", default=8230, help="服务端口")
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
def dashboard(port, no_open):
    """启动 Web Dashboard。"""
    try:
        from memento.dashboard.server import run_server
    except ImportError:
        raise click.ClickException(
            "Dashboard 依赖未安装。请运行: pip install memento[dashboard]"
        )
    run_server(port=port, open_browser=not no_open)
```

- [ ] **Step 2: Verify the command registers**

Run: `cd /Users/maizi/data/work/memento && memento dashboard --help`
Expected: Shows help text with `--port` and `--no-open` options

- [ ] **Step 3: Commit**

```bash
git add src/memento/cli.py
git commit -m "feat(dashboard): add 'memento dashboard' CLI command"
```

---

## Phase 2: Read-only API

### Task 4: Add `list_engrams()` method to LocalAPI

This is a dashboard-specific list/filter/pagination interface, separate from `recall()`.

**Files:**
- Modify: `src/memento/api.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_dashboard.py`:

```python
def test_list_engrams_empty(client):
    """GET /api/engrams with no data returns empty list."""
    resp = client.get("/api/engrams")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_engrams_with_data(client):
    """GET /api/engrams returns engrams after capture."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    api.capture("test memory one", type="fact", origin="human", importance="normal")
    api.capture("test memory two", type="decision", origin="agent", importance="high")
    api.close()

    resp = client.get("/api/engrams")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # Check required fields exist
    for item in data:
        assert "id" in item
        assert "content" in item
        assert "type" in item
        assert "origin" in item
        assert "strength" in item
        assert "tags" in item
        assert "created_at" in item


def test_list_engrams_filter_by_type(client):
    """GET /api/engrams?type=fact filters by type."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    api.capture("a fact", type="fact", origin="human")
    api.capture("a decision", type="decision", origin="human")
    api.close()

    resp = client.get("/api/engrams?type=fact")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["type"] == "fact"


def test_list_engrams_filter_by_origin(client):
    """GET /api/engrams?origin=agent filters by origin."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    api.capture("human memory", type="fact", origin="human")
    api.capture("agent memory", type="fact", origin="agent")
    api.close()

    resp = client.get("/api/engrams?origin=agent")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["origin"] == "agent"


def test_list_engrams_sort_and_limit(client):
    """GET /api/engrams supports sort and limit."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    for i in range(5):
        api.capture(f"memory {i}", type="fact", origin="human")
    api.close()

    resp = client.get("/api/engrams?limit=2&sort=created_at&order=asc")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["content"] == "memory 0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_list_engrams_empty -v`
Expected: FAIL — no `/api/engrams` route

- [ ] **Step 3: Add `list_engrams()` to LocalAPI**

Add to `src/memento/api.py`, inside the `LocalAPI` class, after the `recall()` method:

```python
    def list_engrams(
        self,
        type: str | None = None,
        origin: str | None = None,
        importance: str | None = None,
        verified: bool | None = None,
        sort: str = "created_at",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Dashboard-specific list/filter/pagination for engrams.

        Unlike recall(), this returns all engrams with filtering and pagination,
        not relevance-ranked search results.
        """
        conditions = ["forgotten = 0"]
        params: list = []

        if type:
            types = [t.strip() for t in type.split(",")]
            placeholders = ",".join("?" * len(types))
            conditions.append(f"type IN ({placeholders})")
            params.extend(types)

        if origin:
            conditions.append("origin = ?")
            params.append(origin)

        if importance:
            conditions.append("importance = ?")
            params.append(importance)

        if verified is not None:
            conditions.append("verified = ?")
            params.append(1 if verified else 0)

        where = " AND ".join(conditions)

        # Validate sort column to prevent SQL injection
        allowed_sorts = {"created_at", "strength", "access_count", "last_accessed"}
        if sort not in allowed_sorts:
            sort = "created_at"
        if order not in ("asc", "desc"):
            order = "desc"

        # Clamp limit
        limit = min(max(1, limit), 200)
        offset = max(0, offset)

        query = f"""
            SELECT id, content, type, tags, strength, importance, origin,
                   verified, created_at, last_accessed, access_count,
                   COALESCE(rigidity, 0.0) as rigidity
            FROM engrams
            WHERE {where}
            ORDER BY {sort} {order}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Parse tags from JSON string
            tags_raw = d.get("tags")
            if isinstance(tags_raw, str):
                try:
                    import json as _json
                    d["tags"] = _json.loads(tags_raw)
                except (ValueError, TypeError):
                    d["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
            elif tags_raw is None:
                d["tags"] = []
            d["verified"] = bool(d.get("verified"))
            # Check if provisional (exists in capture_log, not yet consolidated)
            d["provisional"] = False
            results.append(d)

        return results
```

- [ ] **Step 4: Add the `/api/engrams` route**

Add to `src/memento/dashboard/routes.py`:

```python
from typing import Optional


@router.get("/engrams")
def list_engrams(
    q: str = "",
    type: str = "",
    origin: str = "",
    importance: str = "",
    verified: str = "",
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """List engrams with filtering, sorting, and pagination."""
    api = _get_api()
    try:
        # If search query provided, use recall for relevance-ranked results
        if q:
            results = api.recall(q, max_results=limit)
            api.close()
            # Normalize recall results to match list format
            normalized = []
            for r in results:
                if isinstance(r, dict):
                    item = {
                        "id": r.get("id"),
                        "content": r.get("content"),
                        "type": r.get("type"),
                        "origin": r.get("origin"),
                        "importance": r.get("importance"),
                        "strength": r.get("score", 0),
                        "rigidity": 0.0,
                        "verified": bool(r.get("verified", False)),
                        "provisional": r.get("provisional", False),
                        "tags": _parse_tags(r.get("tags")),
                        "access_count": 0,
                        "created_at": r.get("created_at", ""),
                        "last_accessed": r.get("last_accessed", ""),
                    }
                    normalized.append(item)
            return normalized

        # No query: use list_engrams for filtered listing
        verified_bool = None
        if verified == "true":
            verified_bool = True
        elif verified == "false":
            verified_bool = False

        results = api.list_engrams(
            type=type or None,
            origin=origin or None,
            importance=importance or None,
            verified=verified_bool,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        api.close()
        return results
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


def _parse_tags(tags_raw) -> list:
    """Parse tags from various formats."""
    if isinstance(tags_raw, list):
        return tags_raw
    if isinstance(tags_raw, str):
        try:
            import json as _json
            parsed = _json.loads(tags_raw)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass
        return [t.strip() for t in tags_raw.split(",") if t.strip()]
    return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "engram"`
Expected: All engram list tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/memento/api.py src/memento/dashboard/routes.py tests/test_dashboard.py
git commit -m "feat(dashboard): add list_engrams API with filter/sort/pagination"
```

---

### Task 5: Add `GET /api/engrams/{id}` detail endpoint

**Files:**
- Modify: `src/memento/dashboard/routes.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_dashboard.py`:

```python
def test_get_engram_detail(client):
    """GET /api/engrams/{id} returns engram detail with nexus."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    result = api.capture("detail test memory", type="fact", origin="human")
    api.close()

    # Get the ID (capture returns dict with capture_log_id in awake mode)
    engram_id = result if isinstance(result, str) else result.get("capture_log_id")

    resp = client.get(f"/api/engrams/{engram_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == engram_id
    assert data["content"] == "detail test memory"
    assert "nexus" in data


def test_get_engram_not_found(client):
    """GET /api/engrams/{id} returns 404 for missing engram."""
    resp = client.get("/api/engrams/nonexistent-id")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_get_engram_detail -v`
Expected: FAIL — no route for `/api/engrams/{engram_id}`

- [ ] **Step 3: Add the route**

Add to `src/memento/dashboard/routes.py`:

```python
@router.get("/engrams/{engram_id}")
def get_engram_detail(engram_id: str):
    """Get detailed engram info including nexus connections.

    Based on LocalAPI.inspect() — does not reinvent detail query logic.
    """
    api = _get_api()
    result = api.inspect(engram_id)
    api.close()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ENGRAM_NOT_FOUND", "message": f"Engram {engram_id} not found"},
        )

    # Normalize the inspect() result for the dashboard
    result["tags"] = _parse_tags(result.get("tags"))
    result["verified"] = bool(result.get("verified"))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "detail or not_found"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/dashboard/routes.py tests/test_dashboard.py
git commit -m "feat(dashboard): add engram detail endpoint based on inspect()"
```

---

### Task 6: Add session and epoch read-only endpoints

**Files:**
- Modify: `src/memento/dashboard/routes.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_dashboard.py`:

```python
def test_get_sessions(client):
    """GET /api/sessions returns session list."""
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_epoch_history(client):
    """GET /api/epoch/history returns epoch records."""
    resp = client.get("/api/epoch/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_epoch_debt(client):
    """GET /api/epoch/debt returns debt map."""
    resp = client.get("/api/epoch/debt")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "sessions or epoch"`
Expected: FAIL

- [ ] **Step 3: Add the routes**

Add to `src/memento/dashboard/routes.py`:

```python
@router.get("/sessions")
def list_sessions(project: str = "", status: str = "", limit: int = 20):
    """List sessions, optionally filtered by project."""
    api = _get_api()
    sessions = api.session_list(project=project or None, limit=limit)
    api.close()

    return [
        {
            "id": s.id,
            "project": s.project,
            "task": s.task,
            "status": s.status,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "summary": s.summary,
            "event_counts": s.event_counts if s.event_counts else {},
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str):
    """Get session detail with event counts."""
    api = _get_api()
    info = api.session_status(session_id)
    api.close()

    if not info:
        raise HTTPException(
            status_code=404,
            detail={"code": "SESSION_NOT_FOUND", "message": f"Session {session_id} not found"},
        )

    return {
        "id": info.id,
        "project": info.project,
        "task": info.task,
        "status": info.status,
        "started_at": info.started_at,
        "ended_at": info.ended_at,
        "summary": info.summary,
        "event_counts": info.event_counts if info.event_counts else {},
    }


@router.get("/epoch/history")
def get_epoch_history():
    """Get recent epoch run records."""
    api = _get_api()
    records = api.epoch_status()
    api.close()
    return records


@router.get("/epoch/debt")
def get_epoch_debt():
    """Get unresolved cognitive debt by type."""
    api = _get_api()
    debt = api.epoch_debt()
    api.close()
    return debt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "sessions or epoch"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/dashboard/routes.py tests/test_dashboard.py
git commit -m "feat(dashboard): add session and epoch read-only endpoints"
```

---

## Phase 3: Interactive Actions

### Task 7: Add verify, forget, pin, and epoch run endpoints

**Files:**
- Modify: `src/memento/dashboard/routes.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_dashboard.py`:

```python
def test_verify_engram(client):
    """POST /api/engrams/{id}/verify marks agent memory as verified."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    result = api.capture("agent memory to verify", type="fact", origin="agent")
    engram_id = result if isinstance(result, str) else result.get("capture_log_id")
    api.close()

    resp = client.post(f"/api/engrams/{engram_id}/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "verified" or data.get("ok") is True


def test_forget_engram(client):
    """DELETE /api/engrams/{id} marks memory for deletion."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    result = api.capture("memory to forget", type="fact", origin="human")
    engram_id = result if isinstance(result, str) else result.get("capture_log_id")
    api.close()

    resp = client.delete(f"/api/engrams/{engram_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True or data.get("status") == "pending"


def test_pin_engram(client):
    """POST /api/engrams/{id}/pin sets rigidity."""
    import os
    from memento.api import LocalAPI
    from pathlib import Path

    api = LocalAPI(db_path=Path(os.environ["MEMENTO_DB"]))
    result = api.capture("memory to pin", type="fact", origin="human")
    engram_id = result if isinstance(result, str) else result.get("capture_log_id")
    api.close()

    resp = client.post(f"/api/engrams/{engram_id}/pin", json={"rigidity": 0.8})
    assert resp.status_code == 200


def test_pin_engram_invalid_rigidity(client):
    """POST /api/engrams/{id}/pin rejects invalid rigidity."""
    resp = client.post("/api/engrams/some-id/pin", json={"rigidity": 1.5})
    assert resp.status_code == 400


def test_epoch_run(client):
    """POST /api/epoch/run triggers an epoch."""
    resp = client.post("/api/epoch/run", json={"mode": "light"})
    assert resp.status_code == 200
    data = resp.json()
    assert "epoch_id" in data or "error" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "verify or forget or pin or epoch_run"`
Expected: FAIL

- [ ] **Step 3: Add the routes**

Add to `src/memento/dashboard/routes.py`:

```python
from pydantic import BaseModel


class PinRequest(BaseModel):
    rigidity: float


class EpochRunRequest(BaseModel):
    mode: str = "full"


@router.post("/engrams/{engram_id}/verify")
def verify_engram(engram_id: str):
    """Verify an agent memory as trustworthy."""
    api = _get_api()
    try:
        result = api.verify(engram_id)
        api.close()
        if isinstance(result, dict):
            return result
        return {"ok": result, "id": engram_id}
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "VERIFY_FAILED", "message": str(e)})


@router.delete("/engrams/{engram_id}")
def forget_engram(engram_id: str):
    """Mark a memory for deletion (takes effect after next epoch)."""
    api = _get_api()
    try:
        result = api.forget(engram_id)
        api.close()
        if isinstance(result, dict):
            result["ok"] = True
            return result
        return {"ok": result, "id": engram_id, "action": "marked_for_forget"}
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "FORGET_FAILED", "message": str(e)})


@router.post("/engrams/{engram_id}/pin")
def pin_engram(engram_id: str, body: PinRequest):
    """Set rigidity for an engram (0.0-1.0)."""
    if not (0.0 <= body.rigidity <= 1.0):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RIGIDITY", "message": "rigidity must be between 0.0 and 1.0"},
        )
    api = _get_api()
    try:
        result = api.pin(engram_id, body.rigidity)
        api.close()
        return result
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "PIN_FAILED", "message": str(e)})


@router.post("/epoch/run")
def run_epoch(body: EpochRunRequest):
    """Trigger an epoch consolidation run."""
    api = _get_api()
    try:
        result = api.epoch_run(mode=body.mode, trigger="manual")
        api.close()
        return result
    except Exception as e:
        api.close()
        raise HTTPException(status_code=500, detail={"code": "EPOCH_FAILED", "message": str(e)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v -k "verify or forget or pin or epoch_run"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/dashboard/routes.py tests/test_dashboard.py
git commit -m "feat(dashboard): add verify/forget/pin/epoch-run action endpoints"
```

---

### Task 8: Add `list_pending_captures()` to LocalAPI and endpoint

**Files:**
- Modify: `src/memento/api.py`
- Modify: `src/memento/dashboard/routes.py`
- Test: `tests/test_dashboard.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_dashboard.py`:

```python
def test_get_pending_captures(client):
    """GET /api/captures/pending returns L2 buffer contents."""
    resp = client.get("/api/captures/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_get_pending_captures -v`
Expected: FAIL

- [ ] **Step 3: Add `list_pending_captures()` to LocalAPI**

Add to `src/memento/api.py`, inside the `LocalAPI` class:

```python
    def list_pending_captures(self, limit: int = 50) -> list[dict]:
        """List unconsumed captures in L2 buffer (capture_log)."""
        try:
            rows = self.conn.execute(
                """SELECT id, content, type, tags, importance, origin,
                          created_at, source_session_id
                   FROM capture_log
                   WHERE epoch_id IS NULL
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                tags_raw = d.get("tags")
                if isinstance(tags_raw, str):
                    try:
                        import json as _json
                        d["tags"] = _json.loads(tags_raw)
                    except (ValueError, TypeError):
                        d["tags"] = []
                elif tags_raw is None:
                    d["tags"] = []
                results.append(d)
            return results
        except Exception:
            return []
```

- [ ] **Step 4: Add the route**

Add to `src/memento/dashboard/routes.py`:

```python
@router.get("/captures/pending")
def get_pending_captures(limit: int = 50):
    """List pending captures in L2 buffer."""
    api = _get_api()
    results = api.list_pending_captures(limit=limit)
    api.close()
    return results
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py::test_get_pending_captures -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/memento/api.py src/memento/dashboard/routes.py tests/test_dashboard.py
git commit -m "feat(dashboard): add list_pending_captures API and endpoint"
```

---

## Phase 4: Frontend

### Task 9: Download Vue 3 and Vue Router vendor files

**Files:**
- Create: `src/memento/dashboard/static/vendor/vue.global.prod.js`
- Create: `src/memento/dashboard/static/vendor/vue-router.global.prod.js`

- [ ] **Step 1: Download vendor files**

```bash
mkdir -p src/memento/dashboard/static/vendor
curl -L "https://unpkg.com/vue@3/dist/vue.global.prod.js" -o src/memento/dashboard/static/vendor/vue.global.prod.js
curl -L "https://unpkg.com/vue-router@4/dist/vue-router.global.prod.js" -o src/memento/dashboard/static/vendor/vue-router.global.prod.js
```

- [ ] **Step 2: Verify files are valid**

```bash
head -1 src/memento/dashboard/static/vendor/vue.global.prod.js
head -1 src/memento/dashboard/static/vendor/vue-router.global.prod.js
```

Expected: JavaScript content (not HTML error pages)

- [ ] **Step 3: Commit**

```bash
git add src/memento/dashboard/static/vendor/
git commit -m "chore(dashboard): add Vue 3 and Vue Router vendor files for offline use"
```

---

### Task 10: Build the Vue 3 SPA frontend

**Files:**
- Create: `src/memento/dashboard/static/style.css`
- Create: `src/memento/dashboard/static/app.js`
- Modify: `src/memento/dashboard/static/index.html`

- [ ] **Step 1: Create style.css**

Create `src/memento/dashboard/static/style.css`:

```css
/* Memento Dashboard Styles */
:root {
    --primary: #4f46e5;
    --primary-light: #ede9fe;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --text: #1e293b;
    --text-secondary: #64748b;
    --text-muted: #94a3b8;
    --bg: #f8fafc;
    --bg-white: #ffffff;
    --border: #e2e8f0;
    --radius: 8px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
}

/* Navigation */
.nav {
    background: #1e1b4b;
    color: white;
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
}

.nav-brand {
    font-weight: bold;
    font-size: 16px;
}

.nav-tabs {
    display: flex;
    gap: 4px;
}

.nav-tab {
    padding: 6px 16px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    color: white;
    text-decoration: none;
    opacity: 0.7;
    transition: opacity 0.2s, background 0.2s;
}

.nav-tab:hover { opacity: 0.9; }
.nav-tab.active { opacity: 1; background: rgba(255,255,255,0.15); }

.nav-meta {
    font-size: 12px;
    opacity: 0.6;
}

/* Stats Bar */
.stats-bar {
    background: var(--bg-white);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    gap: 32px;
}

.stat {
    text-align: center;
}

.stat-value {
    font-size: 24px;
    font-weight: bold;
}

.stat-label {
    font-size: 11px;
    color: var(--text-secondary);
    margin-top: 2px;
}

/* Search & Filter */
.toolbar {
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 12px;
    align-items: center;
    background: var(--bg-white);
}

.search-input {
    flex: 1;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: 14px;
    outline: none;
}

.search-input:focus { border-color: var(--primary); }

.filter-select {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 13px;
    background: white;
    cursor: pointer;
}

/* Content area */
.content {
    padding: 16px 24px;
    max-width: 1200px;
    margin: 0 auto;
}

/* Memory Card */
.memory-card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    margin-bottom: 12px;
    background: var(--bg-white);
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    transition: opacity 0.3s;
}

.memory-card.dimmed { opacity: 0.5; }

.memory-content { flex: 1; margin-right: 16px; }

.memory-text {
    font-size: 14px;
    line-height: 1.6;
}

.memory-tags {
    margin-top: 8px;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.tag {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
}

.tag-type { background: var(--primary-light); color: #6d28d9; }
.tag-custom { background: #fef3c7; color: #92400e; }
.tag-human { background: #dcfce7; color: #166534; }
.tag-agent { background: #fee2e2; color: #991b1b; }
.tag-provisional { background: #fef3c7; color: #92400e; }

/* Memory meta (right side) */
.memory-meta {
    text-align: right;
    min-width: 140px;
    flex-shrink: 0;
}

.strength-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    justify-content: flex-end;
}

.strength-track {
    width: 60px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
}

.strength-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
}

.strength-value {
    font-size: 11px;
    color: var(--text-secondary);
    min-width: 28px;
}

.memory-info {
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 4px;
}

.memory-actions {
    margin-top: 8px;
    display: flex;
    gap: 4px;
    justify-content: flex-end;
}

/* Buttons */
.btn {
    padding: 4px 10px;
    font-size: 11px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-white);
    cursor: pointer;
    transition: background 0.2s;
}

.btn:hover { background: var(--bg); }
.btn-danger { color: var(--danger); border-color: #fca5a5; }
.btn-danger:hover { background: #fef2f2; }
.btn-primary { color: var(--primary); border-color: #a5b4fc; }
.btn-primary:hover { background: var(--primary-light); }
.btn-success { color: var(--success); border-color: #86efac; }
.btn-success:hover { background: #dcfce7; }

.btn-lg {
    padding: 8px 16px;
    font-size: 13px;
}

/* Session list */
.session-card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    margin-bottom: 8px;
    background: var(--bg-white);
    cursor: pointer;
    transition: border-color 0.2s;
}

.session-card:hover { border-color: var(--primary); }

.session-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.session-detail {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    font-size: 13px;
    color: var(--text-secondary);
}

/* Status badge */
.badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
}

.badge-active { background: #dcfce7; color: #166534; }
.badge-completed { background: #dbeafe; color: #1e40af; }
.badge-error { background: #fee2e2; color: #991b1b; }

/* System view */
.system-section {
    margin-bottom: 24px;
}

.system-section h3 {
    margin-bottom: 12px;
    font-size: 15px;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

th, td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
}

th {
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 11px;
    text-transform: uppercase;
}

/* Confirm dialog */
.modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.modal {
    background: white;
    border-radius: var(--radius);
    padding: 24px;
    max-width: 400px;
    width: 90%;
}

.modal h3 { margin-bottom: 12px; }
.modal p { margin-bottom: 16px; color: var(--text-secondary); font-size: 14px; }

.modal-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
}

/* Empty state */
.empty {
    text-align: center;
    padding: 48px 24px;
    color: var(--text-muted);
}

/* Loading */
.loading {
    text-align: center;
    padding: 24px;
    color: var(--text-muted);
}
```

- [ ] **Step 2: Create app.js**

Create `src/memento/dashboard/static/app.js`:

```javascript
/* Memento Dashboard — Vue 3 Application */
const { createApp, ref, computed, onMounted, watch, nextTick } = Vue;
const { createRouter, createWebHashHistory } = VueRouter;

/* ── API Helper ── */
const api = {
    async get(path) {
        const resp = await fetch(`/api${path}`);
        if (!resp.ok) throw await resp.json();
        return resp.json();
    },
    async post(path, body = {}) {
        const resp = await fetch(`/api${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw await resp.json();
        return resp.json();
    },
    async del(path) {
        const resp = await fetch(`/api${path}`, { method: 'DELETE' });
        if (!resp.ok) throw await resp.json();
        return resp.json();
    },
};

/* ── Utility ── */
function strengthColor(s) {
    if (s > 0.6) return '#4f46e5';
    if (s > 0.3) return '#f59e0b';
    return '#ef4444';
}

function debounce(fn, ms) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), ms);
    };
}

/* ── Memories View ── */
const MemoriesView = {
    template: `
    <div>
        <div class="stats-bar">
            <div class="stat">
                <div class="stat-value" style="color: var(--primary)">{{ status.active || 0 }}</div>
                <div class="stat-label">活跃记忆</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--warning)">{{ status.unverified_agent || 0 }}</div>
                <div class="stat-label">待验证</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--success)">{{ status.total_sessions || 0 }}</div>
                <div class="stat-label">会话数</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: var(--primary)">{{ status.cognitive_debt_count || 0 }}</div>
                <div class="stat-label">认知债务</div>
            </div>
        </div>

        <div class="toolbar">
            <input class="search-input" v-model="searchQuery"
                   @input="onSearch" placeholder="🔍 搜索记忆内容、标签...">
            <select class="filter-select" v-model="filterType" @change="loadEngrams">
                <option value="">全部类型</option>
                <option v-for="t in types" :value="t">{{ t }}</option>
            </select>
            <select class="filter-select" v-model="filterOrigin" @change="loadEngrams">
                <option value="">全部来源</option>
                <option value="human">human</option>
                <option value="agent">agent</option>
            </select>
            <select class="filter-select" v-model="sortBy" @change="loadEngrams">
                <option value="created_at">按时间</option>
                <option value="strength">按强度</option>
                <option value="access_count">按访问次数</option>
            </select>
        </div>

        <div class="content">
            <div v-if="loading" class="loading">加载中...</div>
            <div v-else-if="engrams.length === 0" class="empty">暂无记忆</div>
            <div v-for="e in engrams" :key="e.id"
                 class="memory-card"
                 :class="{ dimmed: (e.strength || 0) < 0.3 }">
                <div class="memory-content">
                    <div class="memory-text">{{ e.content }}</div>
                    <div class="memory-tags">
                        <span class="tag tag-type">{{ e.type }}</span>
                        <span v-for="t in (e.tags || [])" class="tag tag-custom">{{ t }}</span>
                        <span class="tag" :class="e.origin === 'human' ? 'tag-human' : 'tag-agent'">
                            {{ e.origin }}{{ !e.verified && e.origin === 'agent' ? ' · 未验证' : '' }}
                        </span>
                        <span v-if="e.provisional" class="tag tag-provisional">provisional</span>
                    </div>
                </div>
                <div class="memory-meta">
                    <div class="strength-bar">
                        <div class="strength-track">
                            <div class="strength-fill"
                                 :style="{ width: ((e.strength || 0) * 100) + '%', background: strengthColor(e.strength || 0) }">
                            </div>
                        </div>
                        <span class="strength-value">{{ (e.strength || 0).toFixed(2) }}</span>
                    </div>
                    <div class="memory-info">{{ e.importance }} · 访问 {{ e.access_count || 0 }} 次</div>
                    <div class="memory-actions">
                        <button v-if="e.origin === 'agent' && !e.verified"
                                class="btn btn-success" @click="verifyEngram(e)">✓ 验证</button>
                        <button class="btn btn-danger" @click="confirmForget(e)">🗑</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Confirm Dialog -->
        <div v-if="confirmDialog" class="modal-overlay" @click.self="confirmDialog = null">
            <div class="modal">
                <h3>确认删除</h3>
                <p>确定要遗忘这条记忆吗？此操作将在下次 Epoch 后生效。</p>
                <p style="font-size: 12px; color: var(--text-muted);">{{ confirmDialog.content }}</p>
                <div class="modal-actions">
                    <button class="btn" @click="confirmDialog = null">取消</button>
                    <button class="btn btn-danger" @click="forgetEngram(confirmDialog)">确认删除</button>
                </div>
            </div>
        </div>
    </div>
    `,
    setup() {
        const engrams = ref([]);
        const status = ref({});
        const loading = ref(true);
        const searchQuery = ref('');
        const filterType = ref('');
        const filterOrigin = ref('');
        const sortBy = ref('created_at');
        const confirmDialog = ref(null);
        const types = ['fact', 'decision', 'insight', 'convention', 'debugging', 'preference'];

        async function loadStatus() {
            try { status.value = await api.get('/status'); } catch (e) { console.error(e); }
        }

        async function loadEngrams() {
            loading.value = true;
            try {
                let params = new URLSearchParams();
                if (searchQuery.value) params.set('q', searchQuery.value);
                if (filterType.value) params.set('type', filterType.value);
                if (filterOrigin.value) params.set('origin', filterOrigin.value);
                params.set('sort', sortBy.value);
                params.set('order', 'desc');
                params.set('limit', '50');
                engrams.value = await api.get('/engrams?' + params.toString());
            } catch (e) { console.error(e); }
            loading.value = false;
        }

        const onSearch = debounce(() => loadEngrams(), 300);

        async function verifyEngram(e) {
            try {
                await api.post(`/engrams/${e.id}/verify`);
                e.verified = true;
                await loadStatus();
            } catch (err) { alert('验证失败: ' + (err.detail?.message || err)); }
        }

        function confirmForget(e) { confirmDialog.value = e; }

        async function forgetEngram(e) {
            try {
                await api.del(`/engrams/${e.id}`);
                engrams.value = engrams.value.filter(x => x.id !== e.id);
                confirmDialog.value = null;
                await loadStatus();
            } catch (err) { alert('删除失败: ' + (err.detail?.message || err)); }
        }

        onMounted(() => { loadStatus(); loadEngrams(); });

        return {
            engrams, status, loading, searchQuery, filterType, filterOrigin,
            sortBy, confirmDialog, types, onSearch, loadEngrams,
            verifyEngram, confirmForget, forgetEngram, strengthColor, loadStatus,
        };
    },
};

/* ── Sessions View ── */
const SessionsView = {
    template: `
    <div class="content">
        <h2 style="margin-bottom: 16px;">会话历史</h2>
        <div class="toolbar" style="border: none; padding: 0 0 16px 0;">
            <input class="search-input" v-model="projectFilter"
                   @input="loadSessions" placeholder="按项目路径过滤...">
        </div>
        <div v-if="sessions.length === 0" class="empty">暂无会话记录</div>
        <div v-for="s in sessions" :key="s.id" class="session-card" @click="toggle(s.id)">
            <div class="session-header">
                <div>
                    <strong>{{ s.project || '未指定项目' }}</strong>
                    <span style="margin-left: 8px; font-size: 12px; color: var(--text-muted);">
                        {{ s.started_at?.slice(0, 16) }}
                    </span>
                </div>
                <span class="badge" :class="'badge-' + s.status">{{ s.status }}</span>
            </div>
            <div v-if="expanded === s.id" class="session-detail">
                <p v-if="s.summary"><strong>摘要：</strong>{{ s.summary }}</p>
                <p v-if="s.task"><strong>任务：</strong>{{ s.task }}</p>
                <p v-if="s.ended_at"><strong>结束：</strong>{{ s.ended_at?.slice(0, 16) }}</p>
                <p v-if="s.event_counts && Object.keys(s.event_counts).length">
                    <strong>事件：</strong>
                    <span v-for="(v, k) in s.event_counts" style="margin-right: 12px;">{{ k }}: {{ v }}</span>
                </p>
            </div>
        </div>
    </div>
    `,
    setup() {
        const sessions = ref([]);
        const projectFilter = ref('');
        const expanded = ref(null);

        async function loadSessions() {
            try {
                let params = new URLSearchParams();
                if (projectFilter.value) params.set('project', projectFilter.value);
                params.set('limit', '50');
                sessions.value = await api.get('/sessions?' + params.toString());
            } catch (e) { console.error(e); }
        }

        function toggle(id) { expanded.value = expanded.value === id ? null : id; }

        onMounted(() => loadSessions());
        return { sessions, projectFilter, expanded, loadSessions, toggle };
    },
};

/* ── System View ── */
const SystemView = {
    template: `
    <div class="content">
        <h2 style="margin-bottom: 16px;">系统状态</h2>

        <div class="system-section">
            <h3>概览</h3>
            <div class="stats-bar" style="border: 1px solid var(--border); border-radius: var(--radius);">
                <div class="stat">
                    <div class="stat-value">{{ status.total || 0 }}</div>
                    <div class="stat-label">总记忆</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ status.active || 0 }}</div>
                    <div class="stat-label">活跃</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ status.forgotten || 0 }}</div>
                    <div class="stat-label">已遗忘</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ embeddingCoverage }}</div>
                    <div class="stat-label">Embedding 覆盖</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ status.pending_capture || 0 }}</div>
                    <div class="stat-label">待处理 Capture</div>
                </div>
            </div>
        </div>

        <div class="system-section">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>Epoch 历史</h3>
                <button class="btn btn-primary btn-lg" @click="confirmEpoch = true">触发 Epoch</button>
            </div>
            <table v-if="epochs.length > 0" style="margin-top: 12px;">
                <thead>
                    <tr><th>ID</th><th>模式</th><th>状态</th><th>完成时间</th></tr>
                </thead>
                <tbody>
                    <tr v-for="e in epochs" :key="e.id">
                        <td>{{ e.id?.slice(0, 16) }}</td>
                        <td>{{ e.mode }}</td>
                        <td><span class="badge" :class="'badge-' + (e.status === 'committed' ? 'completed' : 'error')">{{ e.status }}</span></td>
                        <td>{{ e.committed_at?.slice(0, 16) || '—' }}</td>
                    </tr>
                </tbody>
            </table>
            <div v-else class="empty" style="padding: 24px;">暂无 Epoch 记录</div>
        </div>

        <div class="system-section">
            <h3>认知债务</h3>
            <div v-if="Object.keys(debt).length === 0" class="empty" style="padding: 24px;">无未解决债务</div>
            <table v-else>
                <thead><tr><th>类型</th><th>数量</th></tr></thead>
                <tbody>
                    <tr v-for="(count, type) in debt" :key="type">
                        <td>{{ type }}</td><td>{{ count }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="system-section">
            <h3>L2 缓冲区 (待处理 Captures)</h3>
            <div v-if="pendingCaptures.length === 0" class="empty" style="padding: 24px;">无待处理 Capture</div>
            <table v-else>
                <thead><tr><th>内容</th><th>类型</th><th>来源</th><th>创建时间</th></tr></thead>
                <tbody>
                    <tr v-for="c in pendingCaptures" :key="c.id">
                        <td>{{ c.content?.slice(0, 60) }}{{ c.content?.length > 60 ? '...' : '' }}</td>
                        <td><span class="tag tag-type">{{ c.type }}</span></td>
                        <td>{{ c.origin }}</td>
                        <td>{{ c.created_at?.slice(0, 16) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Confirm Epoch Dialog -->
        <div v-if="confirmEpoch" class="modal-overlay" @click.self="confirmEpoch = false">
            <div class="modal">
                <h3>触发 Epoch</h3>
                <p>确定要运行 Epoch 整合吗？这会将 L2 缓冲区的 Captures 固化到长期记忆。</p>
                <div class="modal-actions">
                    <button class="btn" @click="confirmEpoch = false">取消</button>
                    <button class="btn btn-primary" @click="runEpoch" :disabled="epochRunning">
                        {{ epochRunning ? '运行中...' : '确认运行' }}
                    </button>
                </div>
            </div>
        </div>
    </div>
    `,
    setup() {
        const status = ref({});
        const epochs = ref([]);
        const debt = ref({});
        const pendingCaptures = ref([]);
        const confirmEpoch = ref(false);
        const epochRunning = ref(false);

        const embeddingCoverage = computed(() => {
            const total = status.value.total || 0;
            const withEmb = status.value.with_embedding || 0;
            if (total === 0) return '—';
            return Math.round((withEmb / total) * 100) + '%';
        });

        async function loadAll() {
            try { status.value = await api.get('/status'); } catch (e) {}
            try { epochs.value = await api.get('/epoch/history'); } catch (e) {}
            try { debt.value = await api.get('/epoch/debt'); } catch (e) {}
            try { pendingCaptures.value = await api.get('/captures/pending'); } catch (e) {}
        }

        async function runEpoch() {
            epochRunning.value = true;
            try {
                await api.post('/epoch/run', { mode: 'full' });
                confirmEpoch.value = false;
                await loadAll();
            } catch (err) {
                alert('Epoch 失败: ' + (err.detail?.message || err));
            }
            epochRunning.value = false;
        }

        onMounted(() => loadAll());
        return { status, epochs, debt, pendingCaptures, confirmEpoch, epochRunning, embeddingCoverage, loadAll, runEpoch };
    },
};

/* ── Router ── */
const router = createRouter({
    history: createWebHashHistory(),
    routes: [
        { path: '/', component: MemoriesView },
        { path: '/sessions', component: SessionsView },
        { path: '/system', component: SystemView },
    ],
});

/* ── App ── */
const app = createApp({
    template: `
    <div>
        <nav class="nav">
            <div style="display: flex; align-items: center; gap: 24px;">
                <span class="nav-brand">🧠 Memento</span>
                <div class="nav-tabs">
                    <router-link to="/" class="nav-tab" active-class="active" exact>记忆</router-link>
                    <router-link to="/sessions" class="nav-tab" active-class="active">会话</router-link>
                    <router-link to="/system" class="nav-tab" active-class="active">系统</router-link>
                </div>
            </div>
        </nav>
        <router-view />
    </div>
    `,
});

app.use(router);
app.mount('#app');
```

- [ ] **Step 3: Update index.html**

Replace `src/memento/dashboard/static/index.html` with:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memento Dashboard</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div id="app"></div>
    <script src="/static/vendor/vue.global.prod.js"></script>
    <script src="/static/vendor/vue-router.global.prod.js"></script>
    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Run all tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v`
Expected: All tests PASS

- [ ] **Step 5: Manual smoke test**

Run: `memento dashboard --no-open --port 8230`

Then open `http://localhost:8230` in browser. Verify:
- Navigation tabs work (记忆 / 会话 / 系统)
- Memory cards display with strength bars and tags
- Search and filters work
- Verify and delete buttons work

Press Ctrl+C to stop.

- [ ] **Step 6: Commit**

```bash
git add src/memento/dashboard/static/
git commit -m "feat(dashboard): complete Vue 3 SPA with memories, sessions, and system views"
```

---

## Phase 5: Final Integration

### Task 11: Run full test suite and fix any issues

- [ ] **Step 1: Run dashboard tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_dashboard.py -v`
Expected: All PASS

- [ ] **Step 2: Run full project test suite**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/ -v --timeout=60`
Expected: No regressions in existing tests

- [ ] **Step 3: Fix any failures**

If tests fail, diagnose and fix. The dashboard should not break existing functionality.

- [ ] **Step 4: Verify packaging**

Run: `cd /Users/maizi/data/work/memento && pip install -e ".[dashboard]" && python -c "from memento.dashboard.server import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(dashboard): complete Memento Web Dashboard MVP"
```

---

## Verification Checklist

After all tasks, verify against spec acceptance criteria:

- [ ] `memento dashboard` starts and opens browser
- [ ] Works offline (no network required)
- [ ] Memory list with search, filter by type/origin/verified
- [ ] Verify / delete / pin operations work with confirmation
- [ ] Sessions view loads with project filter
- [ ] System view shows status, epoch history, debt, pending captures
- [ ] `pip install memento` (without `[dashboard]`) still works
- [ ] All tests pass
