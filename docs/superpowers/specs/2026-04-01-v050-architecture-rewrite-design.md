# v0.5.0 三轨架构重写 — 设计规格书

## Scope Lock

以下决策在 brainstorming 中已定死，实现期间不再争论。

| 决策 | 结论 | 理由 |
|------|------|------|
| 分批策略 | v0.5.0 仅交付核心架构；Fork/PR/Merge、隐私、Diplomat、冷启动、连接器、LongMemEval 后移 | 架构重写先打地基 |
| 数据迁移 | 原地迁移（ALTER TABLE），不新建库 | 简单直接，用户无需手动操作 |
| CLI/MCP | 增量升级，不全部推翻 | 减少迁移成本 |
| 进程模型 | 双进程：Worker（Awake + Subconscious）常驻 + Epoch 独立子进程 | 天然隔离 LLM 重度计算 |
| LLM 提供商 | 仅支持 OpenAI 兼容 API，单 Epoch 绑定单 model，失败→cognitive debt | 稳定性优先于可用性 |
| Nexus 存储 | 纯 SQLite 邻接表，不引入内存图索引 | 万条级别 + 2 跳限制，SQLite 足够 |
| 状态模型 | 五态（BUFFERED/CONSOLIDATED/ABSTRACTED/ARCHIVED/FORGOTTEN）+ 丢弃转移 | 文档正文校正 |
| 实施路径 | 自底向上分层构建（Layer 1→4），层内最小纵向冒烟 | 数据模型先定死，避免反复改表 |
| View Store | 事务内原地重建，view_pointer 仅做审计 | v0.5.0 不需要真正的版本切换 |
| forget | 不做 Awake 例外，走 pending_forget → Epoch T7 | 保持"仅 Epoch 做状态转换"不变量 |
| /observe vs /capture | capture → capture_log（L2），observe → session_events，observe 不参与 Epoch L2 整合 | 不混语义 |
| export/import | 仅处理 L3（engrams + nexus），不导出运行时表 | 避免导入半处理态 |
| ARCHIVED 唤醒 | v0.5.0 不支持 archived 唤醒（Archive Tombstone Index 推到 v0.5.1） | 显式降级，view_engrams 仅含 consolidated |
| ABSTRACTED 可见性 | v0.5.0 abstracted 不进入主 recall 结果 | 间接引用层，非主查询对象 |
| Embedding 同步 | awake_capture 同步调 get_embedding，已知可能拖慢写入 | v0.5.0 显式妥协，v0.5.1 考虑下放 Subconscious |

## 版本与范围

**版本**：v0.5.0（核心架构）

**交付物**：
1. 新数据模型 + 原地迁移脚本
2. 三轨节律（Awake / Subconscious / Sleep-Epoch）
3. Epoch lease + seal_timestamp + `memento epoch run`
4. CQRS（View Store 原地重建 + Truth Store）
5. 五态状态机 + 状态转换规则
6. Hot Buffer View（BUFFERED 弱查询，provisional 标记）
7. Delta Ledger（append-only，Epoch 折叠）
8. rigidity 系统
9. Nexus SQLite 邻接表 + 赫布学习
10. LLM 抽象层（OpenAI 兼容，单 Epoch 单 model）
11. 降级 Epoch（Light Sleep + cognitive debt 池）
12. CLI/MCP 增量升级 + hooks 适配

**不做**（v0.5.1+）：
- Fork / PR / Merge + OperationLog
- 隐私系统 + 加密粉碎
- Diplomat Agent
- Project Vault
- 冷启动管道
- 外部连接器 + Context Profile
- OpenAI Function Schema 适配
- LongMemEval 基准评测
- Revision Chain / 历史版本持久化

---

## Layer 1 — 数据层

### 1.1 engrams 表扩展

在现有表上 ALTER，`state` 成为唯一状态真相源，`forgotten` 列保留但不再参与业务逻辑。

```sql
ALTER TABLE engrams ADD COLUMN state TEXT DEFAULT 'consolidated';
  -- 五态: buffered / consolidated / abstracted / archived / forgotten
  -- 迁移时所有现存记忆 → consolidated

ALTER TABLE engrams ADD COLUMN rigidity REAL DEFAULT 0.5;
  -- 迁移时按 type 自动赋值:
  --   preference/convention → 0.7 (procedural 类)
  --   fact/decision         → 0.5 (semantic 类)
  --   debugging/insight     → 0.15 (episodic 类)

ALTER TABLE engrams ADD COLUMN content_hash TEXT;
  -- SHA256(content)，供再巩固 diff 和去重

ALTER TABLE engrams ADD COLUMN last_state_changed_epoch_id TEXT;
  -- 最近一次改变此 engram 状态的 Epoch ID

CREATE INDEX idx_engrams_state ON engrams(state);
CREATE INDEX idx_engrams_content_hash ON engrams(content_hash);
```

### 1.2 capture_log 表（L2 原始捕获日志）

BUFFERED 的物理落点。`capture()` 只写这张表，不直接写 engrams（L3）。

```sql
CREATE TABLE capture_log (
    id                TEXT PRIMARY KEY,          -- UUID
    content           TEXT NOT NULL,
    type              TEXT DEFAULT 'fact',
    tags              TEXT,                       -- JSON array
    importance        TEXT DEFAULT 'normal',
    origin            TEXT DEFAULT 'human',
    source_session_id TEXT,
    source_event_id   TEXT,
    content_hash      TEXT NOT NULL,              -- SHA256(content)
    embedding         BLOB,
    embedding_dim     INTEGER,
    embedding_pending INTEGER DEFAULT 0,
    created_at        TEXT NOT NULL,
    epoch_id          TEXT,                       -- NULL = 未消费；消费后写入 epoch_id
    disposition       TEXT,                       -- NULL = 未决；'promoted' / 'dropped'
    drop_reason       TEXT                        -- dropped 时记录原因：'noise' / 'duplicate' / 'below_threshold'
);

CREATE INDEX idx_capture_unconsumed ON capture_log(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX idx_capture_hash ON capture_log(content_hash);
CREATE INDEX idx_capture_created ON capture_log(created_at);
```

Hot Buffer View 查询：`SELECT ... FROM capture_log WHERE epoch_id IS NULL`，结果标记 `provisional=true`，降权排序。

### 1.3 nexus 表

