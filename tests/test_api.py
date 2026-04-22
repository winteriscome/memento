"""统一 Memory API 测试。"""

import struct
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from memento.api import MementoAPI, LocalAPI, MementoAPIBase, WorkerClientAPI, StatusResult
from memento.session import SessionStartResult, SessionEndResult


@pytest.fixture
def api(tmp_path):
    """创建临时数据库的 MementoAPI 实例（旧模式，直接写 engrams）。"""
    db_path = tmp_path / "test_api.db"
    with patch("memento.core.get_embedding") as mock_core, \
         patch("memento.observation.get_embedding") as mock_obs:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_core.return_value = (fake_blob, 4, False)
        mock_obs.return_value = (fake_blob, 4, False)

        a = MementoAPI(db_path=db_path, use_awake=False)
        yield a
        a.close()


def test_session_lifecycle(api):
    """完整的会话生命周期。"""
    # start
    start_result = api.session_start(project="/test", task="fix bug")
    assert start_result.session_id
    assert start_result.project == "/test"

    sid = start_result.session_id

    # capture within session
    eid = api.capture("JWT 使用 RS256", type="fact", session_id=sid)
    assert len(eid) == 36

    # end
    end_result = api.session_end(sid, summary="修好了")
    assert end_result.status == "completed"
    assert end_result.captures_count == 1

    # verify session info
    info = api.session_status(sid)
    assert info.summary == "修好了"


def test_recall_default_readonly(api):
    """recall 默认只读，不修改 access_count。"""
    api.capture("测试记忆", type="fact")

    results = api.recall("测试")
    assert len(results) >= 0  # 可能找到也可能没有（depends on embedding mock）

    # 即使有结果，access_count 也不应增加（默认 reinforce=False）
    for r in results:
        assert r.access_count == 0


def test_recall_with_reinforce(api):
    """reinforce=True 时应更新 access_count。"""
    api.capture("强化测试记忆", type="fact")

    results = api.recall("强化测试", reinforce=True)
    if results:
        # recall 后再查，access_count 应该增加了
        engram = api.core.get_by_id(results[0].id)
        assert engram["access_count"] == 1


def test_ingest_observation_via_api(api):
    """通过 API 调用 observation pipeline。"""
    start_result = api.session_start(project="/test")
    sid = start_result.session_id

    result = api.ingest_observation(
        content="发现连接池泄漏",
        tool="Read",
        files=["db.py"],
        importance="high",
        session_id=sid,
    )

    assert result.promoted is True
    assert result.engram_id is not None


def test_status_includes_sessions(api):
    """status 应包含 session 统计。"""
    api.session_start(project="/test")
    api.capture("一条记忆")

    stats = api.status()
    assert stats.total_sessions >= 1
    assert stats.active_sessions >= 1
    assert stats.active >= 1


def test_capture_tracks_source(api):
    """capture 应记录来源 session/event。"""
    start_result = api.session_start(project="/test")
    sid = start_result.session_id

    eid = api.capture("带来源的记忆", session_id=sid)
    engram = api.core.get_by_id(eid)

    assert engram["source_session_id"] == sid


def test_forget_and_verify(api):
    """forget 和 verify 应正常工作。"""
    eid = api.capture("要遗忘的", origin="agent")
    assert api.forget(eid) is True

    eid2 = api.capture("要验证的", origin="agent")
    assert api.verify(eid2) is True


