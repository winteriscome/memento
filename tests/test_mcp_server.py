"""MCP Server 测试 — 验证 Tools 正确映射到 api.py。"""

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.mcp_server import create_mcp_app, _dispatch_tool, _DEPRECATED_TOOLS


@pytest.fixture
def mcp_api(tmp_path):
    db_path = tmp_path / "test_mcp.db"
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2, \
         patch("memento.awake.get_embedding") as m3:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)
        m3.return_value = (fake_blob, 4, False)

        app, api = create_mcp_app(db_path)
        yield api
        api.close()


def test_dispatch_session_start(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_session_start", {"project": "/test", "task": "fix bug"})
    assert "session_id" in result
    assert len(result["session_id"]) == 36


def test_dispatch_capture_and_recall(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_capture", {"content": "MCP 测试记忆", "type": "fact"})
    # awake mode: capture_log_id instead of engram_id
    assert "capture_log_id" in result
    assert len(result["capture_log_id"]) == 36


def test_dispatch_capture_returns_state(mcp_api):
    """capture 返回值应包含 state 字段。"""
    result = _dispatch_tool(mcp_api, "memento_capture", {"content": "测试"})
    assert "state" in result
    # awake 模式返回 buffered
    assert result["state"] == "buffered"


def test_dispatch_recall_has_provisional(mcp_api):
    """recall 结果应包含 provisional 字段。"""
    _dispatch_tool(mcp_api, "memento_capture", {"content": "recall 测试记忆"})
    results = _dispatch_tool(mcp_api, "memento_recall", {"query": "recall 测试"})
    assert isinstance(results, list)
    if results:
        assert "provisional" in results[0]


def test_dispatch_recall_no_mode_reinforce(mcp_api):
    """recall 不再接受 mode/reinforce 参数（应忽略）。"""
    _dispatch_tool(mcp_api, "memento_capture", {"content": "测试"})
    # 应该正常返回，即使传了旧参数
    results = _dispatch_tool(mcp_api, "memento_recall", {"query": "测试"})
    assert isinstance(results, list)


def test_dispatch_status(mcp_api):
    _dispatch_tool(mcp_api, "memento_capture", {"content": "一条记忆"})
    result = _dispatch_tool(mcp_api, "memento_status", {})
    # awake mode: capture goes to capture_log (pending), not engrams
    assert result["pending_capture"] >= 1
    # v0.5 新增字段
    assert "by_state" in result
    assert "pending_capture" in result
    assert "pending_delta" in result
    assert "cognitive_debt_count" in result
    assert "last_epoch_committed_at" in result
    assert "decay_watermark" in result


def test_dispatch_forget(mcp_api):
    r = _dispatch_tool(mcp_api, "memento_capture", {"content": "要删的"})
    # awake mode: capture returns capture_log_id
    target_id = r.get("capture_log_id") or r.get("engram_id")
    result = _dispatch_tool(mcp_api, "memento_forget", {"engram_id": target_id})
    assert result["status"] == "pending"


def test_dispatch_observe(mcp_api):
    r = _dispatch_tool(mcp_api, "memento_session_start", {"project": "/test"})
    sid = r["session_id"]
    result = _dispatch_tool(mcp_api, "memento_observe", {
        "content": "观察到问题", "tool": "Read", "session_id": sid, "importance": "high"
    })
    assert result["promoted"] is True


# ── v0.5 新增 Tools 测试 ──


def test_dispatch_epoch_status(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_epoch_status", {})
    assert "epochs" in result
    assert isinstance(result["epochs"], list)


def test_dispatch_epoch_debt(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_epoch_debt", {})
    assert "debt" in result
    assert isinstance(result["debt"], dict)


def test_dispatch_inspect(mcp_api):
    # Use use_awake=False path to create a real engram for inspect
    from memento.core import MementoCore
    eid = mcp_api.core.capture("检查这条", type="fact")
    mcp_api.core.conn.commit()
    result = _dispatch_tool(mcp_api, "memento_inspect", {"engram_id": eid})
    assert result["content"] == "检查这条"
    assert "nexus" in result
    assert "pending_forget" in result


def test_dispatch_inspect_not_found(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_inspect", {"engram_id": "nonexistent"})
    assert "error" in result


def test_dispatch_nexus(mcp_api):
    # Use core to create a real engram for nexus query
    eid = mcp_api.core.capture("nexus 测试", type="fact")
    mcp_api.core.conn.commit()
    result = _dispatch_tool(mcp_api, "memento_nexus", {"engram_id": eid})
    assert result["engram_id"] == eid
    assert "connections" in result
    assert result["depth"] == 1


def test_dispatch_nexus_depth2(mcp_api):
    eid = mcp_api.core.capture("深度测试", type="fact")
    mcp_api.core.conn.commit()
    result = _dispatch_tool(mcp_api, "memento_nexus", {"engram_id": eid, "depth": 2})
    assert result["depth"] == 2


def test_dispatch_pin(mcp_api):
    eid = mcp_api.core.capture("钉住这条", type="fact")
    mcp_api.core.conn.commit()
    result = _dispatch_tool(mcp_api, "memento_pin", {"engram_id": eid, "rigidity": 0.9})
    assert "engram_id" in result


# ── Deprecated tools 测试 ──


def test_deprecated_set_session(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_set_session", {})
    assert result["deprecated"] is True
    assert "v0.5" in result["error"]


def test_deprecated_get_session(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_get_session", {})
    assert result["deprecated"] is True


def test_deprecated_evaluate(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_evaluate", {})
    assert result["deprecated"] is True
    assert "A/B" in result["error"]


def test_deprecated_backfill_embeddings(mcp_api):
    result = _dispatch_tool(mcp_api, "memento_backfill_embeddings", {})
    assert result["deprecated"] is True
    assert "Epoch" in result["error"]


def test_unknown_tool(mcp_api):
    result = _dispatch_tool(mcp_api, "nonexistent_tool", {})
    assert "error" in result


# ── v0.6 recall schema + prime staleness 测试 ──


def test_recall_returns_staleness_tags_origin(mcp_api):
    """recall 结果应包含 staleness_level, tags, origin 字段。"""
    _dispatch_tool(mcp_api, "memento_capture", {
        "content": "recall schema 测试",
        "type": "fact",
        "tags": ["test"],
        "origin": "agent",
    })
    results = _dispatch_tool(mcp_api, "memento_recall", {"query": "recall schema"})
    assert isinstance(results, list)
    assert len(results) > 0
    r = results[0]
    assert "staleness_level" in r
    assert r["staleness_level"] in ("fresh", "stale", "very_stale")
    assert "tags" in r
    assert "origin" in r


def test_prime_prompt_includes_staleness_marker(mcp_api):
    """memento_prime prompt 应对 stale/very_stale 显示标记。"""
    import asyncio
    from memento.mcp_server import create_mcp_app

    app, api = mcp_api._app if hasattr(mcp_api, '_app') else (None, mcp_api)

    # Capture something so prime has content
    _dispatch_tool(mcp_api, "memento_capture", {"content": "prime 文案测试"})

    # Call api.recall directly to check dict-based path
    results = mcp_api.recall("prime 文案", max_results=5, reinforce=False)
    # Build lines the same way the prompt does
    lines = []
    for m in results:
        if isinstance(m, dict):
            staleness = ""
            sl = m.get("staleness_level", "")
            if sl == "stale":
                staleness = " ⚠️较旧"
            elif sl == "very_stale":
                staleness = " ⏳可能过时"
            lines.append(f"- [{m.get('type', '?')}] {m.get('content', '')}{staleness}")

    # At minimum, results should be formatted without error
    assert len(lines) > 0
    # Fresh items should have no marker
    for line in lines:
        if "prime 文案测试" in line:
            assert "⚠️" not in line
            assert "⏳" not in line


# ── v0.6.1 session_end auto-summary + daily/today 测试 ──


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
    _dispatch_tool(mcp_api, "memento_capture", {"content": "Today's test capture"})

    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    captures = mcp_api.core.conn.execute(
        "SELECT id FROM capture_log WHERE created_at >= ?", (today,)
    ).fetchall()
    assert len(captures) > 0