```sql
CREATE TABLE nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    target_id            TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    direction            TEXT DEFAULT 'directed',  -- directed / bidirectional
    type                 TEXT NOT NULL,             -- causal/temporal/semantic/spatial/abstracted_to/perspective
    association_strength REAL DEFAULT 0.5,
    created_at           TEXT NOT NULL,
    last_coactivated_at  TEXT,
    CHECK(source_id <> target_id),
    UNIQUE(source_id, target_id, type)
);

CREATE INDEX idx_nexus_source ON nexus(source_id, type);
CREATE INDEX idx_nexus_target ON nexus(target_id, type);
CREATE INDEX idx_nexus_strength ON nexus(source_id, association_strength DESC);
```

**双向边规范化规则**：`direction='bidirectional'` 时只存一条记录，`source_id < target_id`（字典序）。查询时 `WHERE source_id = ? OR target_id = ?`。

### 1.4 delta_ledger 表

只承载 strength 相关变更（reinforce / decay），不混入 nexus 调整。

```sql
CREATE TABLE delta_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id   TEXT NOT NULL,
    delta_type  TEXT NOT NULL,     -- reinforce / decay（仅此两种）
    delta_value REAL NOT NULL,
    epoch_id    TEXT,              -- NULL = 未消费
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_delta_unconsumed ON delta_ledger(epoch_id) WHERE epoch_id IS NULL;
CREATE INDEX idx_delta_engram ON delta_ledger(engram_id);
```

### 1.5 recon_buffer 表

专管再巩固上下文，带幂等键和双消费标记。

```sql
CREATE TABLE recon_buffer (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    engram_id                TEXT NOT NULL,
    query_context            TEXT,
    coactivated_ids          TEXT,            -- JSON array
    idempotency_key          TEXT UNIQUE,     -- 防重复消费
    nexus_consumed_epoch_id  TEXT,            -- Nexus 更新消费标记
    content_consumed_epoch_id TEXT,           -- 内容再巩固消费标记
    created_at               TEXT NOT NULL
);

CREATE INDEX idx_recon_nexus_unconsumed ON recon_buffer(nexus_consumed_epoch_id)
    WHERE nexus_consumed_epoch_id IS NULL;
CREATE INDEX idx_recon_content_unconsumed ON recon_buffer(content_consumed_epoch_id)
    WHERE content_consumed_epoch_id IS NULL;
```

### 1.6 epochs 表

```sql
CREATE TABLE epochs (
    id               TEXT PRIMARY KEY,       -- UUID
    vault_id         TEXT NOT NULL DEFAULT 'default',
    status           TEXT NOT NULL,           -- leased / running / committed / failed / degraded
    mode             TEXT NOT NULL DEFAULT 'full',    -- full / light
    trigger          TEXT NOT NULL DEFAULT 'manual',  -- manual / scheduled / auto
    seal_timestamp   TEXT NOT NULL,
    lease_acquired   TEXT NOT NULL,
    lease_expires    TEXT NOT NULL,
    llm_base_url     TEXT,
    llm_model        TEXT,
    stats            TEXT,                   -- JSON
    started_at       TEXT,
    committed_at     TEXT,
    error            TEXT
);

CREATE UNIQUE INDEX idx_epoch_active ON epochs(vault_id)
    WHERE status IN ('leased', 'running');
```

### 1.7 cognitive_debt 表

```sql
CREATE TABLE cognitive_debt (
    id                 TEXT PRIMARY KEY,
    type               TEXT NOT NULL,       -- pending_consolidation / pending_abstraction / pending_reconsolidation
    raw_ref            TEXT NOT NULL,        -- JSON: {"source": "capture_log|recon_buffer|cluster", "id": "..."}
    priority           REAL DEFAULT 0.5,
    accumulated_epochs INTEGER DEFAULT 0,
    created_at         TEXT NOT NULL,
    resolved_at        TEXT
);
```

### 1.8 View Store 物化表

CQRS 读侧。Epoch 提交时事务内原地重建。

```sql
CREATE TABLE view_engrams (
    id                TEXT PRIMARY KEY,
    content           TEXT NOT NULL,
    type              TEXT,
    tags              TEXT,
    state             TEXT NOT NULL,
    strength          REAL NOT NULL,
    importance        TEXT,
    origin            TEXT,
    verified          INTEGER,
    rigidity          REAL,
    access_count      INTEGER,
    created_at        TEXT,
    last_accessed     TEXT,
    content_hash      TEXT,
    embedding         BLOB,
    embedding_dim     INTEGER
);

CREATE TABLE view_nexus (
    id                   TEXT PRIMARY KEY,
    source_id            TEXT NOT NULL,
    target_id            TEXT NOT NULL,
    direction            TEXT,
    type                 TEXT NOT NULL,
    association_strength REAL
);

CREATE TABLE view_pointer (
    id           TEXT PRIMARY KEY DEFAULT 'current',
    epoch_id     TEXT,              -- 上次重建的 Epoch ID（审计用）
    refreshed_at TEXT NOT NULL
);
```

### 1.9 runtime_cursors 表

运行时游标，与 view_pointer 分离。

```sql
CREATE TABLE runtime_cursors (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- 初始行：('decay_watermark', <now>, <now>)
```

### 1.10 pending_forget 表

Awake 记录遗忘意图，Epoch 执行。支持 BUFFERED（capture_log）和 CONSOLIDATED（engrams）两种目标。

```sql
CREATE TABLE pending_forget (
    id           TEXT PRIMARY KEY,          -- UUID
    target_table TEXT NOT NULL,             -- 'capture_log' | 'engrams'
    target_id    TEXT NOT NULL,             -- capture_log.id 或 engrams.id
    requested_at TEXT NOT NULL,
    UNIQUE(target_table, target_id)
);
```

**Epoch 处理逻辑**：
- `target_table='engrams'` → T7 状态转换 + CASCADE 清 nexus + 清 delta/recon
- `target_table='capture_log'` → 标记 `disposition='dropped'`, `drop_reason='user_forget'`

### 1.11 迁移脚本

`migrate_v03_to_v05(conn)`:

1. `PRAGMA user_version` 检查（当前值 < 5 才执行）
2. 事务内执行所有 ALTER + CREATE
3. 迁移现有 engrams：
   - `forgotten=0` → `state='consolidated'`
   - `forgotten=1` → `state='forgotten'`
   - rigidity 按 type 赋值：preference/convention → 0.7，fact/decision → 0.5，debugging/insight → 0.15
   - `content_hash = SHA256(content)` 回填
