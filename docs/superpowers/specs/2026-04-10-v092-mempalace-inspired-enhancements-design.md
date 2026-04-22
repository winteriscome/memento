# v0.9.2 Design Spec — MemPalace-Inspired Enhancements

> **Version**: v0.9.2
> **Date**: 2026-04-10
> **Status**: Draft
> **Baseline**: v0.9.1 (commit 51add9f)
> **Inspiration**: [MemPalace](https://github.com/milla-jovovich/mempalace) 对比分析
>
> **版本说明**：Earlier roadmap documents use an older milestone naming scheme (v0.6/v0.7). This spec follows the repository's current implementation version line (v0.9.x). 以 `docs/README.md` 的 source-of-truth 约定为准：实现以 `src/memento/` 和 tests 为权威。

## 1. 概述

### 1.1 背景

通过与 [MemPalace](https://github.com/milla-jovovich/mempalace) 的能力对比分析，识别出 Memento 在以下方面可以借鉴的设计理念：

- **分层上下文注入**：MemPalace 的四层记忆栈（L0-L3）vs Memento 的单次 top-5 recall
- **本地嵌入优先**：MemPalace 的零 API 成本默认 vs Memento 的云端优先 fallback 链
- **时序关系生命周期**：MemPalace 的时序知识图谱 vs Memento 的单调累积 Nexus

### 1.2 范围

| 编号 | 改进项 | 优先级 | 范围 |
|------|--------|--------|------|
| 1 | 分层上下文注入 | P0 | **实现** |
| 2 | 本地嵌入优先 | P0 | **实现** |
| 3 | 时序知识图谱增强 | P1 | **实现** |
| 4 | 标准化基准 | P2 | 仅设计 |
| 5 | 写前审计日志 | P2 | 仅设计 |
| 6 | 多格式对话导入 | P3 | 仅设计 |
| 7 | 逐字存储补充层 | P3 | 仅设计 |

---

## 2. P0: 分层上下文注入

### 2.1 问题陈述

当前 `api.py:session_start()` 的 priming 逻辑是单次 `recall(query, max_results=5)`（[api.py:172-176](../../src/memento/api.py#L172-L176)），存在三个核心缺陷：

1. **类型挤占**：5 条 slot 可能全被同一类型占满（如 5 条 fact，0 条 convention）
2. **身份/偏好不稳定**：priming 强依赖 `task`/`project`/`query` 命中，关键规则可能静默掉线
3. **task mismatch 脆弱**：query 不匹配时，priming 质量骤降

### 2.2 设计方案：三层注入

将 priming 从"一刀切 top-N"重构为分层递进：

```
L0 — Identity Layer（固定预算 3）
├─ 来源：preference + convention
├─ 排序：原始 strength DESC
├─ 选择策略：preference top-1 + convention top-1 + wildcard top-1
├─ 特点：不依赖 task 关键词，始终注入
├─ 目的：确保用户身份/偏好/核心约定始终在场

L1 — Core Memory Layer（固定预算 2）
├─ 来源：decision / fact / insight
├─ 排序：effective_strength DESC（Python 内存计算）
├─ 选择策略：三类候选池取最强 2 条
├─ 准入门槛：effective_strength >= MIN_L1_THRESHOLD（初始值 0.15）
├─ 规则：debugging 类型显式排除
├─ 特点：不依赖 task，保证核心知识覆盖但不过度占预算

L2 — Task-Relevant Layer（动态剩余预算）
├─ 来源：现有 recall(query) 逻辑
├─ 预算：priming_max - len(L0) - len(L1)
├─ 规则：排除已进入 L0/L1 的 engram id
├─ 特点：补充当前任务相关上下文
```

### 2.3 strength vs effective_strength 的哲学区分

| 层级 | 排序依据 | 理由 |
|------|---------|------|
| L0 | `strength` | preference/convention 的 rigidity 高达 0.7，衰减极慢。用原始 strength 排序确保**核心身份的不可变性**——"你是谁"不应因最近没写某语言的代码就褪色。**这是刻意的产品哲学选择，不是遗漏。** L0 的目标是 identity stability，不是 freshness。若后续观察到 L0 长期僵化，可在同层 tie-break 中加入 freshness 作为次级排序键 |
| L1 | `effective_strength` | decision/fact/insight 的 rigidity 较低（0.15-0.5），衰减明显。用 effective_strength 确保**工作上下文的时效性**——上周频繁调优的数据库方案比半年前的日志格式决策更重要 |

### 2.4 跨项目污染防护（Project Boundary）

**风险**：L0/L1 若做全局 `ORDER BY strength DESC`，会发生跨项目记忆穿透。例如在 Go 项目中被注入 Node.js 项目的 convention "必须使用 pnpm"。

**解决方案**：`awake_recall_by_type()` 必须支持 project 过滤，通过 `source_session_id → sessions.project` 关联实现隔离：

```sql
-- L0 查询示例（L1 同理，替换 type 列表）
SELECT v.* FROM view_engrams v
JOIN engrams e ON v.id = e.id
LEFT JOIN sessions s ON e.source_session_id = s.id
WHERE v.type IN ('preference', 'convention')
  AND (s.project = :project OR s.project IS NULL)
ORDER BY v.strength DESC
LIMIT :candidate_limit
```

`s.project IS NULL` 条件同时涵盖三种情况（得益于 LEFT JOIN）：

1. 明确匹配当前 project 的记忆
2. 来源于全局会话（session 存在但 project 为 NULL）的记忆
3. 手动 capture，没有 source_session_id 的孤立记忆

**当前 session 无 project 时的规则**：若 `session_start(project=None)`，则 L0/L1 **仅注入全局记忆**（`s.project IS NULL` 的记忆），不拉入任何项目特定记忆。无项目会话缺乏可信项目边界，默认只注入全局记忆以避免项目特定记忆泄漏。

实现方式：当 `:project` 为 NULL 时，SQL 条件退化为 `WHERE s.project IS NULL`，只匹配全局会话和孤立记忆。

### 2.5 L1 的两步法计算

SQLite 中没有 `effective_strength` 列，该值是运行时结合 `now` 动态计算的（`memento.decay.effective_strength`）。

L1 的实现步骤：

1. **SQL 取候选集**：按 `project` 和 `type IN ('decision', 'fact', 'insight')` 查出候选（LIMIT 50，按 `last_accessed DESC` 初步排序，保证近期活跃的记忆优先进入候选池）
2. **Python 内存算分**：遍历候选，调用 `compute_eff_strength()` 计算 effective_strength
3. **按 type 分组取 Top**：Group By type → 每组取 effective_strength 最高的 1 条 → 全局取最强 2 条
4. **准入门槛过滤**：仅纳入 `effective_strength >= MIN_L1_THRESHOLD` 的候选（初始值 `0.15`，可调整）

### 2.6 动态 Slot 分配（优雅降级）

采用**动态减法分配**而非硬编码：

```python
L0_BUDGET = 3
L1_BUDGET = 2
PRIMING_MAX = 7  # 总上限

l0_results = _recall_l0(project, budget=L0_BUDGET)  # min(3, 可用身份记忆数)
l1_results = _recall_l1(project, budget=L1_BUDGET)  # min(2, 合格核心记忆数)

l2_budget = PRIMING_MAX - len(l0_results) - len(l1_results)
l2_exclude_ids = {m["id"] for m in l0_results + l1_results}
l2_results = _recall_l2(query, budget=l2_budget, exclude_ids=l2_exclude_ids)
```

**空库/新项目降级**：L0=0, L1=0 时，L2 自动拿满 7 个 slot，100% 向后兼容旧版逻辑。

### 2.7 L0 内部分配策略

防止 preference/convention 内部互相挤占：

```python
def _recall_l0(project: str, budget: int = 3) -> list[dict]:
    candidates = _query_by_types(project, types=["preference", "convention"])
    
    pref_top1 = top_by_type(candidates, "preference", n=1)
    conv_top1 = top_by_type(candidates, "convention", n=1)
    
    selected_ids = {m["id"] for m in pref_top1 + conv_top1}
    remaining = [c for c in candidates if c["id"] not in selected_ids]
    wildcard = sorted(remaining, key=lambda x: x["strength"], reverse=True)[:1]
    
    return (pref_top1 + conv_top1 + wildcard)[:budget]
```

### 2.8 MCP Layer 标记

priming 返回结果中每条记忆增加 `layer` 字段：

```json
{"id": "...", "content": "...", "type": "preference", "layer": "L0"}
```

MCP priming prompt 格式化时，推荐按 layer 分组，并添加结构化标记前缀：

```
[L0-Identity] 始终使用中文注释
[L0-Identity] 测试覆盖率不低于 80%
[L1-Core] 数据库采用 SQLite WAL 模式
[L2-Context] 上次讨论了 epoch 的七阶段流程
```

标记前缀定位为**结构化提示符**，帮助 LLM 和人类 debug 时区分上下文作用域。消费方可自定义或省略前缀。

### 2.9 改动范围

| 文件 | 改动 |
|------|------|
| `api.py` | `session_start()` 重构 priming 逻辑为三层编排 |
| `awake.py` | 新增 `awake_recall_by_type(conn, types, project, limit)` |
| `mcp_server.py` | priming prompt 按 layer 分组输出 + layer 标记 |
| priming 常量 | 新增 `L0_BUDGET`, `L1_BUDGET`, `PRIMING_MAX`, `MIN_L1_THRESHOLD`（具体落点可在 `api.py` 或专用配置模块中确定） |

### 2.10 向后兼容

- `priming_max` 参数保留，作为总量上限（默认从 5 提升到 7）
- L0/L1 候选不足时由 L2 补足
- 整体候选极少（空库）时退化为现有单次 recall 行为
- `SessionStartResult` 中 `layer` 为可选增量字段（optional additive field）。消费方必须忽略未知字段以保证前向兼容（consumers must ignore unknown fields for forward compatibility）

### 2.11 测试要点

**核心逻辑测试：**
- L0 保证 preference / convention 不被 fact 挤掉
- L0 内部 preference / convention 各有保底 slot
- L1 保证类型多样性（不全是 decision）
- L1 准入门槛生效（弱记忆不强行塞入）
- L2 去重不重复 L0/L1

**边界条件测试：**
- 跨项目过滤：Go 项目不注入 Node.js convention
- 全局记忆（project=NULL）能被所有项目看到
- 空库 fallback：L2 拿满额度

**API/MCP 契约测试：**
- priming_max 上限生效
- MCP 输出包含 layer 标记
- SessionStartResult dataclass 新增 layer 字段后旧客户端兼容
- MCP priming prompt 格式化按 layer 分组

**受影响的现有测试文件：**
- `tests/test_api.py` — session_start 返回值结构
- `tests/test_mcp_server.py` — priming prompt 格式
- `tests/test_awake.py` — 新增 awake_recall_by_type 测试

---

## 3. P0: 本地嵌入优先

### 3.1 问题陈述

当前 `embedding.py` 的本地模型（`all-MiniLM-L6-v2`, 384d）是第 6 优先级的 fallback（[embedding.py:134-179](../../src/memento/embedding.py#L134-L179)）。用户不配置 API key 时，系统能工作但这是"意外降级"而非"有意设计"。

**这是一次行为变更**，不是纯内部优化：

| | 旧行为 | 新行为 |
|--|--------|--------|
| 全新安装，无配置 | 扫描 legacy env → local fallback → pending/FTS5 | 直接使用 local provider |
| 测试契约 | `cfg["embedding"]["provider"] is None` | `cfg["embedding"]["provider"] == "local"` |
| 用户感知 | "没配 API key，语义搜索不可用" | "默认本地模型，语义搜索可用" |

### 3.2 设计方案

#### 3.2.1 配置层

`config.py` 的 `_defaults()` 中 `embedding.provider` 从 `None` 改为 `"local"`：

```python
"embedding": {
    "provider": "local",  # 从 None 改为 "local"
    "api_key": None,
    "model": None,
}
```

#### 3.2.2 运行时

`embedding.py` 的 `provider_map` 增加 `"local": _embed_local`：

```python
provider_map = {
    "zhipu": _embed_zhipu, "minimax": _embed_minimax,
    "moonshot": _embed_moonshot, "openai": _embed_openai,
    "gemini": _embed_gemini,
    "local": _embed_local,  # 新增
}
```

当配置为 `local` 时，走配置路径（`provider_map` 直接调用），跳过 legacy env 扫描。语义从"fallback"变为"显式选择"。

#### 3.2.3 缺依赖时的行为

当 `provider == "local"` 但 `sentence-transformers` 未安装时：

- **不伪装成已正常配置**
- 返回 `(None, 0, True)`（即 `is_pending=True`）
- `doctor` 明确提示：`pip install memento[local]`
- `setup wizard` 检测到依赖缺失时引导安装

#### 3.2.4 Setup Wizard

local 作为第一个选项，默认选中：

```
选择嵌入模型供应商：
> [1] 本地模型（无需 API key，适合快速开始）  ← 默认
  [2] 智谱 (Zhipu)
  [3] OpenAI
  [4] Gemini
  [5] 跳过（仅使用全文搜索）
```

**文案约束**：不使用"开箱即用"等暗示质量也最优的措辞。如用户选择 local，补充提示：

> 本地模型适合快速开始。如主要处理中文内容，建议后续配置云端 embedding provider 以获得更稳定的语义检索质量。

#### 3.2.5 Doctor 改造（provider-aware）

| 状态 | Doctor 输出 |
|------|------------|
| `provider=local` + deps present | ✅ Embedding: local (all-MiniLM-L6-v2, 384d) |
| `provider=local` + deps missing | ⚠️ Embedding: local provider configured but sentence-transformers not installed. Run: `pip install memento[local]` |
| `provider=cloud` + key present | ✅ Embedding: zhipu (embedding-3, 2048d) |
| `provider=cloud` + key missing | ⚠️ Embedding: zhipu configured but API key missing |
| `provider="none"` (skip) | ✅ Embedding: skipped (full-text search only) |
| `provider` unset / `None` (legacy) | ⚠️ Embedding: no provider configured, run `memento setup` to configure |

**skip 的规范化内部表示**：setup wizard 的"跳过"选项将 `embedding.provider` 写为字符串 `"none"`（非 Python `None`），以区分"显式跳过"和"从未配置"两种状态。

### 3.3 与旧 spec 的关系

本文档 supersedes `docs/superpowers/specs/2026-04-09-setup-wizard-design.md` 中关于 embedding provider 默认推荐顺序的定义。旧 spec 中"skip embedding = FTS-only"的语义不再是唯一的无配置路径；新默认为 `provider: "local"`。

### 3.4 不做的事

- 不替换本地默认模型（保持 `all-MiniLM-L6-v2`）
- 不引入 GPU/MPS 加速
- 不改变 `sentence-transformers` 作为 optional dependency 的定位
- 不改变四层配置优先级（MEMENTO_* env > config.json > legacy env > defaults）

### 3.5 改动范围

| 文件 | 改动 |
|------|------|
| `config.py` | `_defaults()` embedding.provider 改为 `"local"` |
| `embedding.py` | `provider_map` 增加 `"local"` 入口 |
| `cli.py` | setup wizard 调整选项顺序和默认值 + 中文质量提示 |
| `cli.py` | doctor 命令改为 provider-aware |
| `README.md` / `README.zh-CN.md` | 同步更新 provider 优先级和默认行为描述 |
| `tests/test_config.py` | 更新 `provider is None` 断言为 `provider == "local"` |

### 3.6 向后兼容

- 已有 `config.json` 中显式配置其他 provider 的用户不受影响
- 已有环境变量 `ZHIPU_API_KEY` 等的用户不受影响（legacy env 优先级高于 defaults）
- 唯一变化：全新安装且无任何配置的用户

### 3.7 Release Note 要点

- 新安装用户默认使用 local embedding provider
- 若未安装 `memento[local]`，需补装本地依赖
- 若主要处理中文内容，建议配置云端 embedding provider 以获得更稳定语义检索质量

---

## 4. P1: 时序知识图谱增强

### 4.1 问题陈述

当前 Nexus 表（[migration.py:36-47](../../src/memento/migration.py#L36-L47)）只有 `created_at` 和 `last_coactivated_at`，没有 `invalidated_at`。`plan_nexus_updates()`（[hebbian.py:65-146](../../src/memento/hebbian.py#L65-L146)）只做增量累加，没有衰减或失效逻辑。

现状问题：

- 关联一旦建立就永远有效，无法表达"曾经相关但现在不再相关"
- 查询无法限定时间窗口
- Nexus 只会单调增长，没有生命周期管理
- `view_nexus` 只过滤"consolidated engram 之间的边"，不过滤"active 边"

### 4.2 设计方案：最小生命周期增强

在不引入完整 temporal graph / entity-triple 系统的前提下，为 Nexus 增加最小生命周期语义。

#### 4.2.1 Schema 变更

```sql
ALTER TABLE nexus ADD COLUMN invalidated_at TEXT;  -- NULL = 当前有效
```

通过 `migrate_v05_to_v092()` 幂等迁移添加。`view_nexus` 同步携带 `invalidated_at` 列（完整投影，不预过滤）。

#### 4.2.2 默认查询语义

所有查询面默认仅返回 `invalidated_at IS NULL` 的边：

| Surface | 默认行为 | 历史边访问 |
|---------|---------|-----------|
| CLI `memento nexus` | 仅 active | `--include-invalidated` |
| MCP `memento_nexus` | 仅 active | `include_invalidated=True` |
| `inspect()` | 仅 active | 后续扩展参数 |
| Dashboard detail | 仅 active | 后续扩展 UI |
| `export` | **完整导出**（含 invalidated） | — |
| `import` | **保留 invalidated_at** | — |
| Worker `/nexus` route | 仅 active | 透传 MCP 参数 |
| `api.py` inspect/detail | 仅 active | 后续扩展参数 |

**Export/Import 保留历史语义**：导出包含 invalidated_at 字段，导入时保留该值，不 silently 丢弃。

#### 4.2.3 MCP / 查询增强

`memento_nexus` 增加可选参数：

```python
def memento_nexus(
    engram_id: str,
    depth: int = 1,
    include_invalidated: bool = False,  # 新增
    since: str | None = None,           # 新增：last_coactivated_at >= since，ISO 8601 格式（如 "2026-04-10T12:00:00Z"）
    until: str | None = None,           # 新增：last_coactivated_at <= until，ISO 8601 格式
) -> list[dict]:
```

#### 4.2.4 手动失效

新增 MCP 工具：

```python
def memento_nexus_invalidate(nexus_id: str) -> dict:
    """设置 invalidated_at = now()。"""
```

首版按 `nexus_id` 定位。后续可扩展按 `(source_id, target_id, type)` 定位失效。

#### 4.2.5 自动失效

Epoch Phase 4 在 nexus updates 后增加 stale-edge scan：

```python
NEXUS_ARCHIVE_THRESHOLD = 0.1   # 初始启发式默认，非理论常量
NEXUS_STALE_DAYS = 90           # 初始启发式默认，允许后续调整

# Phase 4 新增步骤
stale_edges = conn.execute("""
    SELECT id FROM nexus
    WHERE invalidated_at IS NULL
      AND association_strength < :threshold
      AND last_coactivated_at < :cutoff
""", {
    "threshold": NEXUS_ARCHIVE_THRESHOLD,
    "cutoff": (now - timedelta(days=NEXUS_STALE_DAYS)).isoformat(),
}).fetchall()

for edge in stale_edges:
    conn.execute(
        "UPDATE nexus SET invalidated_at = ? WHERE id = ?",
        (now.isoformat(), edge["id"]),
    )
```

**阈值定位**：作为保守启发式参数，允许根据真实数据调整，不是"理论最优值"。

**首轮观察要求**：首次启用自动失效后，应记录被标记的 edge 数量并人工抽样复核，确认阈值不会过度清理有价值的弱关联。

#### 4.2.6 复活语义

若已失效的同 key nexus 在未来再次 coactivate：

```python
# repository.py apply_nexus_plan() 中
existing = conn.execute(
    "SELECT id, invalidated_at FROM nexus WHERE source_id=? AND target_id=? AND type=?",
    (plan.source_id, plan.target_id, plan.type),
).fetchone()

if existing and existing["invalidated_at"] is not None:
    # 复活原边
    conn.execute("""
        UPDATE nexus SET
            invalidated_at = NULL,
            last_coactivated_at = ?,
            association_strength = association_strength + ?
        WHERE id = ?
    """, (plan.last_coactivated_at, plan.strength_delta, existing["id"]))
```

复活而非新建，保持 edge identity 稳定，保留历史连续性。

#### 4.2.7 view_nexus 语义

`view_nexus` 是**完整投影视图**，包含 active + invalidated 边，携带 `invalidated_at` 列。各查询面自行添加 `WHERE invalidated_at IS NULL` 过滤。

理由：若 view_nexus 只存 active 边，后续做历史查询时需绕回 nexus 基础表，导致 query surface 分裂。

### 4.3 不做的事

- 不引入 entity/triple 表
- 不引入完整时间线重建（MemPalace `kg_timeline` 级别）
- 不修改 `plan_nexus_updates()` 核心聚合逻辑
- 不加复杂 temporal query DSL
- 不加实体类型标注（保持赫布学习的自动涌现哲学）
- 不为 invalidated nexus 增加二次归档/物理删除策略——本版只引入 soft invalidation

### 4.4 改动范围

| 文件 | 改动 |
|------|------|
| `migration.py` | 新增 `migrate_v05_to_v092()` 添加 `invalidated_at` 列 |
| `epoch.py` | Phase 4 增加 stale-edge scan 步骤 |
| `mcp_server.py` | `memento_nexus` 增加时间过滤参数 + 新增 `memento_nexus_invalidate` |
| `cli.py` | nexus CTE 查询增加 `invalidated_at IS NULL` |
| `repository.py` | 增加 `invalidate_nexus()` 方法 + `apply_nexus_plan()` 复活逻辑 |
| `export.py` | 导出包含 `invalidated_at`；导入保留该字段 |
| view_nexus 重建逻辑 | 同步 `invalidated_at` 列 |
| `epoch.py` 或共享常量模块 | 新增 `NEXUS_ARCHIVE_THRESHOLD`, `NEXUS_STALE_DAYS`（属于 epoch stale-edge policy，不属于 Hebbian planning 核心） |

### 4.5 向后兼容

- 旧 Nexus 记录 `invalidated_at = NULL`，默认有效，行为不变
- 旧 `memento_nexus` 调用不带新参数时行为不变（默认 `include_invalidated=False`）
- `view_nexus` 保持完整投影，不破坏依赖它的查询

### 4.6 测试要点

- 自动失效：弱且超期的边被标记 invalidated
- 自动失效：强边或近期活跃的边不被误杀
- 复活：已失效边在 coactivation 后恢复 active
- 复活：strength 正确累加、invalidated_at 清空
- 默认查询：各 surface 默认不返回 invalidated 边
- 历史查询：`include_invalidated=True` 时返回完整数据
- 时间过滤：`since` / `until` 正确过滤
- 手动失效：`memento_nexus_invalidate` 正确设置 invalidated_at
- export/import：invalidated_at 不丢失
- 迁移幂等：多次执行 `migrate_v05_to_v092()` 不报错

**受影响的现有测试文件：**
- `tests/test_epoch.py` — Phase 4 新增 stale-edge scan
- `tests/test_export.py` — nexus 导出/导入包含 invalidated_at
- `tests/test_migration.py` — 新迁移函数测试

---

## 5. P2: 标准化基准（仅设计）

### 5.1 目标

引入公开、可重复的长期记忆 benchmark，提升项目可信度，并为后续优化提供统一回归门槛。

### 5.2 设计方向

- 以 **LongMemEval** 作为首个主基准
- 基于现有 `memento eval` 扩展标准数据集加载器
- release 前运行完整 benchmark，检测性能/质量回归
- README 公开 benchmark 数据，并标明测试配置

### 5.3 边界约束

- benchmark 结果必须绑定：embedding provider、embedding model、LLM provider/model（如适用）
- CI 默认只跑**小样本 smoke benchmark**
- 全量 benchmark 放在 release 或手动流程中执行
- 首版优先采用 read-only / retrieval-centric 评测，避免强依赖 LLM judge

### 5.4 待定决策

- 是否同时承诺 LoCoMo / ConvoMem 全覆盖
- 跨供应商统一分数归一化方案
- 重度 LLM 裁判型 benchmark 是否作为默认门禁

---

## 6. P2: 写前审计日志（仅设计）

### 6.1 目标

为关键写操作提供 append-only 审计轨迹，回答"这条记忆怎么来的 / 谁触发了删除"等排查问题。

### 6.2 设计方向

新增 `audit_log` 表，记录高价值操作事件：

```sql
CREATE TABLE audit_log (
    id          TEXT PRIMARY KEY,
    operation   TEXT NOT NULL,    -- 'capture' | 'forget'
    target_table TEXT NOT NULL,   -- 'engrams' | 'capture_log'
    target_id   TEXT NOT NULL,
    origin      TEXT,             -- 'human' | 'agent'
    session_id  TEXT,
    content_hash TEXT,
    metadata    TEXT,             -- JSON
    created_at  TEXT NOT NULL
);
```

### 6.3 边界约束：与现有表的分工

`audit_log` 是**操作审计表**，不是 epoch 消费队列，也不替代任何 ledger：

| 表 | 定位 | 生命周期 |
|---|------|---------|
| `capture_log` | L2 候选缓冲 | epoch 消费后标记 disposition |
| `delta_ledger` | 数值变化账本 | epoch 消费后标记 epoch_id |
| `recon_buffer` | 再巩固上下文缓冲 | epoch 消费后标记 consumed |
| `session_events` | 会话事件 | 随 session 归档 |
| **`audit_log`** | **操作审计轨迹** | **append-only，不删除** |

### 6.4 导出/导入策略

- `audit_log` 默认**不进入**普通 memory export（`memento export`）
- 如需导出审计日志，通过 `memento export --include-audit` 显式指定
- import 默认**不支持** audit_log 回放——debug export 仅供排障用途，不保证 import round-trip

### 6.5 索引建议

```sql
CREATE INDEX idx_audit_created ON audit_log(created_at);
CREATE INDEX idx_audit_target ON audit_log(target_table, target_id, created_at);
CREATE INDEX idx_audit_session ON audit_log(session_id, created_at);
```

### 6.6 CLI / 查询方向

- 提供 `memento audit [--since DATE]`
- 支持按 target / operation / session 查询

### 6.7 暂不做

- observe / verify / pin 全覆盖
- 日志轮转/归档
- 用 audit_log 替代现有 ledger/event 表

---

## 7. P3: 多格式对话导入（仅设计）

### 7.1 目标

支持从 Claude Code 之外的对话来源导入历史对话，并复用现有 transcript extraction pipeline。

### 7.2 设计方向

新增 `normalize.py`，定义最小中间格式：

```python
@dataclass
class NormalizedMessage:
    role: str                      # "human" | "assistant"
    content: str
    timestamp: str | None = None
    metadata: dict | None = None   # 保留平台特定字段
```

首批格式 adapter：

| 格式 | 输入 | 说明 |
|------|------|------|
| `chatgpt` | `conversations.json` | ChatGPT 导出格式 |
| `text` | 任意纯文本 | 按段落切分，交替标注 role |
| `markdown` | `.md` 文件 | 按 heading/段落切分 |
| `auto` | 自动检测 | 按文件扩展名和内容特征判断 |

新增命令：

```bash
memento import-conversations <file> --format auto|chatgpt|text|markdown
```

### 7.3 与 transcript.py 的职责划分

- `normalize.py`：负责多格式输入归一化，将各平台原始格式转换为 `NormalizedMessage` 序列
- `transcript.py`：继续负责抽取前清洗/裁剪（去 code block、截断长行、限制消息数）与 extraction orchestration（LLM 调用、去重、写入 L2）

两者的边界是：normalize 产出干净的消息序列，transcript 消费并提取记忆。

### 7.4 边界约束

- 中间格式保持极小，不引入复杂平台特定字段
- 导入后统一走现有 transcript extraction pipeline
- 默认增量导入 + 去重
- 不做交互式审核

### 7.5 与[逐字存储补充层](#8-p3-逐字存储补充层仅设计)的依赖关系

`normalize.py` 的 `NormalizedMessage` 是 source_chunks 的前置基础。如果[逐字存储补充层](#8-p3-逐字存储补充层仅设计)想做得长期正确，最终会受本节 normalization 设计约束。因此本节优先级不低于逐字存储补充层。

### 7.6 暂不做

- Slack / Codex CLI / 飞书等长尾平台
- thread / attachment / reaction 级别归一化
- 导入后人工逐条确认工作流

---

## 8. P3: 逐字存储补充层（仅设计）

### 8.1 目标

为 LLM 提取出的长期记忆补充来源级 provenance，使用户可在 inspect 时回看触发该记忆的原始对话片段。

### 8.2 设计方向

- 为 engram 增加可选 `source_chunks` 字段（JSON 数组），保存原始消息片段
- `source_chunks` 默认不参与 recall，不在普通 priming 中返回
- inspect / debug / provenance 查询时展示

### 8.3 边界约束

- 首版优先采用 engram 内嵌 JSON 字段，不引入独立 chunk 表
- `source_chunks` 不做 embedding
- `source_chunks` 不参与 epoch reconsolidation
- 必须设置每条记忆的 chunk 数和字符数上限，防止存储膨胀

### 8.4 与多格式导入的依赖

本节依赖[多格式对话导入](#7-p3-多格式对话导入仅设计)的 `NormalizedMessage` 定义。建议在 normalization 层稳定后再实现。

**不阻塞前述交付**：source_chunks 的设计依赖 normalization 层，但不阻塞 P0/P1/P2 各实现项的交付。

### 8.5 暂不做

- 独立 chunk lifecycle
- chunk-level retrieval
- chunk 参与语义召回
- 自动压缩/重写 source_chunks

---

## 9. 迁移策略

### 9.1 数据库迁移

新增 `migrate_v05_to_v092()` 函数（幂等）：

```python
def migrate_v05_to_v092(conn: sqlite3.Connection) -> None:
    """v0.5 → v0.9.2 schema migration."""
    # 1. nexus 表增加 invalidated_at
    _ensure_column(conn, "nexus", "invalidated_at", "TEXT")
    
    # 2. view_nexus 增加 invalidated_at（重建视图表）
    # ... rebuild view_nexus with invalidated_at column
    
    conn.execute("PRAGMA user_version = 92")
    conn.commit()
```

### 9.2 配置迁移

无破坏性 DB 迁移。`config.json` 中已有 `embedding.provider` 的用户不受影响。仅影响无配置的全新安装。

需同步更新的测试契约：`tests/test_config.py` 中 `assert cfg["embedding"]["provider"] is None` 改为 `assert cfg["embedding"]["provider"] == "local"`。

---

## 10. 总结

### 10.1 实现项交付物

| 改进项 | 涉及文件数 | 核心风险 |
|--------|-----------|---------|
| 分层上下文注入 | 4 | 跨项目污染（已通过 project 过滤解决） |
| 本地嵌入优先 | 6 | 行为变更（已通过 doctor/文档/release note 同步解决） |
| 时序知识图谱增强 | 8 | 首轮 epoch 可能扫掉旧弱边（已通过保守阈值缓解） |

### 10.2 仅设计项实现建议顺序

1. **标准化基准**（P2）— 决定项目可信度
2. **写前审计日志**（P2）— 决定可追责性
3. **多格式对话导入**（P3）— 决定未来 ingestion 架构边界
4. **逐字存储补充层**（P3）— 依赖多格式导入的 normalization 层
