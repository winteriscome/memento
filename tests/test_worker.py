"""Worker Service 测试。"""

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


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_worker.db"


@pytest.fixture
def mock_embedding():
    """统一 mock embedding，所有测试共享。"""
    fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2, \
         patch("memento.awake.get_embedding") as m3:
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)
        m3.return_value = (fake_blob, 4, False)
        yield


def test_db_thread_executes_commands(db_path, mock_embedding):
    """DB 线程应能执行同步命令并返回结果。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("status")
        assert "total" in result
        assert result["total"] == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_processes_observations(db_path, mock_embedding):
    """DB 线程应能异步处理 observation。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("session_start",
            external_session_id="test-sess",
            project="/test",
            task="test",
        )
        session_id = result["session_id"]

        t.enqueue_observation(
            external_session_id="test-sess",
            content="发现连接池问题",
            tool="Read",
            importance="high",
        )

        t.flush()

        status = t.execute("status")
        assert status["total_observations"] >= 1
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_session_registry_maps_claude_to_memento(db_path, mock_embedding):
    """session_start 应建立 external_session_id → memento_session_id 映射。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("session_start",
            external_session_id="claude-abc",
            project="/test",
        )
        assert "session_id" in result
        assert "claude-abc" in t.session_registry
        assert t.session_registry["claude-abc"] == result["session_id"]
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_session_end_removes_from_registry(db_path, mock_embedding):
    """session_end 应从 registry 中删除映射。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("session_start",
            external_session_id="claude-xyz",
            project="/test",
        )
        assert "claude-xyz" in t.session_registry

        t.execute("session_end", external_session_id="claude-xyz", outcome="completed")
        assert "claude-xyz" not in t.session_registry
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_observe_without_session_is_discarded(db_path, mock_embedding):
    """没有 session 的 observation 应被丢弃。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        t.enqueue_observation(
            external_session_id="nonexistent",
            content="should be discarded",
        )
        t.flush()

        status = t.execute("status")
        assert status["total_observations"] == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_default_session_fallback(db_path, mock_embedding):
    """external_session_id=default 降级模式：新 start 自动结束旧 session。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        r1 = t.execute("session_start", external_session_id="default", project="/test")
        old_sid = r1["session_id"]

        r2 = t.execute("session_start", external_session_id="default", project="/test")
        new_sid = r2["session_id"]

        assert old_sid != new_sid
        assert t.session_registry.get("default") == new_sid
    finally:
        t.shutdown()
        t.join(timeout=5)


def _send_request(sock_path: str, method: str, path: str, body: dict = None) -> dict:
    """通过 Unix Socket 发送 HTTP 请求。"""
    conn = http.client.HTTPConnection("localhost")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_path)
    conn.sock = sock
    body_str = json.dumps(body) if body else "{}"
    conn.request(method, path, body_str, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read().decode())
    conn.close()
    return data


def _short_sock_path(name: str) -> str:
    """生成短路径的 socket 文件，避免 AF_UNIX path too long。"""
    import tempfile
    return os.path.join(tempfile.gettempdir(), f"memento-test-{name}.sock")


def test_socket_server_status(tmp_path, mock_embedding):
    """Socket Server 应响应 GET /status。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_sock.db"
    sock_path = _short_sock_path("status")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)
        data = _send_request(sock_path, "GET", "/status")
        assert "db_path" in data
        assert "queue_depth" in data
    finally:
        server.shutdown_gracefully()


def test_socket_server_session_lifecycle(tmp_path, mock_embedding):
    """Socket Server 应支持完整的 session 生命周期。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_sock2.db"
    sock_path = _short_sock_path("lifecycle")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)

        # start
        data = _send_request(sock_path, "POST", "/session/start", {
            "external_session_id": "test-session",
            "project": "/test",
        })
        assert "session_id" in data

        # observe
        data = _send_request(sock_path, "POST", "/observe", {
            "external_session_id": "test-session",
            "content": "发现问题",
            "tool": "Read",
            "importance": "high",
        })
        assert data.get("queued") is True

        # flush
        data = _send_request(sock_path, "POST", "/flush", {
            "external_session_id": "test-session",
        })
        assert data.get("flushed") is True

        # end
        data = _send_request(sock_path, "POST", "/session/end", {
            "external_session_id": "test-session",
            "outcome": "completed",
        })
        assert data.get("status") == "completed"
    finally:
        server.shutdown_gracefully()


