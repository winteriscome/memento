"""State Machine Engine (Layer 2, Task 2).

定义 Engram 生命周期的状态机：
- STATES: 五种状态 {buffered, consolidated, abstracted, archived, forgotten}
- TRANSITIONS: 状态转换映射（T1, T5-T10）
- validate_transition(): 转换验证函数
- TransitionPlan: 转换计划数据类
- DropDecision: 丢弃决策数据类

纯数据+验证模块，无 IO，无 DB 依赖。
"""

from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════
# States
# ═══════════════════════════════════════════════════════════════════════════

STATES = {
    "buffered",      # 缓冲态：新捕获，待整合
    "consolidated",  # 整合态：已入库，活跃记忆
    "abstracted",    # 抽象态：模式提取，高阶知识
    "archived",      # 归档态：低频访问，冷存储
    "forgotten",     # 遗忘态：已删除，吸收态
}

# ═══════════════════════════════════════════════════════════════════════════
# Transitions
# ═══════════════════════════════════════════════════════════════════════════

TRANSITIONS = {
    "buffered": {
        "consolidated": "T1",  # 新记忆入库
    },
    "consolidated": {
        "abstracted": "T5",    # 模式提取
        "archived": "T6",      # 低频归档
        "forgotten": "T7",     # 主动遗忘
    },
    "abstracted": {
        "archived": "T8",      # 抽象知识归档
    },
    "archived": {
        "consolidated": "T9",  # 重新激活
        "forgotten": "T10",    # 归档后遗忘
    },
    "forgotten": {},           # 吸收态，无出边
}

# ═══════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════


def validate_transition(from_state: str, to_state: str) -> bool:
    """验证状态转换是否合法。

    Args:
        from_state: 起始状态
        to_state: 目标状态

    Returns:
        True 如果转换合法，False 否则
    """
    if from_state not in STATES or to_state not in STATES:
        return False

    if from_state not in TRANSITIONS:
        return False

    return to_state in TRANSITIONS[from_state]


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TransitionPlan:
    """状态转换计划。

    由 Epoch 决策层生成，交给 Repository apply 层执行。

    Attributes:
        engram_id: Engram ID（T1 时为 None，由 apply 层生成）
        capture_log_id: Capture Log ID（仅 T1 使用）
        from_state: 起始状态
        to_state: 目标状态
        transition: 转换标识符 (T1, T5-T10)
        reason: 转换原因（可读描述）
        epoch_id: 触发此转换的 Epoch ID
        metadata: 附加元数据（如 T5 的模式信息、T9 的访问统计等）
    """

    engram_id: Optional[str]
    capture_log_id: Optional[str]
    from_state: str
    to_state: str
    transition: str
    reason: str
    epoch_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class DropDecision:
    """丢弃决策。

    Epoch 决定不提升 buffered 记忆到 consolidated 的决策记录。

    Attributes:
        capture_log_id: 被丢弃的 Capture Log ID
        reason: 丢弃原因 ('noise'/'duplicate'/'below_threshold')
        epoch_id: 触发此决策的 Epoch ID
    """

    capture_log_id: str
    reason: str  # 'noise' | 'duplicate' | 'below_threshold'
    epoch_id: str