4. 初始化 view_engrams + view_nexus（从 engrams 全量写入 state='consolidated' 的行）
5. 初始化 view_pointer（epoch_id=NULL, refreshed_at=now）
6. 初始化 runtime_cursors（decay_watermark=now）
7. `PRAGMA user_version = 5`

### 1.12 层内冒烟验证

- 迁移完整性：v0.3 数据迁移后 state/rigidity/content_hash 正确
- capture_log：插入 → Hot Buffer 查询 → epoch 标记消费后不再返回
- delta_ledger：插入 reinforce/decay → 按 epoch_id IS NULL 筛选
- recon_buffer：幂等键去重 → 双消费标记独立
- nexus：CRUD + 双向边规范化 + 2 跳 CTE + CASCADE 删除 + CHECK(source<>target)
- epochs：租约互斥（同 vault 两次 lease 第二次失败）
- view_engrams/view_nexus：全量重建 + view_pointer 更新
- pending_forget：插入 + epoch 消费

---

## Layer 2 — 引擎层

所有规则实现为纯函数（compute_* / plan_*），不依赖 CLI/线程/网络。持久化操作集中在 repository.py（apply_*）。

### 2.1 五态状态机（state_machine.py）

```python
STATES = {'buffered', 'consolidated', 'abstracted', 'archived', 'forgotten'}

# 持久状态间的合法转换（discarded 不在此表中）
TRANSITIONS = {
    'buffered':     {'consolidated': 'T1'},
    'consolidated': {'abstracted': 'T5', 'archived': 'T6', 'forgotten': 'T7'},
    'abstracted':   {'archived': 'T8'},
    'archived':     {'consolidated': 'T9', 'forgotten': 'T10'},
    'forgotten':    {},  # 吸收态
}
```

**核心类型**：

```python
class TransitionPlan:
    engram_id: str             # T1 时由 apply 层生成，plan 阶段携带 capture_log_id
    capture_log_id: str | None # 仅 T1 使用
    from_state: str
    to_state: str
    transition: str            # T1/T5-T10
    reason: str
    epoch_id: str
    metadata: dict             # cluster_id, wake_reason, policy_name 等

class DropDecision:
    """L2 丢弃决策 — 不是状态转换"""
    capture_log_id: str
    reason: str                # 'noise' / 'duplicate' / 'below_threshold'
    epoch_id: str
```

**核心函数**：

```python
def validate_transition(from_state: str, to_state: str) -> bool

def plan_l2_candidates(capture_items: list[dict], epoch_context: dict) -> list[dict]:
    """准备待 LLM 结构化的候选和输入
    不做最终判定，仅准备数据。
    """

def materialize_l2_outcomes(
    candidates: list[dict],
    llm_results: list[dict] | None,  # None = Light Sleep
) -> tuple[list[TransitionPlan], list[DropDecision]]:
    """基于 LLM 输出形成 T1Plan 或 DropDecision
    llm_results=None 时不产出任何 plan/drop（数据保持未消费）。
    """

def plan_l3_transitions(engrams: list[dict], epoch_context: dict) -> list[TransitionPlan]:
    """对 L3 engrams 计算 T5/T6/T8/T10
    T7 由 pending_forget 表驱动，不在此函数。
    T9 由外部显式请求触发，不在此函数。
    """
```

**不变量**：
- FORGOTTEN 无出边（吸收态）
- 转换必须在 TRANSITIONS 表中
- 仅 Epoch 上下文内调用

### 2.2 rigidity 引擎（rigidity.py）

```python
RIGIDITY_DEFAULTS = {
    'preference': 0.7, 'convention': 0.7,     # procedural 类
    'fact': 0.5, 'decision': 0.5,              # semantic 类
    'debugging': 0.15, 'insight': 0.15,        # episodic 类
}
CONTENT_LOCK_THRESHOLD = 0.5

def can_modify_content(rigidity: float) -> bool:
    return rigidity < CONTENT_LOCK_THRESHOLD

def max_drift_per_epoch(rigidity: float) -> float:
    if rigidity >= CONTENT_LOCK_THRESHOLD:
        return 0.0
    MAX_DRIFT_STEP = 0.3
    return (1.0 - rigidity) * MAX_DRIFT_STEP
```

**再巩固规划**：

```python
class ReconsolidationPlan:
    engram_id: str
    allow_content_update: bool
    max_drift: float
    llm_inputs: dict           # {current_content, query_contexts, coactivated_contents}
    nexus_candidates: list     # [{source_id, target_id, type, reasoning}]

def plan_reconsolidation(engram: dict, recon_items: list[dict]) -> ReconsolidationPlan | None:
    """规划单条 engram 的再巩固。None = 无需处理。
    allow_content_update=False 时 LLM 仅产出 nexus_candidates。
    """
```

### 2.3 Delta fold 引擎（delta_fold.py）

```python
class StrengthDelta:
    engram_id: str
    net_delta: float
    reinforce_count: int
    decay_count: int
    source_ledger_ids: list[int]    # 精确标记已消费行

class StrengthUpdatePlan:
    engram_id: str
    old_strength: float
    new_strength: float             # clamp 后
    access_count_delta: int         # 仅来自 reinforce_count
    update_last_accessed: bool      # 仅 reinforce_count > 0 时为 True
    source_ledger_ids: list[int]

def fold_deltas(deltas: list[dict]) -> list[StrengthDelta]:
    """按 engram_id 分组折叠，保留 source_ledger_ids"""

def plan_strength_updates(
    folds: list[StrengthDelta],
    engrams_lookup: dict,
) -> list[StrengthUpdatePlan]:
    """折叠结果 → 更新计划
    - clamp(0.0, 1.0)，Agent 未验证上限 0.5
    - 纯 decay 时 update_last_accessed = False
    """

ARCHIVE_THRESHOLD = 0.05
AGENT_STRENGTH_CAP = 0.5
```

### 2.4 衰减引擎（decay.py）

保留现有公式（FSRS v6 幂律），新增带水位的衰减计算。

