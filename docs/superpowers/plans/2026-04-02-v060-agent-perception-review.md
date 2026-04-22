> [!NOTE]
> **Historical Review / Plan Snapshot**
> This document captures a point-in-time review state. It may not reflect the latest repository-wide milestone semantics or final implementation state. For current source-of-truth, see `docs/README.md`, `Engram：分布式记忆操作系统与协作协议.md`, and `docs/superpowers/plans/2026-04-02-v06-v07-roadmap.md`.

# v0.6.0 检索修复 + Agent 感知增强 — Plan Review

> **审核对象:** `2026-04-02-v060-agent-perception.md`
> **审核日期:** 2026-04-02
> **审核状态:** 可继续，建议修订后再执行

---

## 总评

| 维度 | 评分 | 理由 |
|------|------|------|
| 完整性 | 7/10 | 目标和拆分合理，但缺前置核查与性能/异常说明 |
| 可执行性 | 7/10 | schema/签名基本对齐，能做 |
| 验证性 | 6/10 | fallback、FTS 异常、性能语义、测试命名诚实度不足 |
| 代码对齐度 | 7.5/10 | 主要字段与签名假设基本成立 |

**一句话总结：**

> 这份 plan 比初版评价的更贴近现有代码，说明作者确实做过实现层面的阅读；因此"代码对齐度不足"不是主要问题。真正的问题在于：测试命名不准确、fallback/异常路径验证不足、向量查询在 view_engrams 上的性能含义未交代，以及 staleness 分档虽有模型基础但缺少明确 rationale 和更克制的文案。

---

## 做得好的地方

1. **目标明确** — 修复 awake_recall 检索策略、增加 staleness_level、MCP capture 描述排除规则、recall 返回 tags/origin，范围合理，没有失控。
2. **任务拆分合理** — 先核心逻辑 (awake.py)，再接口层 (mcp_server.py)，再 E2E (smoke test)，顺序正确。
3. **有测试驱动意识** — 先补测试、再跑失败、再实现、再跑全量测试。
4. **关键设计决策提前显式化** — view_engrams 用 FTS join、capture_log 只做 vector + LIKE、staleness_level 分档规则等都提前交代。
5. **Schema 假设基本正确** — 经代码核查：view_engrams / capture_log 的字段、get_embedding 签名、effective_strength 参数签名均与 plan 描述一致。
6. **已有测试契约可复用** — 现有 test_awake.py 已覆盖 dual-source recall、provisional 区分、pulse 仅对 view hits 触发等基础行为，说明本次改动并非从零开始，新增测试主要应围绕 fallback、异常与新字段展开。

---

## 需要修正的问题

### 1. 测试命名不诚实（必改）

`test_recall_semantic_match_not_just_like` 中用 "cache" 匹配 "Redis cache config"，这是词汇重叠，不是语义匹配。

**修正方案（二选一）：**
- **A.** Mock embedding，断言 vector path 被采用并返回结果（测 retrieval path，不测真实语义）
- **B.** 改名为 `test_recall_returns_extended_fields` 或 `test_recall_uses_fallback_pipeline`

### 2. 缺关键 fallback / 异常路径测试（必改）

现有测试不覆盖以下场景，应至少补充：

- `VEC_AVAILABLE = False` 时 recall 仍可工作
- embedding pending / unavailable 时仍可工作
- FTS MATCH 特殊字符 query（如 `"`, `*`, `OR`, `NEAR`）不崩溃
- 最终 LIKE fallback 仍返回结果

### 3. vec_distance_cosine 在 view_engrams 上的性能语义需显式说明（必改）

plan 在 view_engrams 上直接执行 `vec_distance_cosine(v.embedding, ?)`，这大概率是逐行距离计算（全表扫描），而非走专门向量索引路径。功能正确，但性能假设未说明。

**建议在 plan 中补充：**
- 当前方案优先 correctness
- 在 view_engrams 上先采用 brute-force vector distance
- 若 recall 数据量上升，再评估专门向量索引方案

### 4. FTS5 MATCH query 未做 sanitize（建议改）

FTS5 MATCH 对特殊字符和操作符敏感，当前方案沿用了现有 silent fallback 的风格，因此这不是本 plan 新引入的风险；但 plan 应明确把该行为视为已知限制，至少补充异常路径测试，并说明后续可考虑 query escaping 或更可观测的错误记录。

### 5. staleness_level 阈值缺显式 rationale（建议改）

阈值 fresh > 0.6 / stale 0.3–0.6 / very_stale ≤ 0.3 有 FSRS v6 decay + rigidity 模型基础，不离谱，但 plan 未说明推导依据。

**建议补充：**
- 这是基于当前 decay/rigidity 模型的启发式阈值（初版）
- 后续可按实际 recall 分布调整

### 6. staleness 文案太重（建议改）

- `⚠️过时风险` → 建议改为 `⚠️较旧`
- `❌可能已失效` → 建议改为 `⏳可能过时`

heuristic 标签不应包装成事实判断，避免 agent 误把"低分"当"错误"。

### 7. commit 步骤写进 plan（风格建议）

每个 Task 末尾的 git commit 步骤应移除，改成文末统一说明：

> 完成全部任务并验证通过后，按仓库约定提交 1–3 个 commits。

---

## 建议的补强方向

> 不要求完全重写，只建议按以下结构补齐缺失项。

```
Task 1 开始前：补一个短的 baseline checklist
- 核对 view_engrams / capture_log 当前字段
- 核对 vector path 的性能特征
- 核对测试基线与已有断言

Task 1: awake_recall retrieval upgrade
- 保持 vector → FTS5 → LIKE fallback 顺序
- 补 staleness_level（含 rationale 说明）
- 返回 tags/origin
- 覆盖 vector unavailable / FTS unavailable / LIKE fallback 测试
- 测试命名准确反映验证内容

Task 2: MCP response and prompt updates
- capture 描述补 exclusion rules
- recall schema 暴露 staleness_level / tags / origin
- prime prompt 展示 staleness marker（文案中性化）

Task 3: Regression + smoke verification
- update smoke test
- run targeted tests
- run full suite
- verify compatibility
```
