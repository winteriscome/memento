"""v0.5.0 衰减引擎新增函数测试：compute_reinforce_delta 和 compute_decay_deltas。"""

from datetime import datetime, timedelta

from memento.decay import (
    compute_reinforce_delta,
    compute_decay_deltas,
    MIN_DECAY_DELTA,
)


def test_compute_reinforce_delta_produces_positive_delta():
    """compute_reinforce_delta 应产生正值增益。"""
    now = datetime.now()
    engram = {
        "id": "test-123",
        "last_accessed": (now - timedelta(hours=10)).isoformat(),
        "strength": 0.5,
        "access_count": 2,
        "importance": "normal",
    }

    result = compute_reinforce_delta(engram, now)

    assert result["engram_id"] == "test-123"
    assert result["delta_type"] == "reinforce"
    assert result["delta_value"] > 0
    assert result["delta_value"] <= 0.1  # boost 上限


def test_compute_decay_deltas_produces_negative_deltas():
    """compute_decay_deltas 应产生负值衰减。"""
    now = datetime.now()
    watermark = (now - timedelta(hours=100)).isoformat()

    engrams = [
        {
            "id": "eng-1",
            "strength": 0.8,
            "last_accessed": (now - timedelta(hours=200)).isoformat(),
            "access_count": 1,
            "importance": "normal",
        },
    ]

    deltas, new_watermark = compute_decay_deltas(engrams, watermark, now.isoformat())

    assert len(deltas) == 1
    assert deltas[0]["engram_id"] == "eng-1"
    assert deltas[0]["delta_type"] == "decay"
    assert deltas[0]["delta_value"] < 0  # 衰减应为负值
    assert new_watermark == now.isoformat()


def test_compute_decay_deltas_filters_tiny_deltas():
    """compute_decay_deltas 应过滤掉微小的 delta（< MIN_DECAY_DELTA）。"""
    now = datetime.now()
    # 设置一个非常接近 now 的 watermark，使得衰减极小
    watermark = (now - timedelta(seconds=1)).isoformat()

    engrams = [
        {
            "id": "eng-recent",
            "strength": 0.8,
            "last_accessed": (now - timedelta(hours=1)).isoformat(),
            "access_count": 5,
            "importance": "critical",  # 慢衰减
        },
    ]

    deltas, new_watermark = compute_decay_deltas(engrams, watermark, now.isoformat())

    # 因为时间间隔太短、importance 又是 critical，衰减应该极小被过滤掉
    assert len(deltas) == 0
    assert new_watermark == now.isoformat()


def test_compute_decay_deltas_advances_watermark():
    """compute_decay_deltas 应将 watermark 推进到 now。"""
    now = datetime.now()
    old_watermark = (now - timedelta(days=7)).isoformat()

    engrams = []  # 空列表也应推进 watermark

    deltas, new_watermark = compute_decay_deltas(engrams, old_watermark, now.isoformat())

    assert new_watermark == now.isoformat()
    assert len(deltas) == 0


def test_compute_decay_deltas_multiple_engrams():
    """compute_decay_deltas 应处理多个 engram，并只包含显著衰减的。"""
    now = datetime.now()
    watermark = (now - timedelta(hours=200)).isoformat()

    engrams = [
        {
            "id": "eng-old",
            "strength": 0.9,
            "last_accessed": (now - timedelta(hours=300)).isoformat(),
            "access_count": 0,
            "importance": "low",  # 快衰减
        },
        {
            "id": "eng-stable",
            "strength": 0.8,
            "last_accessed": (now - timedelta(hours=10)).isoformat(),
            "access_count": 20,
            "importance": "critical",  # 极慢衰减
        },
    ]

    deltas, new_watermark = compute_decay_deltas(engrams, watermark, now.isoformat())

    # eng-old 应该有显著衰减
    assert any(d["engram_id"] == "eng-old" for d in deltas)
    # eng-stable 可能没有显著衰减（取决于具体数值）

    # 所有 delta 都应为负
    for delta in deltas:
        assert delta["delta_value"] < 0
        assert delta["delta_type"] == "decay"


def test_compute_reinforce_delta_with_string_timestamp():
    """compute_reinforce_delta 应支持字符串 now 参数。"""
    now = datetime.now()
    engram = {
        "id": "test-456",
        "last_accessed": (now - timedelta(hours=5)).isoformat(),
        "strength": 0.6,
        "access_count": 1,
        "importance": "normal",
    }

    result = compute_reinforce_delta(engram, now.isoformat())

    assert result["engram_id"] == "test-456"
    assert result["delta_value"] > 0
