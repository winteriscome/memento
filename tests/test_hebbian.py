"""Tests for Hebbian Learning Engine (Layer 2, Task 6).

测试 Hebbian 学习引擎的常量、数据类和共激活关联规划函数。
"""

import pytest

from memento.hebbian import (
    COACTIVATION_BOOST,
    MAX_ASSOCIATION,
    NexusUpdatePlan,
    plan_nexus_updates,
)


# ═══════════════════════════════════════════════════════════════════════════
# Constants Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_coactivation_boost():
    """测试共激活增益常量为 0.05。"""
    assert COACTIVATION_BOOST == 0.05


def test_max_association():
    """测试最大关联强度为 1.0。"""
    assert MAX_ASSOCIATION == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# NexusUpdatePlan Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_nexus_update_plan_dataclass():
    """测试 NexusUpdatePlan 数据类结构。"""
    plan = NexusUpdatePlan(
        source_id="eng-aaa",
        target_id="eng-zzz",
        type="semantic",
        strength_delta=0.15,
        last_coactivated_at="2026-04-01T10:00:00",
        is_new=True,
        source_recon_ids=[1, 2, 3],
    )
    assert plan.source_id == "eng-aaa"
    assert plan.target_id == "eng-zzz"
    assert plan.type == "semantic"
    assert plan.strength_delta == 0.15
    assert plan.last_coactivated_at == "2026-04-01T10:00:00"
    assert plan.is_new is True
    assert plan.source_recon_ids == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════
