"""Observation ingestion pipeline 测试。"""

import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.core import MementoCore
from memento.observation import IngestResult, _fingerprint, ingest_observation
from memento.session import SessionService


@pytest.fixture
def db_setup(tmp_path):
    """创建临时数据库。"""
    db_path = tmp_path / "test_obs.db"
    with patch("memento.core.get_embedding") as mock_core, \
         patch("memento.observation.get_embedding") as mock_obs:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_core.return_value = (fake_blob, 4, False)
        mock_obs.return_value = (fake_blob, 4, False)

        core = MementoCore(db_path=db_path)
        yield core, core.conn, mock_obs
        core.close()


def test_fingerprint_consistency():
    """相同内容应生成相同 fingerprint。"""
    fp1 = _fingerprint("Hello World")
    fp2 = _fingerprint("  hello   world  ")
    assert fp1 == fp2


def test_fingerprint_difference():
    """不同内容应生成不同 fingerprint。"""
    fp1 = _fingerprint("Hello World")
    fp2 = _fingerprint("Goodbye World")
    assert fp1 != fp2


def test_observation_records_event(db_setup):
    """observation 应记录到 session_events。"""
    core, conn, _ = db_setup
    svc = SessionService(conn)
    sid = svc.start(project="/test")

    result = ingest_observation(
        conn, content="发现 db.py 使用 WAL 模式", session_id=sid
    )

    assert result.event_id != ""
    assert result.skipped is False

    # 验证事件已记录
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM session_events WHERE session_id = ? AND event_type = 'observation'",
        (sid,),
    ).fetchone()
    assert row["cnt"] == 1


def test_observation_fingerprint_dedup(db_setup):
    """同会话内相同内容应被去重。"""
    core, conn, _ = db_setup
    svc = SessionService(conn)
    sid = svc.start(project="/test")

    r1 = ingest_observation(conn, content="重复内容", session_id=sid)
    assert r1.skipped is False

    r2 = ingest_observation(conn, content="重复内容", session_id=sid)
    assert r2.skipped is True


def test_observation_high_importance_promotes(db_setup):
    """importance=high 的 observation 应直接晋升为 engram。"""
    _, conn, _ = db_setup
    svc = SessionService(conn)
    sid = svc.start(project="/test")

    result = ingest_observation(
        conn,
        content="关键发现：数据库连接池泄漏",
        importance="high",
        session_id=sid,
    )

    assert result.promoted is True
    assert result.engram_id is not None

    # 验证 engram 存在
    row = conn.execute(
        "SELECT * FROM engrams WHERE id = ?", (result.engram_id,)
    ).fetchone()
    assert row is not None
    assert row["origin"] == "agent"
    assert row["verified"] == 0
    assert row["strength"] == 0.5
    assert row["source_session_id"] == sid
    assert row["source_event_id"] == result.event_id


def test_observation_normal_no_promote(db_setup):
    """普通 observation 首次出现不应晋升。"""
    _, conn, _ = db_setup
    svc = SessionService(conn)
    sid = svc.start(project="/test")

    result = ingest_observation(
        conn,
        content="普通发现",
        importance="normal",
        session_id=sid,
    )

    assert result.promoted is False
    assert result.engram_id is None


def test_observation_cross_session_promotes(db_setup):
    """同一 observation 在 >=2 个不同 session 出现应晋升。"""
    _, conn, _ = db_setup
    svc = SessionService(conn)

    # 第一个 session
    sid1 = svc.start(project="/test")
    r1 = ingest_observation(conn, content="跨会话发现", session_id=sid1)
    assert r1.promoted is False
    svc.end(sid1)

    # 第二个 session
    sid2 = svc.start(project="/test")
    r2 = ingest_observation(conn, content="跨会话发现", session_id=sid2)
    assert r2.promoted is True
    assert r2.engram_id is not None


def test_observation_merge_does_not_update_access_count(db_setup):
    """合并 observation 不应修改 access_count/last_accessed（避免侧门强化）。"""
    core, conn, mock_obs = db_setup

    # 先 capture 一条记忆
    eid = core.capture("数据库连接池配置", type="fact", tags=["db"])
    engram_before = core.get_by_id(eid)
    access_count_before = engram_before["access_count"]
    last_accessed_before = engram_before["last_accessed"]

    # mock 让语义搜索能命中（相同 embedding → distance=0 → similarity=1.0）
    svc = SessionService(conn)
    sid = svc.start(project="/test")

    result = ingest_observation(
        conn,
        content="数据库连接池配置相关的新发现",
        tags=["db", "pool"],
        session_id=sid,
    )

    # 如果发生了合并（取决于 VEC_AVAILABLE），access_count 不应变
    if result.merged_with:
        engram_after = core.get_by_id(result.merged_with)
        assert engram_after["access_count"] == access_count_before


def test_observation_without_session_promotes(db_setup):
    """没有 session_id 但 importance=high 应晋升。"""
    _, conn, _ = db_setup

    result = ingest_observation(
        conn, content="无会话高重要性 observation", importance="high"
    )

    assert result.promoted is True
    assert result.engram_id is not None
    assert result.skipped is False


def test_observation_without_session_no_promote(db_setup):
    """没有 session_id 且普通 importance，什么都没持久化。"""
    _, conn, _ = db_setup

    result = ingest_observation(
        conn, content="无会话普通 observation", importance="normal"
    )

    assert result.promoted is False
    assert result.engram_id is None
    assert result.event_id == ""
    assert result.skipped is True