```python
BASE_HALF_LIFE = 168  # 小时（一周）
IMPORTANCE_FACTOR = {'low': 0.5, 'normal': 1.0, 'high': 2.0, 'critical': 10.0}
MIN_DECAY_DELTA = 0.001

def effective_strength(strength, last_accessed, access_count, importance, now=None) -> float:
    """纯函数：当前有效强度（公式不变）"""

def reinforcement_boost(last_accessed, now=None) -> float:
    """纯函数：强化增量"""

def compute_reinforce_delta(engram: dict, now=None) -> dict:
    """recall 命中时的强化 delta"""

def compute_decay_deltas(
    engrams: list[dict],
    watermark: str,
    now: str = None,
) -> tuple[list[dict], str]:
    """从 watermark 到 now 区间的衰减 delta
    
    - delta = effective_strength(now) - effective_strength(watermark)
    - 仅 abs(delta) > MIN_DECAY_DELTA 时产出
    - 返回 (deltas, new_watermark)
    """
```

### 2.5 赫布学习引擎（hebbian.py）

```python
COACTIVATION_BOOST = 0.05
MAX_ASSOCIATION = 1.0

class NexusUpdatePlan:
    source_id: str              # 已规范化：source_id < target_id
    target_id: str
    type: str
    strength_delta: float
    last_coactivated_at: str
    is_new: bool
    source_recon_ids: list[int] # 精确标记已消费的 recon_buffer 行

def plan_nexus_updates(recon_items: list[dict], existing_nexus: dict) -> list[NexusUpdatePlan]:
    """从 recon_buffer 计算 Nexus 更新
    
    1. 遍历 recon_items，提取 coactivated_ids 对
    2. 内存聚合同一对的 strength_delta（不重复放大）
    3. 双向边规范化：source_id < target_id
    4. 查 existing_nexus 判断 is_new
    5. 汇总 source_recon_ids
    """
```

### 2.6 PulseEvent

```python
class PulseEvent:
    event_type: str = 'recall_hit'
    engram_id: str
    query_context: str
    coactivated_ids: list[str]
    timestamp: str
    idempotency_key: str        # 直接映射 recon_buffer.idempotency_key
```

### 2.7 持久化层（repository.py）

所有 `apply_*` 集中在此，接收 `conn` + Plan 对象：

```python
def apply_transition_plan(conn, plan: TransitionPlan) -> None:
    """UPDATE engrams SET state=?, last_state_changed_epoch_id=?"""

def apply_l2_to_l3(conn, plan: TransitionPlan, capture_item: dict) -> str:
    """T1: capture_log → engrams INSERT + 标记 capture_log.epoch_id
    返回新生成的 engram_id。
    """

def apply_drop_decisions(conn, drops: list[DropDecision]) -> None:
    """标记 capture_log.epoch_id + 记录丢弃原因"""

def apply_strength_plan(conn, plans: list[StrengthUpdatePlan]) -> None:
    """批量更新 strength/access_count/last_accessed + 标记 delta_ledger 行"""

def apply_nexus_plan(conn, plans: list[NexusUpdatePlan]) -> None:
    """INSERT/UPDATE nexus + 标记 recon_buffer.nexus_consumed_epoch_id"""

def apply_pending_forgets(conn, epoch_id: str) -> tuple[int, list[str]]:
    """消费 pending_forget，按 target_table 分别处理：
    
    target_table='engrams':
      UPDATE engrams SET state='forgotten' + CASCADE 清 nexus
      + 清理相关 delta_ledger（未消费）+ 清理相关 recon_buffer（全部）
    
    target_table='capture_log':
      UPDATE capture_log SET epoch_id=?, disposition='dropped', drop_reason='user_forget'
    
    返回 (处理数量, forgotten_engram_ids)。
    """

def update_decay_watermark(conn, new_watermark: str) -> None:
    """更新 runtime_cursors.decay_watermark"""

def defer_to_debt(conn, debt_type: str, raw_ref: dict, epoch_id: str) -> None:
    """记录 cognitive_debt，已有同 raw_ref 的 → accumulated_epochs += 1"""

def resolve_debt(conn, debt_type: str, raw_ref: dict) -> None:
    """核销 cognitive_debt：按 type + raw_ref 找到未 resolved 的债务，设 resolved_at=now"""

def rebuild_view_store(conn, epoch_id: str) -> None:
    """事务内原地重建 view_engrams + view_nexus + 更新 view_pointer
    
    view_engrams 仅包含 state='consolidated' 的记忆。
    archived/abstracted 不进入主视图 — 这是 v0.5.0 的显式降级：
      - ARCHIVED 唤醒路径（Archive Tombstone Index）推迟到 v0.5.1
      - ABSTRACTED 作为间接引用层，不参与主 recall 排序
    """
```

### 2.8 模块依赖图

```
计算层（纯函数，无 IO）：
  state_machine.py  ← 无依赖
  rigidity.py       ← 无依赖
  decay.py          ← 无依赖
  delta_fold.py     ← decay.py 常量（AGENT_STRENGTH_CAP）
  hebbian.py        ← 无依赖

持久化层（接收 conn + Plan）：
  repository.py     ← 依赖上述所有 Plan/Decision 类型
```

### 2.9 层内冒烟验证

- 状态机：合法转换通过、非法拒绝、FORGOTTEN 吸收态、DropDecision 不进 TRANSITIONS
- rigidity：阈值边界精确（0.49→可修改，0.50→不可修改）
- Delta fold：多条 reinforce + decay → 1 条净变更 + source_ledger_ids 完整、Agent 上限 0.5
- 衰减水位：两次 compute 同区间不重复、watermark 推进后仅计算新区间
- strength plan：纯 decay 时 `update_last_accessed=False`
- 赫布：多条 recon_items 含重叠对 → 内存聚合后去重、source_recon_ids 完整
- 幂等：重复 idempotency_key 不报错
- repository：每个 apply 函数独立测试事务正确性

---

## Layer 3 — 轨道层

### 3.1 进程/线程模型