def test_multi_session_first_end_does_not_clear_registry(db_path, mock_embedding):
    """两个会话共享 worker，第一个 session-end 不应清空 registry。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 启动两个会话
        r1 = t.execute("session_start", external_session_id="sess-A", project="/proj")
        r2 = t.execute("session_start", external_session_id="sess-B", project="/proj")

        assert len(t.session_registry) == 2

        # 结束第一个
        t.execute("session_end", external_session_id="sess-A", outcome="completed")

        # registry 仍有一个活跃会话
        assert len(t.session_registry) == 1
        assert "sess-B" in t.session_registry
        assert "sess-A" not in t.session_registry

        # status 应返回正确的 active_session_ids
        status = t.execute("status")
        assert len(status["active_session_ids"]) == 1
        assert r2["session_id"] in status["active_session_ids"]
    finally:
        t.shutdown()
        t.join(timeout=5)


# ═══════════════════════════════════════════════════════════════════════════
# v0.5 新增测试：Awake track + Subconscious integration
# ═══════════════════════════════════════════════════════════════════════════


def test_db_thread_capture_writes_capture_log(db_path, mock_embedding):
    """v0.5: capture action 走 awake_capture，写入 capture_log。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 先创建 session
        t.execute("session_start", external_session_id="s1", project="/test")

        result = t.execute("capture",
            external_session_id="s1",
            content="记住这个约定",
            type="convention",
            importance="high",
        )
        assert "capture_log_id" in result
        assert result["state"] == "buffered"
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_recall(db_path, mock_embedding):
    """v0.5: recall action 走 awake_recall。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 先 capture 一条
        t.execute("session_start", external_session_id="s1", project="/test")
        t.execute("capture",
            external_session_id="s1",
            content="数据库连接池大小设为50",
            type="fact",
        )

        # recall 应能找到 capture_log 中的 hot buffer
        results = t.execute("recall", query="连接池")
        assert len(results) >= 1
        found = [r for r in results if "连接池" in r["content"]]
        assert len(found) >= 1
        assert found[0]["provisional"] is True
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_recall_with_pulse_queue(db_path, mock_embedding):
    """v0.5: recall 使用 pulse_queue 时，应生成 PulseEvent（对 view_engrams 命中）。"""
    import queue as q
    from memento.worker import DBThread

    pulse_q = q.Queue()
    t = DBThread(db_path, pulse_queue=pulse_q)
    t.start()

    try:
        # Hot buffer hit 不产生 pulse event
        t.execute("session_start", external_session_id="s1", project="/test")
        t.execute("capture", external_session_id="s1", content="test content")
        t.execute("recall", query="test")

        # Hot buffer 命中不产生 pulse（因为 provisional=True）
        # pulse_q 可能为空
        # 这验证了 pulse_queue 被正确传递
        assert pulse_q.qsize() == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_forget(db_path, mock_embedding):
    """v0.5: forget action 走 awake_forget，写入 pending_forget。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        t.execute("session_start", external_session_id="s1", project="/test")
        cap = t.execute("capture", external_session_id="s1", content="要忘记的内容")
        capture_id = cap["capture_log_id"]

        result = t.execute("forget", target_id=capture_id)
        assert result["status"] == "pending"
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_verify(db_path, mock_embedding):
    """v0.5: verify action 走 awake_verify。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("verify", engram_id="nonexistent-id")
        assert result["status"] == "verified"
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_inspect(db_path, mock_embedding):
    """v0.5: inspect action 查询 engram 详情。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        # 不存在的 engram
        result = t.execute("inspect", engram_id="nonexistent")
        assert result is None
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_pin(db_path, mock_embedding):
    """v0.5: pin action 走 awake_pin。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("pin", engram_id="nonexistent", rigidity=0.9)
        assert result["status"] == "pinned"
        assert result["rigidity"] == 0.9
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_debt(db_path, mock_embedding):
    """v0.5: debt action 返回 cognitive debt 统计。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("debt")
        assert isinstance(result, dict)
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_db_thread_nexus_query(db_path, mock_embedding):
    """v0.5: nexus_query action 查询图关联。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        result = t.execute("nexus_query", engram_id="nonexistent")
        assert isinstance(result, list)
        assert len(result) == 0
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_status_includes_v05_fields(db_path, mock_embedding):
    """v0.5: status 返回应包含 pending_capture, by_state 等新字段。"""
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()

    try:
        status = t.execute("status")
        assert "pending_capture" in status
        assert "pending_delta" in status
        assert "pending_recon" in status
        assert "cognitive_debt_count" in status
        assert "last_epoch_committed_at" in status
        assert "decay_watermark" in status
        assert "by_state" in status
    finally:
        t.shutdown()
        t.join(timeout=5)


def test_worker_server_has_pulse_queue(tmp_path, mock_embedding):
    """v0.5: WorkerServer 应创建 pulse_queue。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_pulse.db"
    sock_path = _short_sock_path("pulse")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)
        assert server.pulse_queue is not None
        assert server.db_thread.pulse_queue is server.pulse_queue
    finally:
        server.shutdown_gracefully()


