> [!NOTE]
> **Historical Plan**
> This document is an implementation snapshot retained for history. It may not reflect the latest repository-wide milestone semantics or current implementation behavior. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.5.1a Infrastructure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Worker runtime (fail-fast on init errors) and complete the WorkerClientAPI (Unix Socket HTTP client replacing NotImplementedError stubs).

**Architecture:** Two independent changes: (1) DBThread gets init_event + init_error for fail-fast, WorkerServer checks before continuing; (2) WorkerClientAPI implements all MementoAPIBase methods via HTTP over Unix Socket, with dataclass from_dict for stable return types.

**Tech Stack:** Python 3.10+, SQLite, http.client + socket (stdlib), threading.Event

**Spec:** `docs/superpowers/specs/2026-04-01-v051a-infrastructure-hardening-design.md`

---

## File Structure

### Modified files

| File | Changes |
|------|---------|
| `src/memento/worker.py` | DBThread: ready_event → init_event + init_error, try/except/finally in run(). WorkerServer: check init result, raise on failure. New GET /epochs route. |
| `src/memento/api.py` | MementoAPIBase: add ingest_observation abstract method. StatusResult/SessionStartResult/SessionEndResult: add from_dict classmethod. WorkerClientAPI: full implementation replacing stubs. |

### Modified test files

| File | Changes |
|------|---------|
| `tests/test_worker.py` | Tests for init_event/init_error, fail-fast, GET /epochs |
| `tests/test_api.py` | Tests for from_dict methods, WorkerClientAPI with mocked socket |

---

## Task 1: Worker Fail-Fast (init_event + init_error)

**Files:**
- Modify: `src/memento/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests for init_event/init_error**

```python
# Append to tests/test_worker.py

def test_dbthread_init_event_set_on_success(tmp_path):
    """init_event should be set after successful initialization."""
    from memento.worker import DBThread
    db_path = tmp_path / "test.db"
    t = DBThread(db_path=db_path)
    t.start()
    assert t.init_event.wait(timeout=5)
    assert t.init_error is None
    t.shutdown()


def test_dbthread_init_event_set_on_failure(tmp_path):
    """init_event should be set even when initialization fails."""
    from memento.worker import DBThread
    # Use an invalid path that will cause initialization to fail
    bad_path = tmp_path / "nonexistent_dir" / "sub" / "test.db"
    t = DBThread(db_path=bad_path)
    t.start()
    assert t.init_event.wait(timeout=5)
    assert t.init_error is not None