```
┌─────────────────────────────────────────────────┐
│  Worker 进程（常驻）                              │
│                                                  │
│  HTTP 线程: Unix Socket Server（不碰 DB）          │
│    ↓ 请求分发                                     │
│  ┌──────────────────┐  ┌───────────────────────┐ │
│  │ Awake 轨道        │  │ Subconscious 轨道      │ │
│  │ (独占连接 A)       │  │ (独占连接 B)            │ │
│  │                   │  │                        │ │
│  │ capture → L2      │  │ 消费 PulseEvent        │ │
│  │ recall → ViewStore│  │ → delta_ledger         │ │
│  │   + HotBuffer     │  │ → recon_buffer         │ │
│  │ → 抛 PulseEvent   │  │ 定时衰减计算            │ │
│  └────────┬──────────┘  └────────────────────────┘ │
│           │ PulseEvent (Queue)                     │
│           └──→ Subconscious                        │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  Epoch 子进程（按需启动，`memento epoch run`）      │
│                                                  │
│  独占 lease → seal → Phase 1-5 → commit           │
│  调用 LLM（唯一有权）                              │
│  原子重建 View Store                               │
└─────────────────────────────────────────────────┘
```

**连接约束**：
- Awake 独占连接 A（DB 线程内）
- Subconscious 独占连接 B（后台线程内）
- HTTP 线程不碰 DB
- Epoch 子进程创建自己的连接（WAL 允许并发）

### 3.2 Awake 轨道（awake.py）

**capture 路径**：

```python
def awake_capture(conn, content, type, tags, importance, origin,
                  session_id=None, event_id=None) -> dict:
    """capture 只写 L2 capture_log
    
    1. content_hash = SHA256(normalize(content))
    2. embedding = get_embedding(content)  # 同步调用，已知妥协（见 Scope Lock）
       失败时 embedding_pending=1，后续 Epoch 补填
    3. INSERT INTO capture_log (...)
    4. 返回 {capture_log_id, state: 'buffered'}
    
    不触发 PulseEvent（BUFFERED 不参与再巩固）。
    """
```

**recall 路径**：

```python
def awake_recall(conn, query, max_results=5, pulse_queue=None) -> list[dict]:
    """双源查询：View Store + Hot Buffer
    
    1. 查 view_engrams（向量 + FTS5）
    2. 查 capture_log WHERE epoch_id IS NULL（Hot Buffer，向量 + FTS5）
    3. Hot Buffer 结果标记 provisional=True，score 乘 0.5 降权
    4. 合并排序，取 top-K
    5. 对每个命中的 view_engrams 结果：
       - 构造 PulseEvent（含 coactivated_ids = 同次命中的其他 engram IDs）
       - 放入 pulse_queue
       （Hot Buffer 命中不产生 PulseEvent）
    6. 返回结果（不修改任何数据）
    """
```

**forget 路径**：

```python
def awake_forget(conn, target_id: str) -> dict:
    """记录遗忘意图，不直接修改 state
    
    自动判断目标类型：
    - 存在于 capture_log 且未消费 → target_table='capture_log'
    - 存在于 engrams → target_table='engrams'
    
    INSERT INTO pending_forget (id, target_table, target_id, requested_at)
    返回 {status: 'pending', message: 'Will take effect after next epoch run'}
    """
```

**其他只读操作**：status、inspect、nexus 查询、session_* 均走 Awake。

**verify 和 pin 的特殊处理**：
- `verify` 直接更新 engrams.verified（元数据标记，非状态转换）
- `pin` 直接更新 engrams.rigidity（元数据修改，非状态转换）
- 两者同时更新 view_engrams 中对应行，保持 View Store 一致
- 这不违反"仅 Epoch 做状态转换"不变量——verified 和 rigidity 不是 state

**硬约束**：
- 禁止修改 engrams.state（仅 Epoch）
- 禁止调用 LLM
- 禁止读写 delta_ledger / recon_buffer

### 3.3 Subconscious 轨道（subconscious.py）

独立后台线程，在 Worker 进程内运行，独占连接 B。

```python
class SubconsciousTrack:
    def __init__(self, conn_factory, pulse_queue, config):
        self.pulse_queue = pulse_queue         # Queue[PulseEvent]
        self.conn_factory = conn_factory
        self.decay_interval = config.get('decay_interval', 300)  # 秒
        self.shutdown_event = Event()

    def run(self):
        conn = self.conn_factory()
        while not self.shutdown_event.is_set():
            self._drain_pulse_events(conn)
            if self._should_run_decay():
                self._run_decay_cycle(conn)
            self.shutdown_event.wait(timeout=0.5)
        conn.close()

    def _drain_pulse_events(self, conn):
        """批量消费 pulse_queue
        
        对每个 PulseEvent：
        1. compute_reinforce_delta(engram) → INSERT delta_ledger
        2. INSERT recon_buffer (idempotency_key UNIQUE, 冲突跳过)
        """

    def _run_decay_cycle(self, conn):
        """定时衰减
        
        1. 从 runtime_cursors 读 decay_watermark
        2. 查询 view_engrams（只读视图中的活跃记忆）
        3. compute_decay_deltas(engrams, watermark, now)
        4. 批量 INSERT delta_ledger
        5. update_decay_watermark(conn, new_watermark)
        """
```

**硬约束**：
- 禁止写 engrams / nexus / capture_log
- 禁止调用 LLM
- 禁止修改 view_engrams / view_nexus

### 3.4 Sleep/Epoch 轨道（epoch.py）

独立子进程，通过 `memento epoch run` 启动。

#### 3.4.1 Lease 机制

```python
LEASE_TIMEOUT = 3600  # 1 小时

def acquire_lease(conn, vault_id, mode, trigger) -> str | None:
    """尝试获取 Epoch 租约
    1. 清理过期：UPDATE epochs SET status='failed' WHERE lease_expires < now
    2. INSERT epochs (status='leased', seal_timestamp=now, lease_expires=now+TIMEOUT)
    3. 成功 → 返回 epoch_id；UNIQUE 冲突 → None
    """

def promote_lease(conn, epoch_id) -> None:
    """leased → running"""

def renew_lease(conn, epoch_id) -> None:
    """延长 lease_expires"""
```

#### 3.4.2 seal_timestamp 语义

```
seal_timestamp = Epoch 启动时的时间戳

所有数据查询带此约束：
  capture_log   WHERE created_at < seal_timestamp AND epoch_id IS NULL
  delta_ledger  WHERE created_at < seal_timestamp AND epoch_id IS NULL
  recon_buffer  WHERE created_at < seal_timestamp AND nexus_consumed_epoch_id IS NULL
                                                  (或 content_consumed_epoch_id IS NULL)

Epoch 运行期间新产生的数据留给下一个 Epoch。
Awake + Subconscious 可在 Epoch 运行期间不停写入，互不干扰。
```

