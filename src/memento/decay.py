"""衰减引擎：基于间隔重复原理的 effective_strength 计算。"""

from datetime import datetime
from math import log

# 基础半衰期：168 小时（一周）
BASE_HALF_LIFE = 168.0

# 最小衰减变化阈值
MIN_DECAY_DELTA = 0.001

# importance 对半衰期的倍率
IMPORTANCE_FACTOR = {
    "low": 0.5,
    "normal": 1.0,
    "high": 2.0,
    "critical": 10.0,
}

# critical 记忆复验提醒阈值
REVIEW_THRESHOLD = 0.5

# Agent 未验证记忆的 strength 上限
AGENT_STRENGTH_CAP = 0.5


def _hours_since(last_accessed: str, now: datetime | None = None) -> float:
    """Calculate hours elapsed, handling aware/naive datetime mismatch."""
    if now is None:
        now = datetime.now()
    last = datetime.fromisoformat(last_accessed)
    # Strip tzinfo from both to avoid aware/naive TypeError
    if last.tzinfo is not None:
        last = last.replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return (now - last).total_seconds() / 3600.0


def effective_strength(
    strength: float,
    last_accessed: str,
    access_count: int,
    importance: str,
    now: datetime | None = None,
    rigidity: float = 0.0,
) -> float:
    """
    每次 recall 时实时计算，不存中间态。

    设计文档 22.2 节公式 (已更新为 FSRS v6 幂律模型):
      half_life = BASE_HALF_LIFE × (1 + access_count × 0.5) × importance_factor × rigidity_factor
      decay = (1 + hours_since / half_life) ^ -0.5
      effective = strength × decay

    rigidity_factor: 1.0 + rigidity × 4.0
      rigidity=0.0 → ×1.0（无影响）
      rigidity=0.5 → ×3.0（半衰期延长3倍）
      rigidity=0.7 → ×3.8（偏好/约定几乎不衰减）
      rigidity=1.0 → ×5.0（钉住的记忆极难衰减）
    """
    hours = _hours_since(last_accessed, now)

    half_life = BASE_HALF_LIFE * (1 + access_count * 0.5)
    half_life *= IMPORTANCE_FACTOR.get(importance, 1.0)
    half_life *= 1.0 + rigidity * 4.0

    decay = (1 + hours / half_life) ** -0.5 if half_life > 0 else 0.0
    return strength * decay


def reinforcement_boost(last_accessed: str, now: datetime | None = None) -> float:
    """
    再巩固增益：间隔越长，增益越大。

    boost = min(0.1, 0.05 × (1 + log(1 + hours_since)))
    """
    hours = _hours_since(last_accessed, now)
    return min(0.1, 0.05 * (1 + log(1 + hours)))


def needs_review(importance: str, eff_strength: float) -> bool:
    """判断 critical 记忆是否需要复验提醒。"""
    return importance == "critical" and eff_strength < REVIEW_THRESHOLD


def compute_reinforce_delta(engram: dict, now: datetime | str | None = None) -> dict:
    """
    计算单次 recall 命中的再巩固增益。

    Args:
        engram: 包含 id, last_accessed, strength (至少) 的字典
        now: 当前时间，可为 datetime 或 ISO 字符串，默认为当前时间

    Returns:
        {"engram_id": str, "delta_type": "reinforce", "delta_value": float}
    """
    if now is None:
        now = datetime.now()
    elif isinstance(now, str):
        now = datetime.fromisoformat(now)

    boost = reinforcement_boost(engram["last_accessed"], now)
    return {
        "engram_id": engram["id"],
        "delta_type": "reinforce",
        "delta_value": boost,
    }


def compute_decay_deltas(
    engrams: list, watermark: str, now: str | None = None
) -> tuple:
    """
    计算从 watermark 到 now 的衰减变化量。

    对每个 engram:
    - s_at_wm = effective_strength(..., now=watermark)
    - s_at_now = effective_strength(..., now=now)
    - delta = s_at_now - s_at_wm  (负值)
    - 仅包含 abs(delta) > MIN_DECAY_DELTA 的记录

    Args:
        engrams: engram 字典列表，需包含 strength, last_accessed, access_count, importance
        watermark: 上次计算的时间戳（ISO 字符串）
        now: 当前时间戳（ISO 字符串），默认为当前时间

    Returns:
        (deltas_list, new_watermark)
        deltas_list: [{"engram_id": str, "delta_type": "decay", "delta_value": float}, ...]
        new_watermark: str (即 now)
    """
    if now is None:
        now = datetime.now().isoformat()

    # 转换为 datetime 对象用于计算
    wm_dt = datetime.fromisoformat(watermark)
    now_dt = datetime.fromisoformat(now)

    deltas = []
    for engram in engrams:
        rigidity = engram.get("rigidity", 0.0)
        s_at_wm = effective_strength(
            strength=engram["strength"],
            last_accessed=engram["last_accessed"],
            access_count=engram["access_count"],
            importance=engram["importance"],
            now=wm_dt,
            rigidity=rigidity,
        )
        s_at_now = effective_strength(
            strength=engram["strength"],
            last_accessed=engram["last_accessed"],
            access_count=engram["access_count"],
            importance=engram["importance"],
            now=now_dt,
            rigidity=rigidity,
        )

        delta_value = s_at_now - s_at_wm  # 应为负值（衰减）

        if abs(delta_value) > MIN_DECAY_DELTA:
            deltas.append(
                {
                    "engram_id": engram["id"],
                    "delta_type": "decay",
                    "delta_value": delta_value,
                }
            )

    return (deltas, now)
