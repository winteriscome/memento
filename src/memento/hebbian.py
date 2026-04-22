"""Hebbian Learning Engine (Layer 2, Task 6).

Hebbian 学习引擎：基于共激活的关联强化（"同时激活的神经元连接在一起"）。

常量：
- COACTIVATION_BOOST: 每次共激活的强度增益（0.05）
- MAX_ASSOCIATION: 最大关联强度（1.0）

数据类：
- NexusUpdatePlan: Nexus 关联更新计划

函数：
- plan_nexus_updates(): 从 recon_buffer 生成 Nexus 更新计划

纯函数模块，无 IO，无 DB 依赖。供 Epoch Phase 4 和 repository 使用。
"""

import json
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

COACTIVATION_BOOST = 0.05  # 每次共激活增益
MAX_ASSOCIATION = 1.0  # 最大关联强度


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class NexusUpdatePlan:
    """Nexus 关联更新计划。

    由 plan_nexus_updates() 生成，交给 repository 执行。

    Attributes:
        source_id: 源 engram ID（规范化：source_id < target_id）
        target_id: 目标 engram ID（规范化：source_id < target_id）
        type: 关联类型（始终为 'semantic'，用于共激活）
        strength_delta: 强度增量（COACTIVATION_BOOST × 出现次数）
        last_coactivated_at: 最后共激活时间（ISO 字符串）
        is_new: 是否为新建 nexus（不存在于 existing_nexus 中）
        source_recon_ids: 源 recon_buffer 行 ID 列表（哪些记录被消费）
    """

    source_id: str
    target_id: str
    type: str
    strength_delta: float
    last_coactivated_at: str
    is_new: bool
    source_recon_ids: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Core Functions
# ═══════════════════════════════════════════════════════════════════════════


def plan_nexus_updates(recon_items: list, existing_nexus: dict) -> list:
    """从 recon_buffer 生成 Nexus 更新计划。

    对每个 recon_item，提取 (engram_id, coactivated_id) 对：
    - 规范化：source_id = min(a, b), target_id = max(a, b)
    - 聚合：相同 pair → strength_delta 累加（每次 +COACTIVATION_BOOST）
    - 去重 source_recon_ids
    - 检查 existing_nexus 以设置 is_new

    Args:
        recon_items: recon_buffer 记录列表，每条包含：
            - id: recon_buffer 行 ID
            - engram_id: 主 engram ID
            - coactivated_ids: JSON 字符串数组，如 '["eng-1", "eng-2"]'
            - query_context: 查询上下文
            - occurred_at: 发生时间（ISO 字符串）
        existing_nexus: {(source_id, target_id, type): current_strength}

    Returns:
        list[NexusUpdatePlan]: Nexus 更新计划列表
    """
    if not recon_items:
        return []

    # 聚合字典：{(source_id, target_id): {count, last_occurred_at, recon_ids}}
    aggregated = {}

    for item in recon_items:
        engram_id = item["engram_id"]
        coactivated_ids_str = item["coactivated_ids"]
        occurred_at = item["occurred_at"]
        recon_id = item["id"]

        # 解析 JSON 数组
        try:
            coactivated_ids = json.loads(coactivated_ids_str)
        except (json.JSONDecodeError, TypeError):
            coactivated_ids = []

        # 提取每个 pair
        for coactivated_id in coactivated_ids:
            # 规范化：source_id < target_id
            source_id = min(engram_id, coactivated_id)
            target_id = max(engram_id, coactivated_id)
            pair_key = (source_id, target_id)

            if pair_key not in aggregated:
                aggregated[pair_key] = {
                    "count": 0,
                    "last_occurred_at": occurred_at,
                    "recon_ids": [],
                }

            agg = aggregated[pair_key]
            agg["count"] += 1
            # 更新到最新时间（假设 recon_items 是时间递增的，或者我们取 max）
            if occurred_at > agg["last_occurred_at"]:
                agg["last_occurred_at"] = occurred_at
            agg["recon_ids"].append(recon_id)

    # 生成 NexusUpdatePlan 列表
    plans = []
    for (source_id, target_id), agg in aggregated.items():
        strength_delta = agg["count"] * COACTIVATION_BOOST

        # 检查是否为新 nexus
        nexus_key = (source_id, target_id, "semantic")
        is_new = nexus_key not in existing_nexus

        plans.append(
            NexusUpdatePlan(
                source_id=source_id,
                target_id=target_id,
                type="semantic",
                strength_delta=strength_delta,
                last_coactivated_at=agg["last_occurred_at"],
                is_new=is_new,
                source_recon_ids=agg["recon_ids"],
            )
        )

    return plans