#### 3.4.3 Epoch 完整流程

```
memento epoch run [--mode full|light] [--trigger manual|scheduled|auto]
│
├─ Phase 0: 获取 Lease
│   ├─ acquire_lease() → epoch_id
│   ├─ 失败 → 报错退出
│   └─ promote_lease() → status='running'
│
├─ Phase 1: 处理 pending_forget (T7)
│   ├─ apply_pending_forgets(conn, epoch_id) → state='forgotten' + CASCADE 清 nexus
│   └─ 同步清理：DELETE delta_ledger WHERE engram_id IN (forgotten_ids) AND epoch_id IS NULL
│                DELETE recon_buffer WHERE engram_id IN (forgotten_ids)
│     （无条件删除所有相关 recon_buffer 行，无论消费状态。
│       防止 Phase 4/5 对已 forgotten 的记忆继续做 Nexus 更新或内容再巩固）
│
├─ Phase 2: L2 整合（BUFFERED → CONSOLIDATED / 丢弃）
│   ├─ 读取 capture_log WHERE epoch_id IS NULL AND created_at < seal_timestamp
│   ├─ [Full] plan_l2_candidates() → LLM 结构化 → materialize_l2_outcomes()
│   │         → T1Plan + DropDecision
│   │         → apply_l2_to_l3() + apply_drop_decisions()
│   │         → resolve_debt(pending_consolidation, {capture_log.id}) 核销对应债务
│   └─ [Light] 数据保持未消费，仅记录 cognitive_debt 索引
│              raw_ref 指向 capture_log.id
│
├─ Phase 3: Delta 折叠 + Strength 更新
│   ├─ 读取 delta_ledger WHERE epoch_id IS NULL AND created_at < seal_timestamp
│   ├─ fold_deltas() → plan_strength_updates()
│   └─ apply_strength_plan()
│
├─ Phase 4: Nexus 更新（从 recon_buffer）
│   ├─ 读取 recon_buffer WHERE nexus_consumed_epoch_id IS NULL
│   │                    AND created_at < seal_timestamp
│   ├─ plan_nexus_updates(recon_items, existing_nexus)
│   └─ apply_nexus_plan()  — 标记 nexus_consumed_epoch_id
│
├─ Phase 5: 再巩固（内容修改）
│   ├─ 读取 recon_buffer WHERE content_consumed_epoch_id IS NULL
│   │                    AND created_at < seal_timestamp
│   ├─ 按 engram_id 分组 → plan_reconsolidation()
│   ├─ [Full] allow_content_update=True → LLM 再巩固 → 更新 content + content_hash
│   │         标记 content_consumed_epoch_id
│   │         → resolve_debt(pending_reconsolidation, {engram_id}) 核销对应债务
│   ├─ [Light] content 修改部分记入 cognitive_debt (pending_reconsolidation)
│   │         recon_buffer 保持 content 未消费
│   └─ [Full] allow_content_update=False → 仅标记 content_consumed_epoch_id
│
├─ Phase 6: 状态转换（T5/T6/T8/T10）
│   ├─ plan_l3_transitions(engrams, epoch_context)
│   ├─ T6: strength < ARCHIVE_THRESHOLD → archived
│   ├─ T5: [Full] 聚类阈值达标 → LLM 抽象化 → abstracted
│   │     → resolve_debt(pending_abstraction, {cluster_id}) 核销对应债务
│   ├─ T5: [Light] 记入 cognitive_debt (pending_abstraction)
│   └─ apply_transition_plan()
│
├─ Phase 7: View Store 重建 + Commit
│   ├─ BEGIN TRANSACTION
│   ├─ rebuild_view_store(conn, epoch_id)
│   │   DELETE FROM view_engrams;
│   │   INSERT INTO view_engrams SELECT ... FROM engrams WHERE state='consolidated';
│   │   DELETE FROM view_nexus;
│   │   INSERT INTO view_nexus SELECT ... FROM nexus WHERE ...;
│   │   UPDATE view_pointer SET epoch_id=?, refreshed_at=now;
│   ├─ UPDATE epochs SET status='committed'|'degraded', stats=..., committed_at=now
│   ├─ COMMIT
│   └─ 失败 → ROLLBACK, UPDATE epochs SET status='failed', error=...
│
└─ 退出
```

#### 3.4.4 Light Sleep 规则总结

| Phase | Full | Light |
|-------|------|-------|
| pending_forget (T7) | 执行 | 执行 |
| L2 整合 | LLM 结构化 | 保持未消费 + debt 索引 |
| Delta fold + strength | 执行（纯数学） | 执行（纯数学） |
| Nexus 更新 | 执行（纯数学） | 执行（纯数学） |
| 再巩固 content | LLM 处理 | 保持未消费 + debt |
| T5 抽象化 | LLM 处理 | debt |
| T6 归档 | 执行（纯数学） | 执行（纯数学） |
| View Store 重建 | 执行 | 执行 |

### 3.5 Worker 进程改造（worker.py）

```python
class WorkerServer:
    def __init__(self, db_path):
        self.pulse_queue = Queue()
        self.awake = AwakeThread(db_path, self.pulse_queue)
        self.subconscious = SubconsciousTrack(
            conn_factory=lambda: get_connection(db_path),
            pulse_queue=self.pulse_queue,
            config={}
        )

    def start(self):
        self.awake.start()
        self.subconscious.start()
        # HTTP Server（不碰 DB）

    def shutdown(self):
        self.subconscious.shutdown()
        self.awake.shutdown()
```

**HTTP 路由**：

| 路由 | 轨道 | 说明 |
|------|------|------|
| `POST /capture` | Awake | 写 capture_log (L2) |
| `POST /recall` | Awake | 双源查询 + PulseEvent |
| `GET /status` | Awake | 只读统计 |
| `POST /session/start` | Awake | 会话管理 |
| `POST /session/end` | Awake | 会话管理 |
| `POST /observe` | Awake | 写 session_events（不进 L2） |
| `POST /forget` | Awake | 写 pending_forget |
| `POST /verify` | Awake | 更新 verified |
| `POST /inspect` | Awake | engram 详情 + nexus |
| `POST /nexus` | Awake | 关联网络查询 |
| `POST /pin` | Awake | 更新 rigidity |
| `POST /flush` | Subconscious | 等待 pulse_queue 清空 |
| `GET /debt` | Awake | cognitive_debt 统计 |