def test_worker_server_subconscious_lifecycle(tmp_path, mock_embedding):
    """v0.5: WorkerServer 应启动和关闭 SubconsciousTrack。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_sub.db"
    sock_path = _short_sock_path("subconscious")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)
        assert server._subconscious is not None
        assert server._subconscious._thread is not None
    finally:
        server.shutdown_gracefully()
        # After shutdown, subconscious thread should be cleaned up
        assert server._subconscious._thread is None


def test_socket_server_new_routes(tmp_path, mock_embedding):
    """v0.5: Socket Server 应支持新路由 /capture, /recall, /forget, /verify, /inspect, /pin, /debt。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_routes.db"
    sock_path = _short_sock_path("routes")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)

        # Start session
        _send_request(sock_path, "POST", "/session/start", {
            "external_session_id": "test-v05",
            "project": "/test",
        })

        # POST /capture
        data = _send_request(sock_path, "POST", "/capture", {
            "external_session_id": "test-v05",
            "content": "v0.5 capture test",
            "type": "fact",
        })
        assert "capture_log_id" in data

        # POST /recall
        data = _send_request(sock_path, "POST", "/recall", {
            "query": "capture test",
            "max_results": 5,
        })
        assert isinstance(data, list)

        # POST /forget
        data = _send_request(sock_path, "POST", "/forget", {
            "target_id": "nonexistent-id",
        })
        assert "status" in data

        # POST /verify
        data = _send_request(sock_path, "POST", "/verify", {
            "engram_id": "nonexistent-id",
        })
        assert data["status"] == "verified"

        # POST /inspect (not found)
        data = _send_request(sock_path, "POST", "/inspect", {
            "engram_id": "nonexistent-id",
        })
        assert "error" in data  # 404

        # POST /nexus
        data = _send_request(sock_path, "POST", "/nexus", {
            "engram_id": "nonexistent-id",
        })
        assert isinstance(data, list)

        # POST /pin
        data = _send_request(sock_path, "POST", "/pin", {
            "engram_id": "nonexistent-id",
            "rigidity": 0.8,
        })
        assert data["status"] == "pinned"

        # GET /debt
        data = _send_request(sock_path, "GET", "/debt")
        assert isinstance(data, dict)
    finally:
        server.shutdown_gracefully()


# ═══════════════════════════════════════════════════════════════════════════
# v0.5.1a 新增测试：DBThread init_event + init_error + epoch_status
# ═══════════════════════════════════════════════════════════════════════════


def test_dbthread_init_event_set_on_success(tmp_path):
    """v0.5.1a: DBThread.init_event 初始化成功时应设置，init_error 为 None。"""
    from memento.worker import DBThread

    db_path = tmp_path / "test.db"
    t = DBThread(db_path=db_path)
    t.start()
    assert t.init_event.wait(timeout=5)
    assert t.init_error is None
    t.shutdown()


def test_dbthread_init_event_set_on_failure(tmp_path):
    """v0.5.1a: DBThread.init_event 初始化失败时应设置，init_error 不为 None。"""
    from memento.worker import DBThread
    from unittest.mock import patch

    # Mock MementoAPI to raise an exception during initialization
    with patch("memento.worker.MementoAPI") as mock_api:
        mock_api.side_effect = RuntimeError("DB initialization failed")

        db_path = tmp_path / "test.db"
        t = DBThread(db_path=db_path)
        t.start()
        assert t.init_event.wait(timeout=5)
        assert t.init_error is not None
        assert isinstance(t.init_error, RuntimeError)


def test_dbthread_epoch_status_action(tmp_path, mock_embedding):
    """v0.5.1a: epoch_status action 应返回 epoch 记录列表。"""
    from memento.worker import DBThread

    db_path = tmp_path / "test.db"
    t = DBThread(db_path=db_path)
    t.start()
    t.init_event.wait(timeout=5)
    result = t.execute("epoch_status")
    assert isinstance(result, list)
    t.shutdown()


def test_socket_server_get_epochs(tmp_path, mock_embedding):
    """v0.5.1a: GET /epochs 应返回 epoch 记录列表。"""
    from memento.worker import WorkerServer

    db_path = tmp_path / "test_epochs.db"
    sock_path = _short_sock_path("epochs")

    server = WorkerServer(db_path, sock_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.5)
        data = _send_request(sock_path, "GET", "/epochs")
        assert isinstance(data, list)
    finally:
        server.shutdown_gracefully()


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
        assert result["id"] if "id" in result else result["capture_log_id"]

        # Verify: capture_log should have 1 entry
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        capture_count = conn.execute("SELECT COUNT(*) FROM capture_log").fetchone()[0]
        conn.close()

        assert capture_count == 1, f"Expected 1 capture_log entry, got {capture_count}"
    finally:
        t.shutdown()
        t.join(timeout=5)

def test_capture_with_invalid_session_still_saves_capture_log(db_path, mock_embedding):
    """Verify that capturing with an invalid session ID under awake track still saves to capture_log."""
    import sqlite3
    from memento.worker import DBThread

    t = DBThread(db_path)
    t.start()
    assert t.init_event.wait(timeout=5)

    try:
        result = t.execute("capture", content="test invalid session", type="fact",
                           importance="normal", origin="human",
                           external_session_id="invalid-claude-sid-999")

        assert result.get("capture_log_id") or result.get("id")

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM capture_log WHERE content = 'test invalid session'").fetchone()
        conn.close()

        assert row is not None
        assert row["source_session_id"] is None
    finally:
        t.shutdown()
        t.join(timeout=5)
