"""Delta Fold Engine (Layer 2, Task 5).

折叠引擎：聚合 Delta Ledger 中的强度变化量，生成批量更新计划。

常量：
- ARCHIVE_THRESHOLD: 归档阈值（0.05）
- AGENT_STRENGTH_CAP: Agent 未验证记忆强度上限（0.5）

数据类：
- StrengthDelta: 折叠后的强度变化量
- StrengthUpdatePlan: 强度更新计划

函数：
- fold_deltas(): 折叠 Delta Ledger 记录
- plan_strength_updates(): 生成强度更新计划

纯函数模块，无 IO，无 DB 依赖。供 Epoch Phase 3 和 repository 使用。
"""

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

ARCHIVE_THRESHOLD = 0.05  # 强度低于此值的 engram 可归档
AGENT_STRENGTH_CAP = 0.5  # Agent 未验证记忆的强度上限


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class StrengthDelta:
    """折叠后的强度变化量。

    Attributes:
        engram_id: Engram ID
        net_delta: 净变化量（reinforce 之和 + decay 之和）
        reinforce_count: reinforce 类型 delta 的数量
        decay_count: decay 类型 delta 的数量
        source_ledger_ids: 源 delta_ledger 行 ID 列表
    """

    engram_id: str
    net_delta: float
    reinforce_count: int
    decay_count: int
    source_ledger_ids: list = field(default_factory=list)


@dataclass
class StrengthUpdatePlan:
    """强度更新计划。

    由 plan_strength_updates() 生成，交给 repository 执行。

    Attributes:
        engram_id: Engram ID
        old_strength: 旧强度值
        new_strength: 新强度值（已钳位）
        access_count_delta: 访问次数增量（仅来自 reinforce_count）
        update_last_accessed: 是否更新 last_accessed（仅 reinforce_count > 0 时为 True）
        source_ledger_ids: 源 delta_ledger 行 ID 列表
    """

    engram_id: str
    old_strength: float
    new_strength: float
    access_count_delta: int
    update_last_accessed: bool
    source_ledger_ids: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Core Functions
# ═══════════════════════════════════════════════════════════════════════════


def fold_deltas(deltas: list) -> list:
    """折叠 Delta Ledger 记录。

    按 engram_id 分组，分别计算 reinforce 和 decay 的总和。

    Args:
        deltas: Delta Ledger 记录列表，每条包含：
            - id: delta_ledger 行 ID
            - engram_id: Engram ID
            - delta_type: "reinforce" 或 "decay"
            - delta_value: 变化量（reinforce 为正，decay 为负）

    Returns:
        list[StrengthDelta]: 折叠后的强度变化量列表
    """
    if not deltas:
        return []

    # 按 engram_id 分组
    grouped = {}
    for delta in deltas:
        engram_id = delta["engram_id"]
        if engram_id not in grouped:
            grouped[engram_id] = {
                "reinforce_sum": 0.0,
                "decay_sum": 0.0,
                "reinforce_count": 0,
                "decay_count": 0,
                "source_ids": [],
            }

        group = grouped[engram_id]
        group["source_ids"].append(delta["id"])

        if delta["delta_type"] == "reinforce":
            group["reinforce_sum"] += delta["delta_value"]
            group["reinforce_count"] += 1
        elif delta["delta_type"] == "decay":
            group["decay_sum"] += delta["delta_value"]
            group["decay_count"] += 1

    # 生成 StrengthDelta 列表
    result = []
    for engram_id, group in grouped.items():
        net_delta = group["reinforce_sum"] + group["decay_sum"]
        result.append(
            StrengthDelta(
                engram_id=engram_id,
                net_delta=net_delta,
                reinforce_count=group["reinforce_count"],
                decay_count=group["decay_count"],
                source_ledger_ids=group["source_ids"],
            )
        )

    return result


def plan_strength_updates(folds: list, engrams_lookup: dict) -> list:
    """生成强度更新计划。

    Args:
        folds: list[StrengthDelta]，折叠后的强度变化量
        engrams_lookup: {engram_id: {strength, access_count, origin, verified}}

    Returns:
        list[StrengthUpdatePlan]: 强度更新计划列表
    """
    plans = []

    for fold in folds:
        engram = engrams_lookup.get(fold.engram_id)
        if not engram:
            continue

        old_strength = engram["strength"]
        new_strength = old_strength + fold.net_delta

        # 确定 cap（上限）
        if engram["origin"] == "agent" and not engram.get("verified", False):
            cap = AGENT_STRENGTH_CAP
        else:
            cap = 1.0

        # 钳位到 [0.0, cap]
        new_strength = max(0.0, min(new_strength, cap))

        # 访问次数增量和 last_accessed 更新逻辑
        access_count_delta = fold.reinforce_count
        update_last_accessed = fold.reinforce_count > 0

        plans.append(
            StrengthUpdatePlan(
                engram_id=fold.engram_id,
                old_strength=old_strength,
                new_strength=new_strength,
                access_count_delta=access_count_delta,
                update_last_accessed=update_last_accessed,
                source_ledger_ids=fold.source_ledger_ids,
            )
        )

    return plans
