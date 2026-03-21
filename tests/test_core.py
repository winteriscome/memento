"""capture / recall 端到端测试（使用内存数据库，不依赖 Embedding API）。"""

import json
import sqlite3
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.core import MementoCore


@pytest.fixture
def core(tmp_path):
    """创建临时数据库的 MementoCore 实例。"""
    db_path = tmp_path / "test.db"
    with patch("memento.core.get_embedding") as mock_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embedding_embed:
        # 模拟 embedding：返回固定的 4 维向量，方便测试
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_embed.return_value = (fake_blob, 4, False)
        mock_embedding_embed.return_value = (fake_blob, 4, False)

        c = MementoCore(db_path=db_path)
        yield c, mock_embed
        c.close()


def test_capture_returns_id(core):
    """capture 应返回 UUID。"""
    c, _ = core
    eid = c.capture("测试记忆内容")
    assert eid is not None
    assert len(eid) == 36  # UUID 格式


def test_capture_stores_data(core):
    """capture 写入的数据应能通过 get_by_id 查回。"""
    c, _ = core
    eid = c.capture("JWT 用 RS256", type="fact", importance="high", tags=["auth"])
    row = c.get_by_id(eid)
    assert row is not None
    assert row["content"] == "JWT 用 RS256"
    assert row["type"] == "fact"
    assert row["importance"] == "high"
    assert json.loads(row["tags"]) == ["auth"]
    assert row["origin"] == "human"
    assert row["verified"] == 1


def test_agent_capture_unverified(core):
    """Agent 写入的记忆应标记为未验证。"""
    c, _ = core
    eid = c.capture("Agent 观察", origin="agent")
    row = c.get_by_id(eid)
    assert row["origin"] == "agent"
    assert row["verified"] == 0
    assert row["strength"] == 0.5


def test_forget(core):
    """forget 应将记忆标记为遗忘。"""
    c, _ = core
    eid = c.capture("将被遗忘")
    assert c.forget(eid) is True
    row = c.get_by_id(eid)
    assert row["forgotten"] == 1


def test_verify(core):
    """verify 应将 Agent 记忆标记为已验证。"""
    c, _ = core
    eid = c.capture("需要验证", origin="agent")
    assert c.verify(eid) is True
    row = c.get_by_id(eid)
    assert row["verified"] == 1


def test_status(core):
    """status 应返回正确的统计信息。"""
    c, _ = core
    c.capture("记忆 1")
    c.capture("记忆 2", origin="agent")
    c.capture("记忆 3")
    eid = c.capture("将遗忘")
    c.forget(eid)

    stats = c.status()
    assert stats["total"] == 4
    assert stats["active"] == 3
    assert stats["forgotten"] == 1
    assert stats["unverified_agent"] == 1


def test_recall_fts_fallback(core):
    """当 embedding 模拟为向量检索时，FTS5 可以作为回退。"""
    c, mock_embed = core

    # 先正常写入几条带 embedding 的记忆
    c.capture("React 项目使用 TypeScript 编写", tags=["react", "typescript"])
    c.capture("部署使用 Docker Compose", tags=["docker", "deploy"])
    c.capture("数据库选型为 PostgreSQL", tags=["database"])

    # recall 时模拟 embedding 失效 → 走 FTS5
    mock_embed.return_value = (None, 0, True)
    results = c.recall("React")

    # FTS5 应能找到包含 "React" 的记忆
    assert len(results) >= 1
    assert any("React" in r.content for r in results)


def test_recall_mode_b_is_read_only(core):
    """Mode B 应只做基线排序，不修改访问元数据。"""
    c, mock_embed = core
    recent_id = c.capture("auth recent baseline")
    old_id = c.capture("auth old baseline")

    c.conn.execute(
        "UPDATE engrams SET created_at = ?, last_accessed = ?, access_count = 0 WHERE id = ?",
        ("2026-03-20T12:00:00", "2026-03-20T12:00:00", recent_id),
    )
    c.conn.execute(
        "UPDATE engrams SET created_at = ?, last_accessed = ?, access_count = 7 WHERE id = ?",
        ("2025-03-20T12:00:00", "2025-03-20T12:00:00", old_id),
    )
    c.conn.commit()

    mock_embed.return_value = (None, 0, True)
    results = c.recall("auth", mode="B")

    assert results[0].id == recent_id
    old_row = c.get_by_id(old_id)
    recent_row = c.get_by_id(recent_id)
    assert old_row["access_count"] == 7
    assert recent_row["access_count"] == 0


def test_dimension_mismatch_falls_back_to_fts(core):
    """查询向量维度与存量 embedding 不匹配时，应回退到 FTS5。"""
    c, mock_embed = core
    c.capture("React memory with stored embedding")

    mismatch_blob = struct.pack("<3f", 0.1, 0.2, 0.3)
    mock_embed.return_value = (mismatch_blob, 3, False)
    results = c.recall("React")

    assert len(results) == 1
    assert results[0].content == "React memory with stored embedding"


def test_evaluate_returns_metrics(core):
    """evaluate 应返回基础排序指标。"""
    c, mock_embed = core
    expected_id = c.capture("token rotation guideline")
    stale_id = c.capture("old token rotation guideline")
    c.conn.execute(
        "UPDATE engrams SET created_at = ? WHERE id = ?",
        ("2024-01-01T00:00:00", stale_id),
    )
    c.conn.commit()

    mock_embed.return_value = (None, 0, True)
    report = c.evaluate(
        [
            {
                "query": "token",
                "expected_ids": [expected_id],
                "stale_ids": [stale_id],
            }
        ],
        mode="A",
    )

    assert report["mode"] == "A"
    assert report["query_count"] == 1
    assert report["labeled_count"] == 1
    assert report["precision_at_3"] is not None
    assert report["mrr"] is not None
    assert report["stale_hit_rate"] is not None