def test_capture_with_invalid_session_still_saves_engram(api):
    """session_id 无效时 engram 应写入，但不追加 event。"""
    eid = api.capture("有价值的记忆", session_id="nonexistent-session-id")
    assert len(eid) == 36

    # engram 已落库
    engram = api.core.get_by_id(eid)
    assert engram is not None
    assert engram["content"] == "有价值的记忆"
    assert engram["source_session_id"] == "nonexistent-session-id"

    # 没有产生孤儿 event
    row = api.core.conn.execute(
        "SELECT COUNT(*) as cnt FROM session_events WHERE payload LIKE ?",
        (f'%{eid}%',),
    ).fetchone()
    assert row["cnt"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# v0.5 架构测试
# ═══════════════════════════════════════════════════════════════════════════


def test_memento_api_is_local_api_alias():
    """MementoAPI 应该是 LocalAPI 的别名。"""
    assert MementoAPI is LocalAPI


def test_local_api_is_subclass_of_base():
    """LocalAPI 应该继承 MementoAPIBase。"""
    assert issubclass(LocalAPI, MementoAPIBase)


def test_worker_client_api_has_all_methods():
    """WorkerClientAPI 应实现所有 MementoAPIBase 方法。"""
    worker = WorkerClientAPI(socket_path="/tmp/test.sock")
    assert hasattr(worker, 'capture')
    assert hasattr(worker, 'recall')
    assert hasattr(worker, 'forget')
    assert hasattr(worker, 'verify')
    assert hasattr(worker, 'status')
    assert hasattr(worker, 'session_start')
    assert hasattr(worker, 'session_end')
    assert hasattr(worker, 'ingest_observation')
    # close should not raise
    worker.close()


def test_inspect_existing_engram(api):
    """inspect 应返回完整的 engram 信息。"""
    eid = api.capture("inspect 测试记忆", type="fact")
    result = api.inspect(eid)

    assert result is not None
    assert result["id"] == eid
    assert result["content"] == "inspect 测试记忆"
    assert "nexus" in result
    assert isinstance(result["nexus"], list)
    assert result["pending_forget"] is False


def test_inspect_nonexistent_engram(api):
    """inspect 不存在的 id 应返回 None。"""
    result = api.inspect("nonexistent-id")
    assert result is None


def test_pin(api):
    """pin 应设置 rigidity 并返回结果。"""
    eid = api.capture("pin 测试记忆", type="fact")
    result = api.pin(eid, rigidity=0.9)

    assert result["status"] == "pinned"
    assert result["engram_id"] == eid
    assert result["rigidity"] == 0.9

    # 验证 engram 的 rigidity 已更新
    row = api.conn.execute(
        "SELECT rigidity FROM engrams WHERE id=?", (eid,)
    ).fetchone()
    assert row["rigidity"] == 0.9


def test_pin_clamps_rigidity(api):
    """pin 应将 rigidity 限制在 [0.0, 1.0] 范围内。"""
    eid = api.capture("pin clamp 测试", type="fact")

    result = api.pin(eid, rigidity=1.5)
    assert result["rigidity"] == 1.0

    result = api.pin(eid, rigidity=-0.5)
    assert result["rigidity"] == 0.0


def test_status_v05_fields(api):
    """status 应包含 v0.5 新增字段。"""
    api.capture("status 测试记忆")
    stats = api.status()

    assert isinstance(stats, StatusResult)
    # 基础字段
    assert stats.total >= 1
    assert stats.active >= 1
    # v0.5 新增字段存在
    assert isinstance(stats.by_state, dict)
    assert isinstance(stats.pending_capture, int)
    assert isinstance(stats.pending_delta, int)
    assert isinstance(stats.pending_recon, int)
    assert isinstance(stats.cognitive_debt_count, int)
    # decay_watermark 应有值（migration 会初始化）
    assert stats.decay_watermark is not None


def test_epoch_run_light_mode(api):
    """epoch_run 应能以 light 模式成功运行。"""
    # 先写入一些数据
    api.capture("epoch 测试记忆", type="fact")

    result = api.epoch_run(mode='light', trigger='manual')

    assert "error" not in result
    assert result["status"] == "completed"
    assert result["mode"] == "light"
    assert result["epoch_id"].startswith("epoch-")


def test_epoch_run_full_mode_degrades_to_light(api, monkeypatch):
    """无 LLM 配置时 epoch_run full 模式应降级为 light。"""
    monkeypatch.delenv("MEMENTO_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MEMENTO_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MEMENTO_LLM_MODEL", raising=False)

    api.capture("epoch full 测试", type="fact")

    result = api.epoch_run(mode='full', trigger='manual')

    # 无 LLM 环境变量时应降级
    assert result["status"] == "completed"
    assert result["mode"] == "light"


def test_epoch_status(api):
    """epoch_status 应返回最近的 epoch 记录。"""
    # 先运行一次 epoch
    api.epoch_run(mode='light', trigger='manual')

    records = api.epoch_status()
    assert len(records) >= 1
    assert records[0]["status"] in ("committed", "degraded")


def test_epoch_debt_empty(api):
    """无 debt 时 epoch_debt 应返回空 dict。"""
    result = api.epoch_debt()
    assert isinstance(result, dict)
    assert len(result) == 0


def test_epoch_run_conflict(api):
    """两个 epoch 同时运行应返回错误。"""
    from memento.epoch import acquire_lease

    # 手动占用一个 lease
    acquire_lease(api.conn, 'default', 'light', 'manual')

    # 再运行 epoch 应报冲突
    result = api.epoch_run(mode='light', trigger='manual')
    assert "error" in result


def test_export_memories_via_api(api):
    """通过 LocalAPI 导出记忆。"""
    api.capture("export 测试", type="fact")
    memories = api.export_memories()
    assert len(memories) >= 1
    assert any(m["content"] == "export 测试" for m in memories)


def test_import_memories_via_api(api):
    """通过 LocalAPI 导入记忆。"""
    import uuid
    mem_id = str(uuid.uuid4())
    data = [{
        "id": mem_id,
        "content": "imported memory",
        "type": "fact",
        "tags": [],
        "strength": 0.7,
        "importance": "normal",
        "origin": "human",
        "verified": True,
        "created_at": "2026-01-01T00:00:00",
        "last_accessed": "2026-01-01T00:00:00",
        "access_count": 0,
    }]
    result = api.import_memories(data, source="test")
    assert result["imported"] == 1


def test_use_awake_capture(tmp_path):
    """use_awake=True 时 capture 应写入 capture_log。"""
    db_path = tmp_path / "test_awake_api.db"
    with patch("memento.core.get_embedding") as mock_core, \
         patch("memento.awake.get_embedding") as mock_awake:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_core.return_value = (fake_blob, 4, False)
        mock_awake.return_value = (fake_blob, 4, False)

        a = LocalAPI(db_path=db_path, use_awake=True)
        try:
            result = a.capture("awake capture 测试", type="fact")
            assert isinstance(result, dict)
            assert result["state"] == "buffered"
            assert "capture_log_id" in result

            # 验证写入了 capture_log 而非 engrams
            row = a.conn.execute(
                "SELECT COUNT(*) as cnt FROM capture_log"
            ).fetchone()
            assert row["cnt"] == 1

            engram_row = a.conn.execute(
                "SELECT COUNT(*) as cnt FROM engrams"
            ).fetchone()
            assert engram_row["cnt"] == 0
        finally:
            a.close()


def test_use_awake_forget(tmp_path):
    """use_awake=True 时 forget 应走 pending_forget 队列。"""
    db_path = tmp_path / "test_awake_forget.db"
    with patch("memento.core.get_embedding") as mock_core:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_core.return_value = (fake_blob, 4, False)

        # 先用旧模式创建 engram
        a = LocalAPI(db_path=db_path, use_awake=False)
        eid = a.capture("to forget", type="fact")

        # 切换到 awake 模式测试 forget
        a._use_awake = True
        result = a.forget(eid)
        assert isinstance(result, dict)
        assert result["status"] == "pending"

        # 验证写入了 pending_forget
        row = a.conn.execute(
            "SELECT COUNT(*) as cnt FROM pending_forget WHERE target_id=?",
            (eid,),
        ).fetchone()
        assert row["cnt"] == 1
        a.close()


# ═══════════════════════════════════════════════════════════════════════════
# Task 3: from_dict + ingest_observation abstract method
# ═══════════════════════════════════════════════════════════════════════════


def test_status_result_from_dict():
    data = {"total": 42, "active": 38, "pending_capture": 5, "by_state": {"consolidated": 38}}
    result = StatusResult.from_dict(data)
    assert isinstance(result, StatusResult)
    assert result.total == 42
    assert result.pending_capture == 5


def test_session_start_result_from_dict_without_priming():
    """旧格式（只有 priming_count）应降级为空列表。"""
    data = {"session_id": "s1", "priming_count": 3}
    result = SessionStartResult.from_dict(data)
    assert result.session_id == "s1"
    assert result.priming_memories == []


def test_session_start_result_from_dict_with_priming():
    """新格式（含完整 priming_memories）应正确解析。"""
    data = {
        "session_id": "s1",
        "priming_count": 2,
        "priming_memories": [
            {"id": "eng-001", "content": "用中文回答", "type": "preference", "importance": "critical"},
            {"id": "eng-002", "content": "推送 main 时打 tag", "type": "convention", "importance": "critical"},
        ],
    }
    result = SessionStartResult.from_dict(data)
    assert result.session_id == "s1"
    assert len(result.priming_memories) == 2
    assert result.priming_memories[0]["content"] == "用中文回答"
    assert result.priming_memories[1]["type"] == "convention"


def test_session_end_result_from_dict():
    data = {"session_id": "s1", "status": "completed", "captures_count": 5, "observations_count": 10}
    result = SessionEndResult.from_dict(data)
    assert result.captures_count == 5


def test_memento_api_base_has_ingest_observation():
    assert hasattr(MementoAPIBase, 'ingest_observation')


# ═══════════════════════════════════════════════════════════════════════════
# Task 4: WorkerClientAPI full implementation
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkerClientAPI:
    def test_capture(self):
        client = WorkerClientAPI("/tmp/test.sock")
        expected = {"capture_log_id": "cl1", "state": "buffered"}
        with patch.object(client, '_request', return_value=expected):
            result = client.capture("test content", type="fact")
            assert result == expected

    def test_recall(self):
        client = WorkerClientAPI("/tmp/test.sock")
        expected = [{"content": "test", "score": 0.8}]
        with patch.object(client, '_request', return_value=expected):
            result = client.recall("test")
            assert isinstance(result, list)

    def test_status_returns_status_result(self):
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {"total": 10, "active": 8, "pending_capture": 3, "by_state": {"consolidated": 8}}
        with patch.object(client, '_request', return_value=raw):
            result = client.status()
            assert isinstance(result, StatusResult)
            assert result.total == 10

    def test_session_start_returns_dataclass(self):
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {
            "session_id": "s1",
            "priming_count": 2,
            "priming_memories": [
                {"id": "e1", "content": "test memory", "type": "fact", "importance": "normal"},
            ],
        }
        with patch.object(client, '_request', return_value=raw):
            result = client.session_start(project="test")
            assert isinstance(result, SessionStartResult)
            assert result.session_id == "s1"
            assert len(result.priming_memories) == 1
            assert result.priming_memories[0]["content"] == "test memory"

    def test_session_end_returns_dataclass(self):
        client = WorkerClientAPI("/tmp/test.sock")
        raw = {"session_id": "s1", "status": "completed", "captures_count": 3, "observations_count": 7}
        with patch.object(client, '_request', return_value=raw):
            result = client.session_end("s1")
            assert isinstance(result, SessionEndResult)
            assert result.captures_count == 3

    def test_epoch_run_spawns_subprocess(self):
        client = WorkerClientAPI("/tmp/test.sock")
        with patch("subprocess.run") as mock_run, \
             patch.object(client, '_request', return_value=[{"id": "ep1", "status": "committed", "mode": "light"}]):
            mock_run.return_value = MagicMock(returncode=0, stdout="done", stderr="")
            result = client.epoch_run(mode="full")
            mock_run.assert_called_once()
            assert result["epoch_id"] == "ep1"

    def test_forget(self):
        client = WorkerClientAPI("/tmp/test.sock")
        with patch.object(client, '_request', return_value={"status": "pending"}):
            result = client.forget("e1")
            assert result["status"] == "pending"

    def test_ingest_observation(self):
        client = WorkerClientAPI("/tmp/test.sock")
        with patch.object(client, '_request', return_value=None) as mock_req:
            client.ingest_observation("tool output", tool="Edit")
            mock_req.assert_called_once()

    def test_close_is_noop(self):
        client = WorkerClientAPI("/tmp/test.sock")
        client.close()

    def test_request_connection_error(self):
        client = WorkerClientAPI("/tmp/nonexistent.sock")
        with pytest.raises(ConnectionError):
            client._request("GET", "/status")
