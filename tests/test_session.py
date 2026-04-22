"""Session lifecycle 测试。"""

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.core import MementoCore
from memento.session import SessionService


@pytest.fixture
def db_conn(tmp_path):
    """创建临时数据库连接。"""
    db_path = tmp_path / "test_session.db"
    with patch("memento.core.get_embedding") as mock_embed:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_embed.return_value = (fake_blob, 4, False)
        core = MementoCore(db_path=db_path)
        yield core.conn, core
        core.close()


@pytest.fixture
def session_svc(db_conn):
    conn, _ = db_conn
    return SessionService(conn)


def test_session_start_creates_record(session_svc):
    """session start 应创建 session 记录。"""
    sid = session_svc.start(project="/test/project", task="fix bug")
    assert len(sid) == 36

    info = session_svc.get(sid)
    assert info is not None
    assert info.project == "/test/project"
    assert info.task == "fix bug"
    assert info.status == "active"


def test_session_end_updates_status(session_svc):
    """session end 应更新状态和摘要。"""
    sid = session_svc.start(project="/test", task="task1")
    result = session_svc.end(sid, outcome="completed", summary="修复了认证 bug")

    assert result.status == "completed"

    info = session_svc.get(sid)
    assert info.status == "completed"
    assert info.summary == "修复了认证 bug"
    assert info.ended_at is not None


def test_session_events_appended(session_svc):
    """事件应正确追加到 session_events。"""
    sid = session_svc.start(project="/test")

    # start 事件已自动追加
    info = session_svc.get(sid)
    assert info.event_counts.get("start") == 1

    # 手动追加事件
    eid = session_svc.append_event(sid, "recall", {"query": "test"})
    assert len(eid) == 36

    session_svc.conn.commit()
    info = session_svc.get(sid)
    assert info.event_counts.get("recall") == 1


def test_session_list(session_svc):
    """list_sessions 应返回最近会话。"""
    session_svc.start(project="/proj1", task="task1")
    session_svc.start(project="/proj2", task="task2")

    all_sessions = session_svc.list_sessions()
    assert len(all_sessions) == 2

    proj1_sessions = session_svc.list_sessions(project="/proj1")
    assert len(proj1_sessions) == 1
    assert proj1_sessions[0].project == "/proj1"


def test_get_active_session(session_svc):
    """get_active_session 应返回当前活跃会话。"""
    sid1 = session_svc.start(project="/test", task="task1")
    session_svc.end(sid1, outcome="completed")

    sid2 = session_svc.start(project="/test", task="task2")

    active = session_svc.get_active_session()
    assert active is not None
    assert active.id == sid2
    assert active.status == "active"


def test_fingerprint_dedup(session_svc):
    """has_fingerprint 应检测重复。"""
    sid = session_svc.start()
    session_svc.append_event(sid, "observation", fingerprint="abc123")
    session_svc.conn.commit()

    assert session_svc.has_fingerprint(sid, "abc123") is True
    assert session_svc.has_fingerprint(sid, "xyz789") is False


def test_end_nonexistent_session_returns_none(session_svc):
    """end 不存在的 session 应返回 None。"""
    result = session_svc.end("nonexistent-id", outcome="completed")
    assert result is None


def test_end_already_ended_session_returns_none(session_svc):
    """end 已结束的 session 应返回 None。"""
    sid = session_svc.start(project="/test")
    session_svc.end(sid)
    result = session_svc.end(sid)
    assert result is None


@pytest.fixture
def api_fixture(tmp_path):
    """创建 MementoAPI 实例用于 auto-summary 测试。"""
    from memento.api import MementoAPI
    db_path = tmp_path / "test_auto_summary.db"
    with patch("memento.core.get_embedding") as m1, \
         patch("memento.observation.get_embedding") as m2, \
         patch("memento.awake.get_embedding") as m3:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        m1.return_value = (fake_blob, 4, False)
        m2.return_value = (fake_blob, 4, False)
        m3.return_value = (fake_blob, 4, False)
        api = MementoAPI(db_path=db_path)
        yield api
        api.close()


# ── auto-summary fallback 测试 ────────────────────────────


def test_session_end_auto_summary_when_no_captures(api_fixture):
    """session_end should auto-capture summary when no explicit captures exist."""
    api = api_fixture
    r = api.session_start(project="/test", task="fix bug")
    sid = r.session_id

    result = api.session_end(sid, summary="Fixed the auth bug by updating JWT validation")
    assert result is not None
    assert result.auto_captures_count >= 1

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


def test_session_summary_not_in_engrams(db_conn):
    """session summary 应存在 sessions 表，不落 engrams。"""
    conn, core = db_conn
    svc = SessionService(conn)

    sid = svc.start(project="/test")
    svc.end(sid, summary="这是会话摘要")

    # summary 在 sessions 表中
    info = svc.get(sid)
    assert info.summary == "这是会话摘要"

    # 确认 engrams 表没有这个摘要
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM engrams WHERE content = ?",
        ("这是会话摘要",),
    ).fetchone()
    assert row["cnt"] == 0
