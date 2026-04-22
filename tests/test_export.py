"""导入导出测试。"""

import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from memento.core import MementoCore
from memento.export import export_memories, export_nexus, export_full, import_memories


@pytest.fixture
def core(tmp_path):
    """创建临时数据库的 MementoCore 实例。"""
    db_path = tmp_path / "test.db"
    with patch("memento.core.get_embedding") as mock_core_embed, patch(
        "memento.embedding.get_embedding"
    ) as mock_embed:
        fake_blob = struct.pack("<4f", 0.1, 0.2, 0.3, 0.4)
        mock_core_embed.return_value = (fake_blob, 4, False)
        mock_embed.return_value = (fake_blob, 4, False)
        c = MementoCore(db_path=db_path)
        yield c, mock_embed
        c.close()


def test_export_basic(core):
    """导出应包含所有活跃记忆。"""
    c, _ = core
    c.capture("记忆 A", type="fact", tags=["a"])
    c.capture("记忆 B", type="decision", tags=["b"])
    eid = c.capture("将遗忘")
    c.forget(eid)

    memories = export_memories(c)
    assert len(memories) == 2
    contents = {m["content"] for m in memories}
    assert "记忆 A" in contents
    assert "记忆 B" in contents
    assert "将遗忘" not in contents


def test_export_filter_type(core):
    """按类型过滤导出。"""
    c, _ = core
    c.capture("事实", type="fact")
    c.capture("决策", type="decision")

    memories = export_memories(c, filter_type="decision")
    assert len(memories) == 1
    assert memories[0]["content"] == "决策"


def test_export_filter_tags(core):
    """按标签过滤导出。"""
    c, _ = core
    c.capture("React 相关", tags=["react"])
    c.capture("Python 相关", tags=["python"])

    memories = export_memories(c, filter_tags=["react"])
    assert len(memories) == 1
    assert memories[0]["content"] == "React 相关"


def test_import_basic(core):
    """基本导入应成功。"""
    c, _ = core
    memories = [
        {"id": "test-001", "content": "导入的记忆", "type": "fact", "tags": ["test"], "strength": 0.9},
    ]
    result = import_memories(c, memories, source="alice")
    assert result["imported"] == 1
    assert result["skipped"] == 0

    row = c.get_by_id("test-001")
    assert row is not None
    assert row["content"] == "导入的记忆"
    assert row["strength"] <= 0.5  # strength 上限


def test_import_strength_capped(core):
    """导入的记忆 strength 应被限制在 0.5。"""
    c, _ = core
    memories = [
        {"id": "test-002", "content": "高强度记忆", "strength": 1.0},
    ]
    import_memories(c, memories)
    row = c.get_by_id("test-002")
    assert row["strength"] == 0.5


def test_import_idempotent(core):
    """重复导入同一 ID 应跳过。"""
    c, _ = core
    memories = [{"id": "test-003", "content": "唯一记忆"}]
    r1 = import_memories(c, memories)
    r2 = import_memories(c, memories)
    assert r1["imported"] == 1
    assert r2["imported"] == 0
    assert r2["skipped"] == 1


def test_export_no_embedding(core):
    """导出数据不包含 embedding 字段。"""
    c, _ = core
    c.capture("测试")
    memories = export_memories(c)
    for m in memories:
        assert "embedding" not in m


def test_export_preserves_last_accessed_and_source(core):
    """导出应保留时间元数据和来源。"""
    c, _ = core
    eid = c.capture("需要导出的元数据")
    c.conn.execute(
        "UPDATE engrams SET source = ?, last_accessed = ? WHERE id = ?",
        ("alice", "2026-03-01T10:00:00", eid),
    )
    c.conn.commit()

    memories = export_memories(c)
    exported = next(m for m in memories if m["id"] == eid)
    assert exported["source"] == "alice"
    assert exported["last_accessed"] == "2026-03-01T10:00:00"


def test_import_preserves_verified_and_last_accessed(core):
    """导入应保留可信度与衰减相关时间元数据。"""
    c, _ = core
    memories = [
        {
            "id": "test-004",
            "content": "导入元数据",
            "origin": "human",
            "verified": True,
            "source": "alice",
            "created_at": "2026-02-01T09:00:00",
            "last_accessed": "2026-02-10T09:00:00",
            "access_count": 7,
        }
    ]

    import_memories(c, memories)
    row = c.get_by_id("test-004")
    assert row["verified"] == 1
    assert row["source"] == "alice"
    assert row["last_accessed"] == "2026-02-10T09:00:00"
    assert row["access_count"] == 7


# ── v0.5 新增测试 ──


def test_export_nexus_empty(core):
    """无 nexus 数据时导出为空列表。"""
    c, _ = core
    nexus = export_nexus(c)
    assert nexus == []


def test_export_full_format(core):
    """export_full 返回 version 2 格式。"""
    c, _ = core
    c.capture("测试", type="fact")
    result = export_full(c)
    assert result["version"] == 2
    assert "memories" in result
    assert "nexus" in result
    assert len(result["memories"]) == 1


def test_import_with_nexus(core):
    """导入 engrams + nexus 数据。"""
    c, _ = core
    memories = [
        {"id": "nx-001", "content": "记忆A", "type": "fact"},
        {"id": "nx-002", "content": "记忆B", "type": "fact"},
    ]
    nexus = [
        {
            "id": "link-001",
            "source_id": "nx-001",
            "target_id": "nx-002",
            "type": "related",
            "association_strength": 0.8,
        }
    ]
    result = import_memories(c, memories, nexus=nexus)
    assert result["imported"] == 2
    assert result["nexus_imported"] == 1

    # 验证 nexus 数据存在
    row = c.conn.execute("SELECT * FROM nexus WHERE id='link-001'").fetchone()
    assert row is not None
    assert row["source_id"] == "nx-001"


def test_import_nexus_idempotent(core):
    """重复导入 nexus 应跳过。"""
    c, _ = core
    memories = [
        {"id": "nx-003", "content": "记忆C"},
        {"id": "nx-004", "content": "记忆D"},
    ]
    nexus = [
        {
            "id": "link-002",
            "source_id": "nx-003",
            "target_id": "nx-004",
            "type": "causal",
        }
    ]
    r1 = import_memories(c, memories, nexus=nexus)
    r2 = import_memories(c, memories, nexus=nexus)
    assert r1["nexus_imported"] == 1
    assert r2["nexus_skipped"] == 1