### 3.6 层内冒烟验证

- **Awake capture**：写入 capture_log、不写 engrams、返回 buffered
- **Awake recall**：view_engrams + capture_log 双源合并、Hot Buffer 降权、PulseEvent 入队
- **Awake forget**：写 pending_forget、不修改 state
- **Subconscious**：PulseEvent → delta_ledger + recon_buffer、幂等去重、衰减水位推进
- **Epoch lease**：获取成功、重复获取失败、过期自动清理
- **Epoch seal**：seal 后新数据不被消费
- **Epoch full**：L2→L3 (T1) + delta fold + nexus + view 重建
- **Epoch light**：跳过 LLM、debt 正确、strength/nexus 纯数学正常
- **pending_forget**：T7 在 Epoch 中执行、nexus CASCADE 清理
- **recon_buffer 双消费**：Light Sleep 仅标记 nexus_consumed，content 保留给 Full Sleep
- **端到端冒烟**：
  1. capture → recall (provisional)
  2. epoch run → recall (consolidated)
  3. forget → epoch run → recall (无结果)

---

## Layer 4 — 接口层

### 4.1 API 分层

```python
class MementoAPI:
    """协议抽象层 — 定义操作接口，不绑定具体传输"""
    def capture(...) -> dict
    def recall(...) -> list[dict]
    def forget(id) -> dict
    def verify(id) -> dict
    def status() -> dict
    def inspect(id) -> dict
    def nexus(id, depth) -> list
    def pin(id, rigidity) -> dict
    def session_start/end/status/list
    def epoch_run(mode, trigger) -> dict
    def epoch_status() -> dict
    def epoch_debt() -> dict
    def observe(...)
    def export_memories/import_memories

class WorkerClientAPI(MementoAPI):
    """走 Unix Socket 与 Worker 通信"""
    def __init__(self, socket_path): ...

class LocalAPI(MementoAPI):
    """直接连 DB，供 epoch run 子进程或离线 CLI 使用"""
    def __init__(self, db_path): ...
```

### 4.2 CLI 命令变更

**保留（签名不变，内部切换新内核）**：

| 命令 | 内部变更 |
|------|---------|
| `memento capture <content> --type --importance --tags --origin` | 写 capture_log |
| `memento recall <query> --max --format` | 双源查询 |
| `memento forget <id>` | 写 pending_forget |
| `memento verify <id>` | 不变 |
| `memento status` | 新增 state/delta/debt 统计 |
| `memento export / import` | export 仅 L3 engrams + nexus；import 不导入运行时表 |
| `memento session start/end/status/list` | 不变 |
| `memento observe` | 写 session_events |

**移除的参数**：

| 参数 | 原因 |
|------|------|
| `recall --mode A\|B` | A/B 实验框架移除 |
| `recall --reinforce` | 强化由 PulseEvent 自动处理 |

被移除的参数调用时打印迁移提示，不崩溃。

**新增命令**：

```bash
memento epoch run [--mode full|light] [--trigger manual|scheduled|auto]
memento epoch status
memento epoch debt

memento inspect <id>         # engram 详情 + state/rigidity + nexus + pending flags
memento nexus <id> [--depth 1|2]
memento pin <id> --rigidity <value>
```

**输出变化**：

```bash
# capture
$ memento capture "Redis 缓存击穿修复" --type debugging --origin agent
Captured to L2 (buffered): a1b2c3d4
→ Will be consolidated in next epoch run.

# recall — provisional 标记
$ memento recall "Redis"
[1] (provisional) Redis 缓存击穿修复  score=0.42
[2] Redis 连接池配置建议  strength=0.71  score=0.68

# forget
$ memento forget a1b2c3d4
Marked for deletion. Will take effect after next epoch run.
```

### 4.3 MCP Tools 变更

**保留**（签名微调）：

| Tool | 变更 |
|------|------|
| `memento_capture` | 返回值新增 `state: 'buffered'` |
| `memento_recall` | 新增 `provisional` 标志，移除 `mode`/`reinforce` |
| `memento_forget` | 返回 pending 状态 |
| `memento_verify` | 不变 |
| `memento_status` | 新增 state/delta/debt |
| `memento_observe` | 不变 |
| `memento_session_*` | 不变 |
| `memento_export / import` | 语义收窄（仅 L3） |

**移除**：

| Tool | 原因 |
|------|------|
| `memento_set_session / get_session` | 被 session_start/end 覆盖 |
| `memento_evaluate` | A/B 框架移除 |
| `memento_backfill_embeddings` | Epoch 内处理 |

**新增**：

| Tool | 说明 |
|------|------|
| `memento_epoch_run` | 触发 Epoch |
| `memento_epoch_status` | Epoch 记录 |
| `memento_epoch_debt` | cognitive_debt |
| `memento_inspect` | engram 详情 |
| `memento_nexus` | 关联查询 |
| `memento_pin` | 设置 rigidity |

**MCP Resources**：

| Resource | 状态 |
|----------|------|
| `memory://status` | 更新：新增统计 |
| `memory://epochs` | 新增 |
| `memory://debt` | 新增 |

### 4.4 Hooks 适配

**hooks.json**（沿用现有仓库格式）：

```json
{
  "description": "Memento v0.5 hooks — session lifecycle, observation, and epoch trigger",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/hook-handler.sh session-start",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/hook-handler.sh observe",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/hook-handler.sh flush-and-epoch",
            "timeout": 15
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/hook-handler.sh session-end",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

**Stop hook epoch 触发策略**：

带冷却和节流。使用与现有 hook-handler.sh 一致的 `send_to_worker` 函数通过 Unix Socket 通信：

```bash
# hook-handler.sh flush-and-epoch 分支
MIN_EPOCH_INTERVAL=300          # 秒，距上次 epoch 至少间隔 5 分钟
MIN_PENDING_ITEMS=1             # 至少有 1 条待消费数据

# 1. flush（等待 pulse_queue 清空）
send_to_worker "$SOCK_PATH" POST /flush "{\"claude_session_id\": \"$CLAUDE_SID\"}"