def test_worker_server_raises_on_init_failure(tmp_path):
    """WorkerServer should raise RuntimeError when DBThread init fails."""
    from memento.worker import WorkerServer
    bad_path = tmp_path / "nonexistent_dir" / "sub" / "test.db"
    with pytest.raises(RuntimeError, match="DBThread initialization failed"):
        WorkerServer(db_path=bad_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_worker.py::test_dbthread_init_event_set_on_success tests/test_worker.py::test_dbthread_init_event_set_on_failure tests/test_worker.py::test_worker_server_raises_on_init_failure -v`
Expected: FAIL — `AttributeError: 'DBThread' object has no attribute 'init_event'`

- [ ] **Step 3: Implement init_event + init_error in DBThread**

In `src/memento/worker.py`, modify `DBThread.__init__` and `run`:

```python
class DBThread(threading.Thread):
    def __init__(self, db_path=None, pulse_queue=None):
        super().__init__(daemon=True)
        self._db_path = db_path
        self._obs_queue = queue.Queue()
        self._cmd_queue = queue.Queue()
        self._running = True
        self._api = None
        self.session_registry = {}
        self.pulse_queue = pulse_queue
        self.init_event = threading.Event()   # renamed from ready_event
        self.init_error = None                # NEW: stores init exception

    def run(self):
        try:
            self._api = MementoAPI(db_path=self._db_path, use_awake=False)
        except Exception as e:
            self.init_error = e
            return  # Thread exits, does not enter main loop
        finally:
            self.init_event.set()  # Always signal, success or failure

        # ... rest of main loop unchanged
```

Also update `WorkerServer.__init__` to check init result:

```python
class WorkerServer:
    def __init__(self, db_path=None, ...):
        # ... create DBThread
        self.db_thread.start()

        # Wait for initialization to complete
        if not self.db_thread.init_event.wait(timeout=10):
            raise RuntimeError("DBThread initialization timed out after 10s")
        if self.db_thread.init_error is not None:
            raise RuntimeError(f"DBThread initialization failed: {self.db_thread.init_error}")

        # ... start SubconsciousTrack (unchanged)
```

**Important:** Search for any remaining references to `ready_event` in worker.py and tests, rename them all to `init_event`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_worker.py -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "feat(v0.5.1a): Worker fail-fast — init_event + init_error with timeout"
```

---

## Task 2: New GET /epochs Worker Route

**Files:**
- Modify: `src/memento/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_worker.py

def test_dbthread_epoch_status_action(tmp_path):
    """epoch_status action should return epoch records."""
    from memento.worker import DBThread
    db_path = tmp_path / "test.db"
    t = DBThread(db_path=db_path)
    t.start()
    t.init_event.wait(timeout=5)

    result = t.execute("epoch_status")
    assert isinstance(result, list)
    # No epochs yet, should be empty
    assert len(result) == 0
    t.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_worker.py::test_dbthread_epoch_status_action -v`
Expected: FAIL — unknown action or similar

- [ ] **Step 3: Add epoch_status action to DBThread + GET /epochs route**

In `src/memento/worker.py`, add to the action dispatch in `DBThread.run()`:

```python
elif cmd.action == "epoch_status":
    cmd.result = self._api.epoch_status()
```

And in `_WorkerHandler.do_GET()`, add:

```python
elif self.path == "/epochs":
    result = self.server.db_thread.execute("epoch_status")
    self._respond(200, result or [])
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_worker.py -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/worker.py tests/test_worker.py
git commit -m "feat(v0.5.1a): Worker GET /epochs route for epoch history"
```

---

## Task 3: MementoAPIBase + from_dict Methods

**Files:**
- Modify: `src/memento/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for from_dict + base class**

```python
# Append to tests/test_api.py

def test_status_result_from_dict():
    from memento.api import StatusResult
    data = {
        "total": 42, "active": 38, "forgotten": 1,
        "unverified_agent": 3, "with_embedding": 35,
        "pending_embedding": 2, "total_sessions": 5,
        "active_sessions": 1, "completed_sessions": 4,
        "total_observations": 100,
        "by_state": {"consolidated": 38, "archived": 3},
        "pending_capture": 5, "pending_delta": 12,
        "pending_recon": 8, "cognitive_debt_count": 2,
        "last_epoch_committed_at": "2026-04-01T12:00:00Z",
        "decay_watermark": "2026-04-01T11:55:00Z",
    }
    result = StatusResult.from_dict(data)
    assert isinstance(result, StatusResult)
    assert result.total == 42
    assert result.pending_capture == 5
    assert result.by_state == {"consolidated": 38, "archived": 3}


def test_session_start_result_from_dict():
    from memento.session import SessionStartResult
    data = {"session_id": "s1", "priming_count": 3}
    result = SessionStartResult.from_dict(data)
    assert isinstance(result, SessionStartResult)
    assert result.session_id == "s1"
    assert result.priming_memories == []  # Worker doesn't send full memories


def test_session_end_result_from_dict():
    from memento.session import SessionEndResult
    data = {"session_id": "s1", "status": "completed",
            "captures_count": 5, "observations_count": 10}
    result = SessionEndResult.from_dict(data)
    assert isinstance(result, SessionEndResult)
    assert result.status == "completed"
    assert result.captures_count == 5
    assert result.observations_count == 10


def test_memento_api_base_has_ingest_observation():
    from memento.api import MementoAPIBase
    assert hasattr(MementoAPIBase, 'ingest_observation')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_api.py::test_status_result_from_dict tests/test_api.py::test_session_start_result_from_dict tests/test_api.py::test_session_end_result_from_dict tests/test_api.py::test_memento_api_base_has_ingest_observation -v`
Expected: FAIL — `AttributeError: type object 'StatusResult' has no attribute 'from_dict'`

- [ ] **Step 3: Implement from_dict + base class update**

In `src/memento/api.py`, add to `StatusResult`:

```python
@classmethod
def from_dict(cls, data: dict) -> "StatusResult":
    return cls(
        total=data.get("total", 0),
        active=data.get("active", 0),
        forgotten=data.get("forgotten", 0),
        unverified_agent=data.get("unverified_agent", 0),
        with_embedding=data.get("with_embedding", 0),
        pending_embedding=data.get("pending_embedding", 0),
        total_sessions=data.get("total_sessions", 0),
        active_sessions=data.get("active_sessions", 0),
        completed_sessions=data.get("completed_sessions", 0),
        total_observations=data.get("total_observations", 0),
        by_state=data.get("by_state", {}),
        pending_capture=data.get("pending_capture", 0),
        pending_delta=data.get("pending_delta", 0),
        pending_recon=data.get("pending_recon", 0),
        cognitive_debt_count=data.get("cognitive_debt_count", 0),
        last_epoch_committed_at=data.get("last_epoch_committed_at"),
        decay_watermark=data.get("decay_watermark"),
    )
```

In `src/memento/session.py`, add to `SessionStartResult`:

```python
@classmethod
def from_dict(cls, data: dict) -> "SessionStartResult":
    return cls(
        session_id=data["session_id"],
        priming_memories=data.get("priming_memories", []),
        project=data.get("project"),
        task=data.get("task"),
    )
```

In `src/memento/session.py`, add to `SessionEndResult`:

```python
@classmethod
def from_dict(cls, data: dict) -> "SessionEndResult":
    return cls(
        session_id=data.get("session_id", ""),
        status=data.get("status", "completed"),
        captures_count=data.get("captures_count", 0),
        observations_count=data.get("observations_count", 0),
    )
```

In `src/memento/api.py`, add to `MementoAPIBase`:

```python
@abstractmethod
def ingest_observation(self, content: str, tool: str = None,
                       files: list = None, importance: str = 'normal') -> None:
    ...
```

**Note:** LocalAPI already has `ingest_observation` implemented. Just make sure it's compatible with the abstract signature. If the existing method has a different signature, align it.

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_api.py -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/memento/api.py src/memento/session.py tests/test_api.py
git commit -m "feat(v0.5.1a): from_dict methods + ingest_observation in MementoAPIBase"
```

---

## Task 4: WorkerClientAPI Implementation

**Files:**
- Modify: `src/memento/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for WorkerClientAPI**

```python
# Append to tests/test_api.py
import json
from unittest.mock import patch, MagicMock


def _mock_http_response(data, status=200):
    """Create a mock HTTP response."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = json.dumps(data).encode()
    return mock_resp


def _mock_connection(response_data, status=200):
    """Create a mock HTTPConnection that returns a canned response."""
    mock_conn = MagicMock()
    mock_resp = _mock_http_response(response_data, status)
    mock_conn.getresponse.return_value = mock_resp
    return mock_conn


class TestWorkerClientAPI:
    def test_capture(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        expected = {"capture_log_id": "cl1", "state": "buffered"}
        with patch.object(client, '_request', return_value=expected) as mock_req:
            result = client.capture("test content", type="fact")
            mock_req.assert_called_once()
            assert result == expected

    def test_recall(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        expected = [{"content": "test", "score": 0.8, "provisional": False}]
        with patch.object(client, '_request', return_value=expected) as mock_req:
            result = client.recall("test")
            assert isinstance(result, list)
            assert result == expected

    def test_status_returns_status_result(self):
        from memento.api import WorkerClientAPI, StatusResult
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {"total": 10, "active": 8, "forgotten": 1,
               "pending_capture": 3, "by_state": {"consolidated": 8}}
        with patch.object(client, '_request', return_value=raw):
            result = client.status()
            assert isinstance(result, StatusResult)
            assert result.total == 10
            assert result.pending_capture == 3

    def test_session_start_returns_dataclass(self):
        from memento.api import WorkerClientAPI
        from memento.session import SessionStartResult
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {"session_id": "s1", "priming_count": 2}
        with patch.object(client, '_request', return_value=raw):
            result = client.session_start(project="test")
            assert isinstance(result, SessionStartResult)
            assert result.session_id == "s1"

    def test_session_end_returns_dataclass(self):
        from memento.api import WorkerClientAPI
        from memento.session import SessionEndResult
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {"session_id": "s1", "status": "completed",
               "captures_count": 3, "observations_count": 7,
               "auto_captures_count": 1}
        with patch.object(client, '_request', return_value=raw):
            result = client.session_end("s1")
            assert isinstance(result, SessionEndResult)
            assert result.captures_count == 3
            assert result.auto_captures_count == 1

    def test_epoch_run_spawns_subprocess(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        with patch("subprocess.run") as mock_run, \
             patch.object(client, '_request', return_value=[{"id": "ep1", "status": "committed", "mode": "light"}]):
            mock_run.return_value = MagicMock(returncode=0, stdout="done", stderr="")
            result = client.epoch_run(mode="full")
            mock_run.assert_called_once()
            assert result["epoch_id"] == "ep1"

    def test_forget(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        expected = {"status": "pending"}
        with patch.object(client, '_request', return_value=expected):
            result = client.forget("e1")
            assert result["status"] == "pending"

    def test_ingest_observation(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        with patch.object(client, '_request', return_value=None) as mock_req:
            client.ingest_observation("tool output", tool="Edit")
            mock_req.assert_called_once()

    def test_close_is_noop(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/test.sock")
        client.close()  # Should not raise

    def test_request_connection_error(self):
        from memento.api import WorkerClientAPI
        client = WorkerClientAPI("/tmp/nonexistent.sock")
        with pytest.raises(ConnectionError):
            client._request("GET", "/status")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_api.py::TestWorkerClientAPI -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement WorkerClientAPI**

Replace the stub `WorkerClientAPI` in `src/memento/api.py`:

```python
import http.client
import json
import socket
import subprocess
import uuid


class WorkerClientAPI(MementoAPIBase):
    """Unix Socket HTTP client to Worker process."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.claude_session_id = str(uuid.uuid4())

    def _request(self, method: str, path: str, body: dict = None) -> dict | list | None:
        """Send HTTP request over Unix Domain Socket."""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect(self.socket_path)
        except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
            raise ConnectionError(f"Worker not running at {self.socket_path}: {e}")

        try:
            conn = http.client.HTTPConnection("localhost")
            conn.sock = sock

            headers = {"Content-Type": "application/json"}
            body_bytes = json.dumps(body).encode() if body else None

            conn.request(method, path, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode()

            if resp.status >= 400:
                raise RuntimeError(f"Worker returned {resp.status}: {data}")

            if not data or data.strip() == "":
                return None
            return json.loads(data)
        finally:
            sock.close()

    # ── Memory Operations ──

    def capture(self, content, type='fact', tags=None, importance='normal',
                origin='human', session_id=None, event_id=None):
        return self._request("POST", "/capture", {
            "content": content, "type": type, "tags": tags,
            "importance": importance, "origin": origin,
        })

    def recall(self, query, max_results=5, **kwargs):
        return self._request("POST", "/recall", {
            "query": query, "max_results": max_results,
        })

    def forget(self, target_id):
        return self._request("POST", "/forget", {"target_id": target_id})

    def verify(self, engram_id):
        return self._request("POST", "/verify", {"engram_id": engram_id})

    def status(self):
        data = self._request("GET", "/status")
        return StatusResult.from_dict(data) if data else StatusResult()

    def inspect(self, engram_id):
        return self._request("POST", "/inspect", {"engram_id": engram_id})

    def pin(self, engram_id, rigidity):
        return self._request("POST", "/pin", {
            "engram_id": engram_id, "rigidity": rigidity,
        })

    # ── Session Lifecycle ──

    def session_start(self, project=None, task=None, metadata=None, **kwargs):
        data = self._request("POST", "/session/start", {
            "claude_session_id": self.claude_session_id,
            "project": project, "task": task,
        })
        return SessionStartResult.from_dict(data) if data else SessionStartResult(session_id="")

    def session_end(self, session_id, outcome='completed', summary=None):
        """session_id is ignored — Worker uses claude_session_id for routing."""
        data = self._request("POST", "/session/end", {
            "claude_session_id": self.claude_session_id,
            "outcome": outcome, "summary": summary,
        })
        return SessionEndResult.from_dict(data) if data else SessionEndResult(session_id="", status="error")

    # ── Observation ──

    def ingest_observation(self, content, tool=None, files=None, importance='normal'):
        self._request("POST", "/observe", {
            "claude_session_id": self.claude_session_id,
            "content": content, "tool": tool, "files": files,
        })

    # ── Epoch ──

    def epoch_run(self, mode='full', trigger='manual'):
        result = subprocess.run(
            ['memento', 'epoch', 'run', '--mode', mode, '--trigger', trigger],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        # Query actual epoch result via /epochs
        epochs = self._request("GET", "/epochs")
        if epochs and len(epochs) > 0:
            latest = epochs[0]
            return {
                "epoch_id": latest.get("id"),
                "status": latest.get("status", "completed"),
                "mode": latest.get("mode", mode),
            }
        return {"status": "completed", "mode": mode}

    def epoch_status(self):
        return self._request("GET", "/epochs") or []

    def epoch_debt(self):
        return self._request("GET", "/debt") or {}

    def close(self):
        pass  # No persistent connection to close
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_api.py -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/ -q --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/memento/api.py tests/test_api.py
git commit -m "feat(v0.5.1a): WorkerClientAPI — full Unix Socket HTTP implementation"
```
