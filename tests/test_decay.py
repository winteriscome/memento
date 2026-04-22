"""衰减公式的数值正确性测试。"""

from datetime import datetime, timedelta

from memento.decay import (
    BASE_HALF_LIFE,
    AGENT_STRENGTH_CAP,
    effective_strength,
    reinforcement_boost,
    needs_review,
)


def test_no_decay_at_zero_time():
    """刚刚访问过的记忆不应有衰减。"""
    now = datetime.now()
    eff = effective_strength(
        strength=0.7,
        last_accessed=now.isoformat(),
        access_count=0,
        importance="normal",
        now=now,
    )
    assert abs(eff - 0.7) < 1e-6


def test_decay_at_characteristic_time():
    """经过一个特征时间H（原半衰期）后，strength 应为 1/sqrt(2)。"""
    now = datetime.now()
    last = (now - timedelta(hours=BASE_HALF_LIFE)).isoformat()
    eff = effective_strength(
        strength=1.0,
        last_accessed=last,
        access_count=0,
        importance="normal",
        now=now,
    )
    assert abs(eff - 2**-0.5) < 1e-6


def test_access_count_slows_decay():
    """高访问次数应延长半衰期、减缓衰减。"""
    now = datetime.now()
    last = (now - timedelta(hours=BASE_HALF_LIFE)).isoformat()

    eff_low = effective_strength(
        strength=1.0, last_accessed=last, access_count=0, importance="normal", now=now
    )
    eff_high = effective_strength(
        strength=1.0, last_accessed=last, access_count=10, importance="normal", now=now
    )
    # 更高的 access_count → 更慢的衰减 → 更高的 effective_strength
    assert eff_high > eff_low


def test_importance_affects_decay():
    """critical 记忆衰减应远慢于 low。"""
    now = datetime.now()
    last = (now - timedelta(hours=BASE_HALF_LIFE * 2)).isoformat()

    eff_low = effective_strength(
        strength=1.0, last_accessed=last, access_count=0, importance="low", now=now
    )
    eff_critical = effective_strength(
        strength=1.0, last_accessed=last, access_count=0, importance="critical", now=now
    )
    assert eff_critical > eff_low


def test_reinforcement_boost_range():
    """boost 应在 [0, 0.1] 区间内。"""
    now = datetime.now()
    # 刚刚访问
    b1 = reinforcement_boost(now.isoformat(), now)
    assert 0 < b1 <= 0.1

    # 很久以前访问
    old = (now - timedelta(hours=1000)).isoformat()
    b2 = reinforcement_boost(old, now)
    assert b2 == 0.1  # 应该已经触顶


def test_boost_increases_with_interval():
    """间隔越长，boost 越大。"""
    now = datetime.now()
    b_short = reinforcement_boost((now - timedelta(hours=1)).isoformat(), now)
    b_long = reinforcement_boost((now - timedelta(hours=100)).isoformat(), now)
    assert b_long > b_short


def test_needs_review_critical():
    """critical 记忆低于阈值应触发复验。"""
    assert needs_review("critical", 0.3) is True
    assert needs_review("critical", 0.8) is False
    assert needs_review("normal", 0.3) is False


def test_rigidity_slows_decay():
    """高 rigidity 记忆应比低 rigidity 衰减更慢。"""
    now = datetime.now()
    last = (now - timedelta(hours=BASE_HALF_LIFE)).isoformat()

    eff_no_rigidity = effective_strength(
        strength=1.0, last_accessed=last, access_count=0,
        importance="normal", now=now, rigidity=0.0,
    )
    eff_mid_rigidity = effective_strength(
        strength=1.0, last_accessed=last, access_count=0,
        importance="normal", now=now, rigidity=0.5,
    )
    eff_high_rigidity = effective_strength(
        strength=1.0, last_accessed=last, access_count=0,
        importance="normal", now=now, rigidity=0.7,
    )
    # 更高 rigidity → 更慢衰减 → 更高 effective_strength
    assert eff_high_rigidity > eff_mid_rigidity > eff_no_rigidity


def test_rigidity_zero_has_no_effect():
    """rigidity=0.0 应该和不传 rigidity 结果一致。"""
    now = datetime.now()
    last = (now - timedelta(hours=100)).isoformat()

    eff_default = effective_strength(
        strength=0.8, last_accessed=last, access_count=3,
        importance="high", now=now,
    )
    eff_zero = effective_strength(
        strength=0.8, last_accessed=last, access_count=3,
        importance="high", now=now, rigidity=0.0,
    )
    assert abs(eff_default - eff_zero) < 1e-10


def test_pinned_memory_barely_decays():
    """rigidity=1.0 的记忆即使过了两周也应保持大部分强度。"""
    now = datetime.now()
    last = (now - timedelta(hours=BASE_HALF_LIFE * 2)).isoformat()  # 两周

    eff = effective_strength(
        strength=1.0, last_accessed=last, access_count=0,
        importance="normal", now=now, rigidity=1.0,
    )
    # rigidity=1.0 → half_life ×5 → 两周后仍应 > 0.8
    assert eff > 0.8
