"""State Machine Engine 测试 (Layer 2, Task 2)。

测试覆盖:
- STATES 常量定义
- TRANSITIONS 映射规则
- validate_transition() 验证逻辑
- TransitionPlan 数据类
- DropDecision 数据类
"""

import pytest

from memento.state_machine import (
    STATES,
    TRANSITIONS,
    DropDecision,
    TransitionPlan,
    validate_transition,
)


class TestStatesDefinition:
    """测试状态常量定义。"""

    def test_states_has_five_elements(self):
        """STATES 应包含恰好 5 个状态。"""
        assert len(STATES) == 5

    def test_states_contains_all_expected_states(self):
        """STATES 应包含所有预期的状态。"""
        expected = {"buffered", "consolidated", "abstracted", "archived", "forgotten"}
        assert STATES == expected

    def test_forgotten_is_absorbing_state(self):
        """forgotten 应是吸收态（无出边）。"""
        assert "forgotten" in TRANSITIONS
        assert TRANSITIONS["forgotten"] == {}


class TestTransitionsMapping:
    """测试状态转换映射。"""

    def test_buffered_transitions(self):
        """buffered 应只能转换到 consolidated (T1)。"""
        assert TRANSITIONS["buffered"] == {"consolidated": "T1"}

    def test_consolidated_transitions(self):
        """consolidated 应能转换到 abstracted (T5)、archived (T6)、forgotten (T7)。"""
        assert TRANSITIONS["consolidated"] == {
            "abstracted": "T5",
            "archived": "T6",
            "forgotten": "T7",
        }

    def test_abstracted_transitions(self):
        """abstracted 应只能转换到 archived (T8)。"""
        assert TRANSITIONS["abstracted"] == {"archived": "T8"}

    def test_archived_transitions(self):
        """archived 应能转换到 consolidated (T9)、forgotten (T10)。"""
        assert TRANSITIONS["archived"] == {
            "consolidated": "T9",
            "forgotten": "T10",
        }

    def test_forgotten_has_no_outgoing_transitions(self):
        """forgotten 不应有任何出边。"""
        assert TRANSITIONS["forgotten"] == {}


class TestValidateTransition:
    """测试 validate_transition() 验证函数。"""

    def test_valid_transitions_pass(self):
        """有效的转换应通过验证。"""
        assert validate_transition("buffered", "consolidated") is True
        assert validate_transition("consolidated", "abstracted") is True
        assert validate_transition("consolidated", "archived") is True
        assert validate_transition("consolidated", "forgotten") is True
        assert validate_transition("abstracted", "archived") is True
        assert validate_transition("archived", "consolidated") is True
        assert validate_transition("archived", "forgotten") is True

    def test_invalid_transitions_fail(self):
        """无效的转换应验证失败。"""
        # buffered 不能直接到 forgotten
        assert validate_transition("buffered", "forgotten") is False
        # forgotten 不能转换到任何状态（吸收态）
        assert validate_transition("forgotten", "consolidated") is False
        assert validate_transition("forgotten", "buffered") is False
        # consolidated 不能回退到 buffered
        assert validate_transition("consolidated", "buffered") is False
        # 不支持的转换
        assert validate_transition("abstracted", "buffered") is False
        assert validate_transition("archived", "abstracted") is False

    def test_invalid_states_fail(self):
        """未知状态应验证失败。"""
        assert validate_transition("invalid_state", "consolidated") is False
        assert validate_transition("buffered", "invalid_state") is False


class TestTransitionPlan:
    """测试 TransitionPlan 数据类。"""

    def test_create_t1_transition_without_engram_id(self):
        """T1 转换（buffered→consolidated）不应有 engram_id（由 apply 层生成）。"""
        plan = TransitionPlan(
            engram_id=None,
            capture_log_id="log-123",
            from_state="buffered",
            to_state="consolidated",
            transition="T1",
            reason="Initial consolidation",
            epoch_id="epoch-001",
        )
        assert plan.engram_id is None
        assert plan.capture_log_id == "log-123"
        assert plan.from_state == "buffered"
        assert plan.to_state == "consolidated"
        assert plan.transition == "T1"
        assert plan.reason == "Initial consolidation"
        assert plan.epoch_id == "epoch-001"
        assert plan.metadata == {}

    def test_create_non_t1_transition_with_engram_id(self):
        """非 T1 转换应有 engram_id，但没有 capture_log_id。"""
        plan = TransitionPlan(
            engram_id="engram-456",
            capture_log_id=None,
            from_state="consolidated",
            to_state="abstracted",
            transition="T5",
            reason="Abstraction due to pattern detected",
            epoch_id="epoch-002",
            metadata={"pattern": "API retry logic"},
        )
        assert plan.engram_id == "engram-456"
        assert plan.capture_log_id is None
        assert plan.from_state == "consolidated"
        assert plan.to_state == "abstracted"
        assert plan.transition == "T5"
        assert plan.metadata == {"pattern": "API retry logic"}

    def test_archived_to_consolidated_t9(self):
        """T9 转换：archived→consolidated（重新激活）。"""
        plan = TransitionPlan(
            engram_id="engram-789",
            capture_log_id=None,
            from_state="archived",
            to_state="consolidated",
            transition="T9",
            reason="Reactivated due to recent access",
            epoch_id="epoch-003",
        )
        assert plan.from_state == "archived"
        assert plan.to_state == "consolidated"
        assert plan.transition == "T9"


class TestDropDecision:
    """测试 DropDecision 数据类。"""

    def test_create_drop_decision_noise(self):
        """创建噪音丢弃决策。"""
        decision = DropDecision(
            capture_log_id="log-999",
            reason="noise",
            epoch_id="epoch-004",
        )
        assert decision.capture_log_id == "log-999"
        assert decision.reason == "noise"
        assert decision.epoch_id == "epoch-004"

    def test_create_drop_decision_duplicate(self):
        """创建重复丢弃决策。"""
        decision = DropDecision(
            capture_log_id="log-888",
            reason="duplicate",
            epoch_id="epoch-005",
        )
        assert decision.reason == "duplicate"

    def test_create_drop_decision_below_threshold(self):
        """创建低于阈值丢弃决策。"""
        decision = DropDecision(
            capture_log_id="log-777",
            reason="below_threshold",
            epoch_id="epoch-006",
        )
        assert decision.reason == "below_threshold"
