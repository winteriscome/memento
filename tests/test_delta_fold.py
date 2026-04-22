"""Tests for Delta Fold Engine (Layer 2, Task 5).

测试 Delta 折叠引擎的常量、数据类和折叠/规划函数。
"""

import pytest

from memento.delta_fold import (
    ARCHIVE_THRESHOLD,
    AGENT_STRENGTH_CAP,
    StrengthDelta,
    StrengthUpdatePlan,
    fold_deltas,
    plan_strength_updates,
)


# ═══════════════════════════════════════════════════════════════════════════
# Constants Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_archive_threshold():
    """测试归档阈值为 0.05。"""
    assert ARCHIVE_THRESHOLD == 0.05


def test_agent_strength_cap():
    """测试 Agent 未验证记忆强度上限为 0.5。"""
    assert AGENT_STRENGTH_CAP == 0.5


# ═══════════════════════════════════════════════════════════════════════════
# StrengthDelta Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_strength_delta_dataclass():
    """测试 StrengthDelta 数据类结构。"""
    delta = StrengthDelta(
        engram_id="eng-123",
        net_delta=0.15,
        reinforce_count=2,
        decay_count=1,
        source_ledger_ids=[1, 2, 3],
    )
    assert delta.engram_id == "eng-123"
    assert delta.net_delta == 0.15
    assert delta.reinforce_count == 2
    assert delta.decay_count == 1
    assert delta.source_ledger_ids == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════
# StrengthUpdatePlan Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_strength_update_plan_dataclass():
    """测试 StrengthUpdatePlan 数据类结构。"""
    plan = StrengthUpdatePlan(
        engram_id="eng-456",
        old_strength=0.7,
        new_strength=0.8,
        access_count_delta=3,
        update_last_accessed=True,
        source_ledger_ids=[4, 5],
    )
    assert plan.engram_id == "eng-456"
    assert plan.old_strength == 0.7
    assert plan.new_strength == 0.8
    assert plan.access_count_delta == 3
    assert plan.update_last_accessed is True
    assert plan.source_ledger_ids == [4, 5]


# ═══════════════════════════════════════════════════════════════════════════
# fold_deltas Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_fold_deltas_single_engram_multiple_deltas():
    """单个 engram 有多个 delta（2 reinforce + 1 decay）。"""
    deltas = [
        {"id": 1, "engram_id": "eng-1", "delta_type": "reinforce", "delta_value": 0.05},
        {"id": 2, "engram_id": "eng-1", "delta_type": "reinforce", "delta_value": 0.08},
        {"id": 3, "engram_id": "eng-1", "delta_type": "decay", "delta_value": -0.03},
    ]

    result = fold_deltas(deltas)

    assert len(result) == 1
    fold = result[0]
    assert fold.engram_id == "eng-1"
    assert fold.reinforce_count == 2
    assert fold.decay_count == 1
    assert fold.net_delta == pytest.approx(0.10)  # 0.05 + 0.08 - 0.03
    assert fold.source_ledger_ids == [1, 2, 3]


def test_fold_deltas_multiple_engrams():
    """多个 engram 各有自己的 delta。"""
    deltas = [
        {"id": 1, "engram_id": "eng-1", "delta_type": "reinforce", "delta_value": 0.05},
        {"id": 2, "engram_id": "eng-2", "delta_type": "decay", "delta_value": -0.02},
        {"id": 3, "engram_id": "eng-1", "delta_type": "decay", "delta_value": -0.01},
        {"id": 4, "engram_id": "eng-3", "delta_type": "reinforce", "delta_value": 0.10},
    ]

    result = fold_deltas(deltas)

    assert len(result) == 3

    # 按 engram_id 排序以便验证
    result_dict = {fold.engram_id: fold for fold in result}

    fold1 = result_dict["eng-1"]
    assert fold1.reinforce_count == 1
    assert fold1.decay_count == 1
    assert fold1.net_delta == pytest.approx(0.04)  # 0.05 - 0.01
    assert fold1.source_ledger_ids == [1, 3]

    fold2 = result_dict["eng-2"]
    assert fold2.reinforce_count == 0
    assert fold2.decay_count == 1
    assert fold2.net_delta == pytest.approx(-0.02)
    assert fold2.source_ledger_ids == [2]

    fold3 = result_dict["eng-3"]
    assert fold3.reinforce_count == 1
    assert fold3.decay_count == 0
    assert fold3.net_delta == pytest.approx(0.10)
    assert fold3.source_ledger_ids == [4]


