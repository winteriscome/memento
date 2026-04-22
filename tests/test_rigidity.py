"""Tests for Rigidity Engine (Layer 2, Task 3).

测试刚性系统的常量、函数和再巩固计划生成。
"""

import pytest
from dataclasses import dataclass
from typing import Optional

from memento.rigidity import (
    RIGIDITY_DEFAULTS,
    CONTENT_LOCK_THRESHOLD,
    MAX_DRIFT_STEP,
    can_modify_content,
    max_drift_per_epoch,
    ReconsolidationPlan,
    plan_reconsolidation,
)


# ═══════════════════════════════════════════════════════════════════════════
# Constants Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_rigidity_defaults():
    """测试 RIGIDITY_DEFAULTS 常量值正确。"""
    assert RIGIDITY_DEFAULTS['preference'] == 0.7
    assert RIGIDITY_DEFAULTS['convention'] == 0.7
    assert RIGIDITY_DEFAULTS['fact'] == 0.5
    assert RIGIDITY_DEFAULTS['decision'] == 0.5
    assert RIGIDITY_DEFAULTS['debugging'] == 0.15
    assert RIGIDITY_DEFAULTS['insight'] == 0.15


def test_content_lock_threshold():
    """测试内容锁定阈值为 0.5。"""
    assert CONTENT_LOCK_THRESHOLD == 0.5


def test_max_drift_step():
    """测试最大漂移步长为 0.3。"""
    assert MAX_DRIFT_STEP == 0.3


# ═══════════════════════════════════════════════════════════════════════════
# can_modify_content Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_can_modify_content_below_threshold():
    """刚性 < 0.5 时允许修改内容。"""
    assert can_modify_content(0.49) is True
    assert can_modify_content(0.15) is True
    assert can_modify_content(0.0) is True


def test_can_modify_content_at_threshold():
    """刚性 = 0.5 时锁定内容。"""
    assert can_modify_content(0.5) is False


def test_can_modify_content_above_threshold():
    """刚性 > 0.5 时锁定内容。"""
    assert can_modify_content(0.7) is False
    assert can_modify_content(1.0) is False


# ═══════════════════════════════════════════════════════════════════════════
# max_drift_per_epoch Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_max_drift_at_threshold():
    """刚性 = 0.5 时漂移为 0。"""
    assert max_drift_per_epoch(0.5) == 0.0


def test_max_drift_above_threshold():
    """刚性 > 0.5 时漂移为 0。"""
    assert max_drift_per_epoch(0.7) == 0.0
    assert max_drift_per_epoch(1.0) == 0.0


def test_max_drift_episodic():
    """情景记忆（rigidity=0.15）最大漂移。"""
    # max_drift = (1.0 - 0.15) * 0.3 = 0.85 * 0.3 = 0.255
    assert max_drift_per_epoch(0.15) == pytest.approx(0.255)


def test_max_drift_fully_flexible():
    """完全柔性（rigidity=0.0）最大漂移。"""
    # max_drift = (1.0 - 0.0) * 0.3 = 0.3
    assert max_drift_per_epoch(0.0) == 0.3


# ═══════════════════════════════════════════════════════════════════════════
# ReconsolidationPlan Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_reconsolidation_plan_dataclass():
    """测试 ReconsolidationPlan 数据类结构。"""
    plan = ReconsolidationPlan(
        engram_id="test-123",
        allow_content_update=True,
        max_drift=0.255,
        llm_inputs={"current_content": "test"},
        nexus_candidates=["eng-456"],
    )
    assert plan.engram_id == "test-123"
    assert plan.allow_content_update is True
    assert plan.max_drift == 0.255
    assert plan.llm_inputs == {"current_content": "test"}
    assert plan.nexus_candidates == ["eng-456"]


def test_reconsolidation_plan_defaults():
    """测试 ReconsolidationPlan 默认值。"""
    plan = ReconsolidationPlan(
        engram_id="test-123",
        allow_content_update=False,
        max_drift=0.0,
    )
    assert plan.llm_inputs == {}
    assert plan.nexus_candidates == []


# ═══════════════════════════════════════════════════════════════════════════
# plan_reconsolidation Tests
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MockEngram:
    """用于测试的简化 Engram 模型。"""
    id: str
    content: str
    rigidity: float


@dataclass
class MockReconItem:
    """用于测试的简化再巩固条目。"""
    query_context: str
    coactivated_ids: list


def test_plan_reconsolidation_empty_items():
    """空再巩固条目返回 None。"""
    engram = MockEngram(id="eng-1", content="test", rigidity=0.15)
    plan = plan_reconsolidation(engram, [])
    assert plan is None


def test_plan_reconsolidation_locked_engram():
    """刚性 >= 0.5 的 engram 不允许内容更新，max_drift=0。"""
    engram = MockEngram(id="eng-2", content="preference", rigidity=0.7)
    items = [MockReconItem(query_context="q1", coactivated_ids=["eng-3"])]

    plan = plan_reconsolidation(engram, items)

    assert plan is not None
    assert plan.engram_id == "eng-2"
    assert plan.allow_content_update is False
    assert plan.max_drift == 0.0
    assert "current_content" in plan.llm_inputs
    assert plan.llm_inputs["current_content"] == "preference"


def test_plan_reconsolidation_unlocked_engram():
    """刚性 < 0.5 的 engram 允许内容更新，max_drift > 0。"""
    engram = MockEngram(id="eng-3", content="episodic memory", rigidity=0.15)
    items = [
        MockReconItem(query_context="q1", coactivated_ids=["eng-4"]),
        MockReconItem(query_context="q2", coactivated_ids=["eng-5"]),
    ]

    plan = plan_reconsolidation(engram, items)

    assert plan is not None
    assert plan.engram_id == "eng-3"
    assert plan.allow_content_update is True
    assert plan.max_drift == pytest.approx(0.255)  # (1.0 - 0.15) * 0.3
    assert plan.llm_inputs["current_content"] == "episodic memory"


def test_plan_reconsolidation_builds_llm_inputs():
    """验证 llm_inputs 包含必要字段。"""
    engram = MockEngram(id="eng-4", content="test content", rigidity=0.3)
    items = [
        MockReconItem(query_context="context A", coactivated_ids=["eng-5", "eng-6"]),
        MockReconItem(query_context="context B", coactivated_ids=["eng-7"]),
    ]

    plan = plan_reconsolidation(engram, items)

    assert plan is not None
    assert "current_content" in plan.llm_inputs
    assert "query_contexts" in plan.llm_inputs
    assert "coactivated_contents" in plan.llm_inputs

    assert plan.llm_inputs["current_content"] == "test content"
    assert plan.llm_inputs["query_contexts"] == ["context A", "context B"]
    # coactivated_contents 应该是去重后的 ID 列表（实际实现可能获取内容，这里先测 ID）
    assert isinstance(plan.llm_inputs["coactivated_contents"], list)


def test_plan_reconsolidation_at_threshold():
    """刚性正好为 0.5 时的边界测试。"""
    engram = MockEngram(id="eng-5", content="fact", rigidity=0.5)
    items = [MockReconItem(query_context="q1", coactivated_ids=[])]

    plan = plan_reconsolidation(engram, items)

    assert plan is not None
    assert plan.allow_content_update is False
    assert plan.max_drift == 0.0
