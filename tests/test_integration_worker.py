"""Worker HTTP Integration Tests.

Simulate the hook-handler.sh -> WorkerServer -> DB pipeline by starting
a real WorkerServer on a temporary Unix Socket and sending HTTP requests.
"""

import hashlib
import http.client
import json
import os
import socket
import threading
import time

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

    # Use /tmp to avoid AF_UNIX path length limit on macOS
    digest = hashlib.md5(str(db_path).encode()).hexdigest()[:12]
    sock_path = f"/tmp/memento-test-{digest}.sock"
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
    """Simulate complete lifecycle: session-start -> observe -> capture -> recall -> flush -> session-end."""
    sock = worker_server

    # 1. session-start
    result = _send(sock, "POST", "/session/start", {
        "external_session_id": "test-claude-1",
        "project": "test-project",
        "task": "integration test",
    })
    assert "session_id" in result
    session_id = result["session_id"]
    assert session_id  # non-empty

    # 2. observe
    result = _send(sock, "POST", "/observe", {
        "external_session_id": "test-claude-1",
        "content": "User asked about architecture",
    })
    assert result["queued"] is True

    # 3. capture
    result = _send(sock, "POST", "/capture", {
        "content": "The project uses event-driven architecture",
        "type": "fact",
        "importance": "normal",
        "origin": "agent",
    })
    assert "capture_log_id" in result
    capture_id = result["capture_log_id"]
    assert capture_id

    # 4. recall
    result = _send(sock, "POST", "/recall", {
        "query": "event-driven architecture",
        "max_results": 5,
    })
    assert isinstance(result, list)
    assert any("event-driven" in r["content"] for r in result)

    # 5. flush
    result = _send(sock, "POST", "/flush", {})
    assert result["flushed"] is True

    # 6. status - verify active session
    result = _send(sock, "GET", "/status")
    assert result["active_sessions"] >= 1
    assert session_id in result["active_session_ids"]

    # 7. session-end
    result = _send(sock, "POST", "/session/end", {
        "external_session_id": "test-claude-1",
        "outcome": "completed",
        "summary": "Integration test completed",
    })
    assert result["status"] == "completed"


def test_multi_session_isolation(worker_server):
    """Two concurrent sessions don't interfere."""
    sock = worker_server

    # Start two sessions
    r1 = _send(sock, "POST", "/session/start", {
        "external_session_id": "session-a",
        "project": "project-a",
    })
    r2 = _send(sock, "POST", "/session/start", {
        "external_session_id": "session-b",
        "project": "project-b",
    })

    sid_a = r1["session_id"]
    sid_b = r2["session_id"]
    assert sid_a != sid_b

    # Status shows 2 active sessions
    status = _send(sock, "GET", "/status")
    assert status["active_sessions"] >= 2

    # End one session
    _send(sock, "POST", "/session/end", {
        "external_session_id": "session-a",
        "outcome": "completed",
    })

    # Other still active
    status = _send(sock, "GET", "/status")
    assert sid_b in status["active_session_ids"]
    assert sid_a not in status["active_session_ids"]


def test_observe_async_does_not_block(worker_server):
    """10 observations complete in < 2 seconds."""
    sock = worker_server

    # Need a session for observations to be processed
    _send(sock, "POST", "/session/start", {
        "external_session_id": "obs-test",
        "project": "obs-project",
    })

    start = time.time()
    for i in range(10):
        result = _send(sock, "POST", "/observe", {
            "external_session_id": "obs-test",
            "content": f"Observation number {i}",
        })
        assert result["queued"] is True
    elapsed = time.time() - start
    assert elapsed < 2.0, f"10 observations took {elapsed:.2f}s, expected < 2s"


def test_capture_recall_without_session(worker_server):
    """Capture and recall work without an active session."""
    sock = worker_server

    # Capture without any session
    result = _send(sock, "POST", "/capture", {
        "content": "Standalone memory without session",
        "type": "fact",
    })
    assert "capture_log_id" in result

    # Recall without any session
    result = _send(sock, "POST", "/recall", {
        "query": "standalone memory",
    })
    assert isinstance(result, list)
    assert len(result) >= 1
    assert any("Standalone" in r["content"] for r in result)


def test_shutdown_graceful(db_path, mock_embedding):
    """POST /shutdown responds without crash."""
    from memento.worker import WorkerServer

    digest = hashlib.md5(str(db_path).encode()).hexdigest()[:12]
    sock_path = f"/tmp/memento-test-shutdown-{digest}.sock"
    server = WorkerServer(db_path, sock_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Wait for server ready
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

    # Shutdown
    result = _send(sock_path, "POST", "/shutdown", {})
    assert "flushed" in result

    # Wait for server thread to finish
    thread.join(timeout=10)
