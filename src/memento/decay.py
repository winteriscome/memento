"""衰减引擎：基于间隔重复原理的 effective_strength 计算。"""

from datetime import datetime
from math import log

# 基础半衰期：168 小时（一周）
BASE_HALF_LIFE = 168.0

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


def effective_strength(
    strength: float,
    last_accessed: str,
    access_count: int,
    importance: str,
    now: datetime | None = None,
) -> float:
    """
    每次 recall 时实时计算，不存中间态。

    设计文档 22.2 节公式：
      half_life = BASE_HALF_LIFE × (1 + access_count × 0.5) × importance_factor
      decay = 0.5 ^ (hours_since_access / half_life)
      effective = strength × decay
    """
    if now is None:
        now = datetime.now()

    last = datetime.fromisoformat(last_accessed)
    hours_since = (now - last).total_seconds() / 3600.0

    half_life = BASE_HALF_LIFE * (1 + access_count * 0.5)
    half_life *= IMPORTANCE_FACTOR.get(importance, 1.0)

    decay = 0.5 ** (hours_since / half_life) if half_life > 0 else 0.0
    return strength * decay


def reinforcement_boost(last_accessed: str, now: datetime | None = None) -> float:
    """
    再巩固增益：间隔越长，增益越大。

    boost = min(0.1, 0.05 × (1 + log(1 + hours_since)))
    """
    if now is None:
        now = datetime.now()

    last = datetime.fromisoformat(last_accessed)
    hours_since = (now - last).total_seconds() / 3600.0
    return min(0.1, 0.05 * (1 + log(1 + hours_since)))


def needs_review(importance: str, eff_strength: float) -> bool:
    """判断 critical 记忆是否需要复验提醒。"""
    return importance == "critical" and eff_strength < REVIEW_THRESHOLD