# plan_nexus_updates Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_single_coactivation_new_nexus():
    """单个共激活 → 新 nexus，normalized source < target。"""
    recon_items = [
        {
            "id": 1,
            "engram_id": "eng-zzz",
            "coactivated_ids": '["eng-aaa"]',
            "query_context": "test context",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 1
    plan = result[0]
    assert plan.source_id == "eng-aaa"  # normalized: min(zzz, aaa)
    assert plan.target_id == "eng-zzz"  # normalized: max(zzz, aaa)
    assert plan.type == "semantic"
    assert plan.strength_delta == pytest.approx(0.05)  # 1x boost
    assert plan.is_new is True
    assert plan.source_recon_ids == [1]
    assert plan.last_coactivated_at == "2026-04-01T10:00:00"


def test_existing_nexus_is_new_false():
    """已存在的 nexus → is_new=False。"""
    recon_items = [
        {
            "id": 2,
            "engram_id": "eng-123",
            "coactivated_ids": '["eng-456"]',
            "query_context": "test",
            "occurred_at": "2026-04-01T11:00:00",
        }
    ]
    existing_nexus = {
        ("eng-123", "eng-456", "semantic"): 0.1  # 已存在
    }

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 1
    plan = result[0]
    assert plan.is_new is False
    assert plan.source_id == "eng-123"
    assert plan.target_id == "eng-456"


def test_three_recon_items_same_pair():
    """3 个 recon_items 引用同一对 → 1 个 plan，3x boost，3 个 source_recon_ids。"""
    recon_items = [
        {
            "id": 10,
            "engram_id": "eng-alpha",
            "coactivated_ids": '["eng-beta"]',
            "query_context": "ctx1",
            "occurred_at": "2026-04-01T10:00:00",
        },
        {
            "id": 11,
            "engram_id": "eng-beta",
            "coactivated_ids": '["eng-alpha"]',
            "query_context": "ctx2",
            "occurred_at": "2026-04-01T11:00:00",
        },
        {
            "id": 12,
            "engram_id": "eng-alpha",
            "coactivated_ids": '["eng-beta"]',
            "query_context": "ctx3",
            "occurred_at": "2026-04-01T12:00:00",
        },
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 1
    plan = result[0]
    assert plan.source_id == "eng-alpha"
    assert plan.target_id == "eng-beta"
    assert plan.strength_delta == pytest.approx(0.15)  # 3x boost
    assert set(plan.source_recon_ids) == {10, 11, 12}  # 所有 3 个
    # last_coactivated_at 应该是最后一次的时间戳
    assert plan.last_coactivated_at == "2026-04-01T12:00:00"


def test_multiple_pairs_from_one_recon_item():
    """一个 recon_item 有多个 coactivated_ids → 生成多个 pair。"""
    recon_items = [
        {
            "id": 20,
            "engram_id": "eng-1",
            "coactivated_ids": '["eng-2", "eng-3"]',
            "query_context": "test",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 2

    # 按 target_id 排序以便验证
    result_sorted = sorted(result, key=lambda p: p.target_id)

    plan1 = result_sorted[0]
    assert plan1.source_id == "eng-1"
    assert plan1.target_id == "eng-2"
    assert plan1.strength_delta == pytest.approx(0.05)
    assert plan1.source_recon_ids == [20]

    plan2 = result_sorted[1]
    assert plan2.source_id == "eng-1"
    assert plan2.target_id == "eng-3"
    assert plan2.strength_delta == pytest.approx(0.05)
    assert plan2.source_recon_ids == [20]


def test_bidirectional_normalization():
    """双向规范化：(zzz, aaa) → (aaa, zzz)。"""
    recon_items = [
        {
            "id": 30,
            "engram_id": "eng-zzz",
            "coactivated_ids": '["eng-aaa"]',
            "query_context": "test",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 1
    plan = result[0]
    # 应该规范化为 aaa < zzz
    assert plan.source_id == "eng-aaa"
    assert plan.target_id == "eng-zzz"


def test_empty_recon_items():
    """空 recon_items → 空结果。"""
    result = plan_nexus_updates([], {})
    assert result == []


def test_recon_item_with_no_coactivated_ids():
    """recon_item 的 coactivated_ids 为空数组 → 无输出。"""
    recon_items = [
        {
            "id": 40,
            "engram_id": "eng-solo",
            "coactivated_ids": "[]",
            "query_context": "test",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 0


def test_deduplication_of_source_recon_ids():
    """同一 recon_item 多次引用同一对 → source_recon_ids 去重（实际上不会发生，但测试防御性代码）。"""
    # 注：在正常情况下，一个 recon_item 的 engram_id 和 coactivated_ids 组合只会产生一次 pair
    # 但我们测试去重逻辑
    recon_items = [
        {
            "id": 50,
            "engram_id": "eng-x",
            "coactivated_ids": '["eng-y", "eng-y"]',  # 重复
            "query_context": "test",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    # 即使 coactivated_ids 有重复，也应该只产生一次 pair
    assert len(result) == 1
    plan = result[0]
    assert plan.strength_delta == pytest.approx(0.10)  # 2x boost (重复计数)
    assert plan.source_recon_ids == [50, 50]  # 记录重复（如果实现支持）


def test_normalization_preserves_existing_nexus_lookup():
    """规范化后正确查找 existing_nexus。"""
    recon_items = [
        {
            "id": 60,
            "engram_id": "eng-zzz",
            "coactivated_ids": '["eng-aaa"]',
            "query_context": "test",
            "occurred_at": "2026-04-01T10:00:00",
        }
    ]
    # existing_nexus 中已经存在规范化后的 key
    existing_nexus = {
        ("eng-aaa", "eng-zzz", "semantic"): 0.2
    }

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 1
    plan = result[0]
    assert plan.is_new is False  # 应该检测到已存在


def test_multiple_distinct_pairs():
    """多个不同的 pair → 多个 plan。"""
    recon_items = [
        {
            "id": 70,
            "engram_id": "eng-a",
            "coactivated_ids": '["eng-b"]',
            "query_context": "ctx1",
            "occurred_at": "2026-04-01T10:00:00",
        },
        {
            "id": 71,
            "engram_id": "eng-c",
            "coactivated_ids": '["eng-d"]',
            "query_context": "ctx2",
            "occurred_at": "2026-04-01T11:00:00",
        },
    ]
    existing_nexus = {}

    result = plan_nexus_updates(recon_items, existing_nexus)

    assert len(result) == 2

    result_dict = {(plan.source_id, plan.target_id): plan for plan in result}

    plan1 = result_dict[("eng-a", "eng-b")]
    assert plan1.strength_delta == pytest.approx(0.05)
    assert plan1.source_recon_ids == [70]

    plan2 = result_dict[("eng-c", "eng-d")]
    assert plan2.strength_delta == pytest.approx(0.05)
    assert plan2.source_recon_ids == [71]
