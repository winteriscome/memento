"""Rigidity Engine (Layer 2, Task 3).

刚性系统：控制 Engram 内容可变性与语义漂移速率。

常量：
- RIGIDITY_DEFAULTS: 按类型的默认刚性值
- CONTENT_LOCK_THRESHOLD: 内容锁定阈值（0.5）
- MAX_DRIFT_STEP: 最大漂移步长（0.3）

函数：
- can_modify_content(): 判断是否允许修改内容
- max_drift_per_epoch(): 计算单次 Epoch 最大语义漂移量
- plan_reconsolidation(): 生成再巩固计划

数据类：
- ReconsolidationPlan: 再巩固计划，供 Epoch 执行器使用

纯函数模块，无 IO，无 DB 依赖。
"""

from dataclasses import dataclass, field
from typing import Optional, Any


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

RIGIDITY_DEFAULTS = {
    'preference': 0.7,   # 程序性记忆：高刚性
    'convention': 0.7,   # 程序性记忆：高刚性
    'fact': 0.5,         # 语义记忆：中等刚性
    'decision': 0.5,     # 语义记忆：中等刚性
    'debugging': 0.15,   # 情景记忆：低刚性
    'insight': 0.15,     # 情景记忆：低刚性
}

CONTENT_LOCK_THRESHOLD = 0.5  # rigidity >= 0.5 时锁定内容
MAX_DRIFT_STEP = 0.3          # 单次 Epoch 最大漂移量系数


# ═══════════════════════════════════════════════════════════════════════════
# Core Functions
# ═══════════════════════════════════════════════════════════════════════════


def can_modify_content(rigidity: float) -> bool:
    """判断是否允许修改 Engram 内容。

    Args:
        rigidity: Engram 刚性值 [0.0, 1.0]

    Returns:
        True 如果刚性 < 0.5，允许修改内容
        False 如果刚性 >= 0.5，内容已锁定
    """
    return rigidity < CONTENT_LOCK_THRESHOLD


def max_drift_per_epoch(rigidity: float) -> float:
    """计算单次 Epoch 允许的最大语义漂移量。

    公式：
    - rigidity >= 0.5: max_drift = 0.0 (完全锁定)
    - rigidity < 0.5:  max_drift = (1.0 - rigidity) * MAX_DRIFT_STEP

    Args:
        rigidity: Engram 刚性值 [0.0, 1.0]

    Returns:
        最大语义漂移量 [0.0, 0.3]
    """
    if rigidity >= CONTENT_LOCK_THRESHOLD:
        return 0.0
    return (1.0 - rigidity) * MAX_DRIFT_STEP


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ReconsolidationPlan:
    """再巩固计划。

    由 plan_reconsolidation() 生成，交给 Epoch 执行器使用。

    Attributes:
        engram_id: Engram ID
        allow_content_update: 是否允许修改内容（基于刚性）
        max_drift: 本次 Epoch 允许的最大语义漂移量
        llm_inputs: 供 LLM 使用的输入数据（current_content、query_contexts、coactivated_contents）
        nexus_candidates: 候选的 Nexus 连接（coactivated engram IDs）
    """

    engram_id: str
    allow_content_update: bool
    max_drift: float
    llm_inputs: dict = field(default_factory=dict)
    nexus_candidates: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Planning Functions
# ═══════════════════════════════════════════════════════════════════════════


def plan_reconsolidation(engram: Any, recon_items: list) -> Optional[ReconsolidationPlan]:
    """为 Engram 生成再巩固计划。

    Args:
        engram: Engram 对象（需有 id, content, rigidity 属性）
        recon_items: 再巩固条目列表（每项需有 query_context, coactivated_ids）

    Returns:
        ReconsolidationPlan 如果有再巩固需求
        None 如果 recon_items 为空
    """
    if not recon_items:
        return None

    # 1. 基于刚性决定内容可变性
    allow_update = can_modify_content(engram.rigidity)
    max_drift = max_drift_per_epoch(engram.rigidity)

    # 2. 构建 LLM 输入数据
    query_contexts = [item.query_context for item in recon_items]

    # 收集所有共激活的 engram IDs（去重）
    coactivated_ids = []
    for item in recon_items:
        coactivated_ids.extend(item.coactivated_ids)
    unique_coactivated = list(dict.fromkeys(coactivated_ids))  # 保序去重

    llm_inputs = {
        "current_content": engram.content,
        "query_contexts": query_contexts,
        "coactivated_contents": unique_coactivated,  # 后续可扩展为实际内容
    }

    # 3. 生成计划
    return ReconsolidationPlan(
        engram_id=engram.id,
        allow_content_update=allow_update,
        max_drift=max_drift,
        llm_inputs=llm_inputs,
        nexus_candidates=unique_coactivated,
    )