def test_fold_deltas_empty_list():
    """空输入返回空列表。"""
    result = fold_deltas([])
    assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# plan_strength_updates Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_plan_strength_updates_clamp_to_upper_bound():
    """strength 超过 1.0 时钳位到 1.0（已验证记忆）。"""
    folds = [
        StrengthDelta(
            engram_id="eng-1",
            net_delta=0.5,
            reinforce_count=1,
            decay_count=0,
            source_ledger_ids=[1],
        ),
    ]
    engrams_lookup = {
        "eng-1": {
            "strength": 0.9,
            "access_count": 5,
            "origin": "human",
            "verified": True,
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-1"
    assert plan.old_strength == 0.9
    assert plan.new_strength == 1.0  # 0.9 + 0.5 → 钳位到 1.0
    assert plan.access_count_delta == 1
    assert plan.update_last_accessed is True
    assert plan.source_ledger_ids == [1]


def test_plan_strength_updates_agent_cap():
    """Agent 未验证记忆强度上限为 0.5。"""
    folds = [
        StrengthDelta(
            engram_id="eng-2",
            net_delta=0.3,
            reinforce_count=2,
            decay_count=0,
            source_ledger_ids=[2, 3],
        ),
    ]
    engrams_lookup = {
        "eng-2": {
            "strength": 0.4,
            "access_count": 2,
            "origin": "agent",
            "verified": False,
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-2"
    assert plan.old_strength == 0.4
    assert plan.new_strength == 0.5  # 0.4 + 0.3 → 钳位到 0.5（agent cap）
    assert plan.access_count_delta == 2
    assert plan.update_last_accessed is True
    assert plan.source_ledger_ids == [2, 3]


def test_plan_strength_updates_pure_decay():
    """纯衰减（无 reinforce）→ update_last_accessed=False, access_count_delta=0。"""
    folds = [
        StrengthDelta(
            engram_id="eng-3",
            net_delta=-0.1,
            reinforce_count=0,
            decay_count=2,
            source_ledger_ids=[4, 5],
        ),
    ]
    engrams_lookup = {
        "eng-3": {
            "strength": 0.6,
            "access_count": 10,
            "origin": "human",
            "verified": True,
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-3"
    assert plan.old_strength == 0.6
    assert plan.new_strength == 0.5  # 0.6 - 0.1
    assert plan.access_count_delta == 0  # 纯衰减不增加访问次数
    assert plan.update_last_accessed is False  # 纯衰减不更新 last_accessed
    assert plan.source_ledger_ids == [4, 5]


def test_plan_strength_updates_with_reinforce():
    """有 reinforce → update_last_accessed=True, access_count_delta=reinforce_count。"""
    folds = [
        StrengthDelta(
            engram_id="eng-4",
            net_delta=0.08,  # 0.12 - 0.04
            reinforce_count=3,
            decay_count=1,
            source_ledger_ids=[6, 7, 8, 9],
        ),
    ]
    engrams_lookup = {
        "eng-4": {
            "strength": 0.3,
            "access_count": 1,
            "origin": "human",
            "verified": False,
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-4"
    assert plan.old_strength == 0.3
    assert plan.new_strength == pytest.approx(0.38)
    assert plan.access_count_delta == 3  # 等于 reinforce_count
    assert plan.update_last_accessed is True
    assert plan.source_ledger_ids == [6, 7, 8, 9]


def test_plan_strength_updates_clamp_to_lower_bound():
    """strength 低于 0.0 时钳位到 0.0。"""
    folds = [
        StrengthDelta(
            engram_id="eng-5",
            net_delta=-0.3,
            reinforce_count=0,
            decay_count=3,
            source_ledger_ids=[10, 11, 12],
        ),
    ]
    engrams_lookup = {
        "eng-5": {
            "strength": 0.2,
            "access_count": 0,
            "origin": "human",
            "verified": True,
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-5"
    assert plan.old_strength == 0.2
    assert plan.new_strength == 0.0  # 0.2 - 0.3 → 钳位到 0.0
    assert plan.access_count_delta == 0
    assert plan.update_last_accessed is False
    assert plan.source_ledger_ids == [10, 11, 12]


def test_plan_strength_updates_verified_agent_origin():
    """Agent 记忆被 verify 后不受 0.5 cap 限制。"""
    folds = [
        StrengthDelta(
            engram_id="eng-6",
            net_delta=0.4,
            reinforce_count=1,
            decay_count=0,
            source_ledger_ids=[13],
        ),
    ]
    engrams_lookup = {
        "eng-6": {
            "strength": 0.5,
            "access_count": 3,
            "origin": "agent",
            "verified": True,  # 已验证
        },
    }

    result = plan_strength_updates(folds, engrams_lookup)

    assert len(result) == 1
    plan = result[0]
    assert plan.engram_id == "eng-6"
    assert plan.old_strength == 0.5
    assert plan.new_strength == 0.9  # 0.5 + 0.4，不受 0.5 cap 限制
    assert plan.access_count_delta == 1
    assert plan.update_last_accessed is True
    assert plan.source_ledger_ids == [13]