# 2. 查询 status（检查冷却和阈值）
STATUS=$(send_to_worker "$SOCK_PATH" GET /status "")

# 3. 检查冷却
last_epoch=$(echo "$STATUS" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('last_epoch_committed_at', '1970-01-01T00:00:00'))
")
elapsed=$(python3 -c "
from datetime import datetime, timezone
last = datetime.fromisoformat('$last_epoch'.replace('Z','+00:00'))
print(int((datetime.now(timezone.utc) - last).total_seconds()))
" 2>/dev/null || echo 99999)
if [ "$elapsed" -lt "$MIN_EPOCH_INTERVAL" ]; then exit 0; fi

# 4. 检查阈值
pending=$(echo "$STATUS" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('pending_capture', 0) + d.get('pending_delta', 0))
")
if [ "$pending" -lt "$MIN_PENDING_ITEMS" ]; then exit 0; fi

# 5. 触发 light epoch
memento epoch run --mode light --trigger auto
```

**`GET /status` 响应契约**（v0.5 新增字段）：

```json
{
  "total_engrams": 42,
  "by_state": {"consolidated": 38, "archived": 3, "forgotten": 1},
  "active_session_ids": ["sid-1"],
  "pending_capture": 5,
  "pending_delta": 12,
  "pending_recon": 8,
  "cognitive_debt_count": 2,
  "last_epoch_committed_at": "2026-04-01T12:00:00Z",
  "last_epoch_mode": "full",
  "decay_watermark": "2026-04-01T11:55:00Z"
}
```

### 4.5 export / import 语义

```python
def export_memories(core, **filters) -> dict:
    """仅导出 L3 数据：
    - engrams (state != 'forgotten')
    - nexus
    - 元数据（version, exported_at, stats）
    
    不导出：capture_log, delta_ledger, recon_buffer, cognitive_debt,
            runtime_cursors, epochs, pending_forget, view_*
    """

def import_memories(core, data, source) -> dict:
    """导入到 L3：
    - engrams: strength 上限 0.5，origin 保留
    - nexus: 随 engrams 导入
    - 运行时表不触碰
    - 导入完成后同步调用 rebuild_view_store()，确保导入的记忆立即可查询
      （不等下次 epoch，避免"导入成功但查不到"）
    """
```

### 4.6 CLAUDE.md / AGENTS.md 更新要点

```markdown
# 主要变更
- capture 写入 L2（buffered），epoch 后进入长期记忆
- recall 可能返回 provisional 结果
- forget 标记删除意图，epoch 后生效
- 新命令：epoch run/status/debt, inspect, nexus, pin
- 移除：--mode A|B, --reinforce
```

### 4.7 向后兼容

被移除的参数/命令调用时打印迁移提示，不崩溃：

```python
if args.mode:
    print("Warning: --mode removed in v0.5. A/B framework retired.")
if args.reinforce:
    print("Warning: --reinforce removed. Reinforcement is automatic via PulseEvent.")
```

MCP 中移除的 tool 调用返回包含迁移指引的错误信息。

### 4.8 层内冒烟验证

- CLI capture → recall：buffered + provisional
- CLI epoch run：子进程启动执行退出，provisional → consolidated
- CLI forget：pending → epoch → 不可查
- CLI inspect/nexus/pin：输出正确
- MCP 全量 tool 测试
- Hooks：Stop hook 冷却+节流正确、触发 light epoch
- 兼容性：旧参数打印迁移提示
- export/import：仅 L3 数据、运行时表不受影响
- **端到端完整链路**：
  1. `memento capture "test"` → buffered
  2. `memento recall "test"` → provisional 命中
  3. `memento epoch run --mode full` → consolidated
  4. `memento recall "test"` → 正式命中
  5. `memento inspect <id>` → state=consolidated, rigidity=0.5
  6. `memento forget <id>` → pending
  7. `memento epoch run` → forgotten
  8. `memento recall "test"` → 无结果

---

## LLM 抽象层

### 配置

```bash
MEMENTO_LLM_BASE_URL=https://api.openai.com/v1    # OpenAI 兼容接口
MEMENTO_LLM_API_KEY=sk-xxx
MEMENTO_LLM_MODEL=gpt-4o-mini

# 可选
MEMENTO_LLM_TIMEOUT=30           # 秒
MEMENTO_LLM_MAX_RETRIES=3
MEMENTO_LLM_TEMPERATURE=0
```

### 接口

```python
class LLMClient:
    """OpenAI 兼容 API 客户端"""
    
    def __init__(self, base_url, api_key, model, timeout=30, max_retries=3, temperature=0):
        ...
    
    def generate(self, prompt: str, system: str = None) -> str:
        """文本生成"""
    
    def generate_json(self, prompt: str, system: str = None) -> dict:
        """JSON 模式生成（response_format=json_object）"""
```

### Epoch 内使用

- 单次 Epoch 启动时创建 LLMClient 实例，绑定当前配置
- `epoch.llm_base_url` 和 `epoch.llm_model` 记录到 epochs 表（审计）
- 调用失败：同 provider 重试 → 仍失败 → 当前项记入 cognitive_debt，继续下一项
- 所有 LLM 不可用：整个 Epoch 降级为 light mode（status='degraded'）

### 不支持

- 非 OpenAI 兼容的原生 API（如 Anthropic Messages API）
- 跨 provider 自动 failover
- 多 model 混用（如日常 Haiku + 重要 Opus）— 推到 v0.5.1+

---

## 数据迁移

### migrate_v03_to_v05(conn)

1. `PRAGMA user_version` 检查（< 5 才执行）
2. 单事务内：
   - ALTER engrams + 新增所有表（capture_log, nexus, delta_ledger, recon_buffer, epochs, cognitive_debt, view_engrams, view_nexus, view_pointer, runtime_cursors, pending_forget）
   - `forgotten=0` → `state='consolidated'`，`forgotten=1` → `state='forgotten'`
   - rigidity 按 type 赋值
   - content_hash 回填
   - view_engrams 从 engrams 全量写入 `state='consolidated'` 的行
   - view_pointer 初始化
   - runtime_cursors 初始化（decay_watermark=now）
3. `PRAGMA user_version = 5`

### 安全约束

- 迁移前自动备份（cp default.db default.db.v03-backup）
- 迁移失败自动回滚（事务内）
- 幂等：已迁移的库（user_version >= 5）跳过
