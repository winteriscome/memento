# 借鉴 Claude Code 记忆系统的启发与行动项

> 分析来源：[claude-code-source-code](https://github.com/winteriscome/claude-code-source-code)（v2.1.88 反编译源码）
> 分析日期：2026-04-02

---

## 两个系统的本质差异

Claude Code 和 Memento 代表两种不同的记忆哲学：

| 维度 | Claude Code | Memento |
|------|------------|---------|
| 存储 | Markdown 文件 + JSONL | SQLite（engrams + nexus + capture_log） |
| 检索 | Sonnet LLM 做语义选择 | 向量相似度（sqlite-vec）+ FTS5 |
| 记忆类型 | user / feedback / project / reference | fact / decision / insight / convention / debugging / preference |
| 衰减 | 手动 staleness warning（>1 天就警告） | FSRS v6 自动衰减 + 半衰期 |
| 关联图谱 | 无 | Nexus 图谱 + Hebbian 学习 |
| 整合 | KAIROS：人工夜间蒸馏日志 | 三轨 + 7 阶段 Epoch 自动整合 |
| 信任模型 | 无区分（all equal） | origin-based（human > agent，cap 0.5） |
| 可读性 | 极高（人可直接编辑 .md 文件） | 低（SQL，需要 CLI 操作） |

---

## 值得借鉴的四个点

### 1. LLM 语义选择作为 Reranker（高优先级）

**Claude Code 的做法**（`findRelevantMemories.ts`）：

不用向量搜索，而是让 Sonnet 读所有记忆的 manifest（filename + description 列表），挑出最相关的 5 条。这是"LLM 做 reranker"的思路。

```typescript
selectRelevantMemories(query, memories, signal, recentTools)
// Input:  query + 所有 memory 的 frontmatter manifest
// Output: 最相关的 5 个 filename
```

**Memento 的盲区**：`awake_recall()` 是纯数学（向量余弦 + FTS5 关键词），对"语义相关但措辞不同"这类情况有盲区。

**行动项**：在 Epoch full mode 里，recall 结果上加可选的 LLM rerank 步骤。LLM 只做增强（reranker），不做主检索——主检索必须保持 ms 级延迟。

---

### 2. Staleness Warning 对 Agent 可见（高优先级）

**Claude Code 的做法**（`memoryAge.ts`）：

记忆超过 1 天，自动在内容末尾追加警告：

> "Memories are point-in-time observations, not live state. Verify against current code before asserting as fact."

**Memento 的盲区**：有 `effective_strength = strength × decay` 内部衰减，但 recall 返回给 agent 的结果没有任何"这条记忆可能已过时"的信号。Agent 无法区分一条新鲜记忆和一条衰减了 90% 的旧记忆。

**行动项**：`awake_recall()` 返回值和 `memento_recall` MCP tool 的 response schema 里加 `staleness_level` 字段：

```python
# 基于 effective_strength 和 last_accessed 计算
staleness_level: "fresh" | "stale" | "very_stale"
# fresh:     effective_strength > 0.6
# stale:     0.3 < effective_strength <= 0.6
# very_stale: effective_strength <= 0.3
```

已有 `provisional` 字段是同类机制，这是自然扩展。

---

### 3. Capture Exclusion Rules（高优先级，改动极小）

**Claude Code 的做法**（`memoryTypes.ts` system prompt）：

明确告诉 agent **什么不应该写进记忆**：

- ❌ 代码结构、架构、文件路径（可以从 codebase 推导）
- ❌ Git 历史（用 `git log` 即可）
- ❌ 调试方案（修复已在代码里体现）
- ❌ CLAUDE.md / AGENTS.md 里已有的内容
- ❌ 临时任务状态（当前 session 结束即失效）

**Memento 的盲区**：`observation.py` 有 promotion gates（高重要性、跨会话才促进），但 agent 主动调用 `memento_capture` 时没有任何过滤或写入指导，噪音完全依赖 agent 自己判断。

**行动项**：在 `mcp_server.py` 的 `memento_capture` tool description 里加 exclusion guidance（改动极小，纯文档变更）。同时在 `memento_prime` prompt 里加"what NOT to capture"指导。

---

### 4. Daily Digest Resource（中优先级）

**Claude Code 的做法**（KAIROS 模式）：

每天追加写入日志文件（`logs/YYYY/MM/YYYY-MM-DD.md`），只追加不修改，夜间蒸馏为 MEMORY.md 摘要。这是一个**只追加的事件流** + 定期摘要的模式。

**Memento 的盲区**：有 `session_events` 表和 `capture_log`，但这些是面向内部处理的。没有面向 agent 的"今天发生了什么"时序视图。`priming_memories` 是跨时间的语义检索，不是时序回顾。

**行动项**：新增 `memento://daily/today` MCP Resource，读取当天的 session_events + captures，按时间排列，让 agent 在 session start 时快速回顾当天上下文。

---

## 补充借鉴点

### 5. 后台 Fork 提取——零成本自动采集（中优先级）

**Claude Code 的做法**（`extractMemories.ts`）：

每次模型完成回复后，自动 fork 一个子代理分析最近对话，提取值得持久化的记忆。关键技术点：

- `runForkedAgent` 共享主对话的 prompt cache，几乎零额外 token 消耗
- 有频率控制（`turnsSinceLastExtraction`），可配置每 N 轮提取一次
- **互斥逻辑**：如果主代理已经在这批消息中写了记忆（`hasMemoryWritesSince`），则跳过后台提取，避免重复

**Memento 的现状**：完全依赖 prompt 指导 agent 主动调用 `memento capture`，采集质量取决于 agent 的"自觉性"。

**行动项**：考虑提供 `memento watch` 命令或 session hook，在会话结束时自动分析 transcript 并调用 capture。互斥逻辑值得直接借鉴——如果 agent 在会话中已主动 capture，则跳过自动采集。

---

### 6. Team Memory 作用域与安全防护（低优先级）

**Claude Code 的做法**（`teamMemPaths.ts`）：

支持团队共享记忆目录（`memory/team/`），跨用户同步。安全防护包括：
- 路径遍历检测（防止 `../../` 逃逸）
- Symlink 解析验证（确保链接不指向记忆目录外）
- 空字节注入防护

**Memento 的现状**：单用户、单作用域，无多人协作支持。

**行动项**：如果未来 Memento 考虑多用户/团队场景，可引入 `--scope project|user|team` 参数。Team scope 的记忆需要额外的安全校验层，Claude Code 的 `teamMemPaths.ts` 是可参考的实现。

---

## 两个核心差异——不应该学

### 1. 文件存储 vs SQLite

Claude Code 的 Markdown 文件存储有明显短板：
- 无法做向量搜索
- 无法自动衰减
- 无法追踪 `access_count` 和 co-activation
- 200 个文件就需要 LLM 帮选，本质上是用 LLM 弥补检索能力不足

Memento 的 SQLite + sqlite-vec + FTS5 + Nexus 图谱是正确的架构方向。技术复杂度是值得的，不是过度设计。**不要向文件系统退化。**

### 2. LLM 作为主检索 vs 作为 Reranker

Claude Code 的 LLM-based recall 有致命缺陷：需要 LLM 在线、有延迟、有 token 消耗。Memento 的 `awake_recall` 是 ms 级的，这是关键优势。

**LLM 只能做 reranker（增强），不能做主检索。**

---

## 行动项优先级汇总

| 优先级 | 借鉴点 | 实现位置 | 复杂度 |
|--------|--------|----------|--------|
| 🔴 高 | recall 结果加 `staleness_level` 字段 | `awake.py` 返回值 + `mcp_server.py` schema | 小 |
| 🔴 高 | `memento_capture` tool description 加 exclusion rules | `mcp_server.py` list_tools | 极小 |
| 🟡 中 | `memento://daily/today` resource（当天事件流） | `mcp_server.py` resources + `api.py` | 中 |
| 🟢 低 | Epoch full mode 加 LLM recall reranker | `epoch.py` + `awake.py` | 大 |
| 🟢 低 | 后台自动采集 hook（含互斥逻辑） | 新增 `watch` 命令或 session hook | 大 |
| 🟢 低 | Team Memory 作用域 + 安全防护 | `api.py` + `mcp_server.py` | 大 |

---

## Claude Code 记忆系统关键文件索引

> 除上文已引用的文件外，以下两个文件与补充借鉴点直接相关：

```
src/services/extractMemories/
    └── extractMemories.ts     # 后台 Fork 提取（runForkedAgent + 互斥逻辑）
src/memdir/
    └── teamMemPaths.ts        # Team memory 路径解析 + 安全防护（遍历/symlink/空字节）
```

### 完整索引

```
src/
├── memdir/
│   ├── memdir.ts               # 主记忆 prompt 构建
│   ├── findRelevantMemories.ts # LLM 语义选择（Sonnet reranker）
│   ├── memoryScan.ts           # 扫描 .md 文件，解析 frontmatter
│   ├── memoryTypes.ts          # 类型分类 + exclusion rules prompt
│   ├── paths.ts                # 目录解析逻辑
│   ├── memoryAge.ts            # Staleness 计算与警告
│   ├── teamMemPaths.ts         # Team memory 路径 + 安全防护
│   └── teamMemPrompts.ts       # Team memory prompt 构建
├── utils/
│   ├── memory/types.ts         # MemoryType enum
│   ├── sessionStorage.ts       # JSONL transcript 存储
│   └── history.ts              # 全局 prompt 历史
└── commands/memory/
    └── memory.tsx              # /memory 命令 UI
```
