# v0.9 Conversation Memory Extraction 设计文档

## 概述

为 Memento 增加一条基于 Stop hook 和 `transcript_path` 的 conversation-memory extraction 管线，在会话进行中持续生成高价值记忆候选，并通过现有 `capture_log → epoch → engram` 架构完成去重、信任控制和长期巩固。

**定位**：从 event ingestion（工具事件记录）升级到 conversation memory extraction（对话结论提炼）。

## 问题陈述

### 现状

当前自动采集的主要对象是**工具事件**（PostToolUse → observe）：

- "读了哪个文件"
- "执行了什么命令"
- "某个工具返回了什么"

这些信息对追踪 Agent 行为有帮助，但对跨会话知识积累来说太低级。

Agent 主动 capture 的记忆也存在问题：
- 太碎：调试修复记录、代码审核细节
- 太长：一条记忆塞了过多技术细节
- 不精炼：过程记录而非结论提炼

### 期望

根据用户和 Agent 的聊天内容，系统自动提取具有长期价值的精炼记忆：
- 在对话进行过程中不断完善，不依赖会话结束一次性总结
- 不依赖 Agent 手动调 `memento capture`
- 只记结论层信息，过滤过程层噪音

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 触发入口 | Stop hook（每次 Agent 回复后） | 自然的交互停顿点，不阻塞对话 |
| 数据源 | `transcript_path`（hook 输入中自带） | 包含完整对话内容，比 tool event 信息量高一个数量级 |
| 写入目标 | `capture_log`（L2 buffer） | 复用现有 `capture_log → epoch → engram` 主链，不新建表 |
| 不直接写 engram | 是 | 保持分层：Awake 快速写 buffer，Epoch 重 consolidation |
| P1 不新建 memory_candidates 表 | 是 | capture_log 已具备 candidate 语义（disposition/dedup/epoch consume），避免并行 pipeline 冲突 |
| 执行位置 | Worker 内部（hook 只投递，不做重逻辑） | hook 保持轻量，Worker 内可控重试/降级 |
| LLM 选择 | 便宜快速模型（Gemini Flash / Haiku / DeepSeek） | 提炼任务不需要最强推理，需要快和便宜 |

## 架构

### 数据流

```
Stop hook 触发
    │
    ▼
hook-handler.sh
  ├─ 取 transcript_path + session_id + timestamp
  ├─ 发送到 Worker: POST /transcript/extract
  └─ 异步返回，不阻塞
    │
    ▼
Worker: /transcript/extract
  ├─ 节流检查（上次提取 < 5 分钟 → skip）
  ├─ 读取 transcript 增量（last_processed_offset → 当前末尾）
  ├─ 净化 transcript（剔除代码块、工具输出、长日志）
  ├─ 拉取现有核心记忆摘要（origin=human + importance>=high，20-30 条）
  ├─ 调用 LLM 提取 durable memories（强制 JSON 输出）
  ├─ 对结果做 candidate disposition：
  │   ├─ duplicate → suppress（content_hash 或语义匹配已有记忆）
  │   ├─ reinforce → merge/boost candidate importance
  │   └─ new → 写入 capture_log
  └─ 更新 last_processed_offset
    │
    ▼
Epoch Phase 2（现有流程）
  ├─ 扫描 capture_log 未消费项
  ├─ LLM structuring
  └─ promote / drop / defer to debt
```

### 与现有体系的分工

| 层 | 职责 | 存储 |
|------|------|------|
| `session_events` | 事件流（observation/start/end） | 发生了什么 |
| `capture_log` | L2 candidate buffer（含 transcript candidate） | 哪些内容被判定为候选记忆 |
| `engrams` | 长期记忆 | 哪些候选最终被巩固 |

## Stop Hook 改造

### hook-handler.sh 改造 flush-and-epoch 分支

当前 Stop hook 映射到 `flush-and-epoch`（不是 `flush`）。在原有 flush + epoch 节流逻辑之间，插入 transcript extraction 投递。

```bash
flush-and-epoch)
    # 1. Flush（原有逻辑不变）
    send_to_worker POST /flush "$PAYLOAD"

    # 2. 新增：投递 transcript extraction（异步，不阻塞后续 epoch 判断）
    EXTRACT_PAYLOAD=$(echo "$HOOK_INPUT" | python3 -c "
    import json, sys
    d = json.load(sys.stdin)
    print(json.dumps({
        'claude_session_id': d.get('session_id', 'default'),
        'transcript_path': d.get('transcript_path', ''),
        'timestamp': d.get('timestamp', ''),
    }))
    " 2>/dev/null)
    send_to_worker POST /transcript/extract "$EXTRACT_PAYLOAD" &

    # 3. 原有 epoch 节流判断（不变）
    ...
    ;;
```

**关键约束**：
- hook 只投递，不在 shell 做 transcript 解析或 LLM 调用
- transcript extraction 失败不得影响现有 flush-and-epoch 主流程

## Worker 新增路由

### `POST /transcript/extract`

**Session ID 映射**：hook 传入的是 `claude_session_id`（Claude Code 外部 ID）。Worker 内部通过 `session_registry` 查找对应的 `memento_session_id`（Memento 内部 ID）。transcript extraction 的游标、去重、capture 写入均绑定 `memento_session_id`，不使用 Claude 外部 ID。

```python
@app.route("/transcript/extract", methods=["POST"])
def transcript_extract(body):
    transcript_path = body.get("transcript_path", "")
    claude_session_id = body.get("claude_session_id", "")

    if not transcript_path or not Path(transcript_path).exists():
        return {"status": "skipped", "reason": "no_transcript"}

    # 映射 claude_session_id → memento_session_id
    memento_session_id = session_registry.get(claude_session_id)
    if not memento_session_id:
        return {"status": "skipped", "reason": "no_session"}

    # 节流：5 分钟冷却（基于 memento_session_id）
    if not _should_extract(memento_session_id):
        return {"status": "skipped", "reason": "cooldown"}

    # 后台异步执行（不阻塞 hook 响应）
    threading.Thread(
        target=_do_transcript_extract,
        args=(transcript_path, memento_session_id),
        daemon=True,
    ).start()

    return {"status": "accepted"}
```

## Transcript 增量处理

### 游标机制

使用现有 `runtime_cursors` 表持久化游标（`src/memento/migration.py:142-146`），同时在内存中缓存以加速。Worker 重启后从 DB 恢复，不会从 transcript 起点重复扫描。

```python
# 内存缓存（加速，DB 为真）
_extract_cursors_cache: dict[str, int] = {}

CURSOR_KEY_PREFIX = "transcript_extract:"

def _get_cursor(conn: sqlite3.Connection, memento_session_id: str) -> int:
    """从 runtime_cursors 读取游标，内存缓存优先"""
    key = CURSOR_KEY_PREFIX + memento_session_id
    if key in _extract_cursors_cache:
        return _extract_cursors_cache[key]
    row = conn.execute(
        "SELECT value FROM runtime_cursors WHERE key = ?", (key,)
    ).fetchone()
    offset = int(row["value"]) if row else 0
    _extract_cursors_cache[key] = offset
    return offset

def _set_cursor(conn: sqlite3.Connection, memento_session_id: str, offset: int):
    """持久化游标到 runtime_cursors"""
    key = CURSOR_KEY_PREFIX + memento_session_id
    conn.execute(
        "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) VALUES (?, ?, ?)",
        (key, str(offset), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    _extract_cursors_cache[key] = offset

def _read_transcript_delta(
    conn: sqlite3.Connection,
    transcript_path: str,
    memento_session_id: str,
) -> list[dict]:
    """读取上次处理位置之后的新增对话。
    
    transcript parser 容忍格式漂移：读取失败的行 skip，不影响主流程。
    """
    last_offset = _get_cursor(conn, memento_session_id)
    messages = []
    current_line = 0

    with open(transcript_path) as f:
        for line in f:
            current_line += 1
            if current_line <= last_offset:
                continue
            try:
                entry = json.loads(line)
                msg = entry.get("message", {})
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            except (json.JSONDecodeError, KeyError):
                continue  # skip malformed lines

    _set_cursor(conn, memento_session_id, current_line)
    return messages
```

### 窗口控制

即使有增量游标，单次提取也限制最多处理**最近 10 轮对话**（约 5 个 user-assistant 来回），避免 token 爆炸。

## Transcript 净化

传 LLM 前必须清洗，剔除低价值高 token 内容：

```python
def _clean_transcript(messages: list[dict]) -> str:
    """净化 transcript：剔除代码块、工具输出、长日志"""
    cleaned = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        # assistant 消息：提取纯文本 block，跳过 tool_use
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block["text"])
            content = "\n".join(texts)

        # user 消息：提取纯文本（跳过 tool_result）
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, str):
                    texts.append(block)
            content = "\n".join(texts)

        if not isinstance(content, str) or not content.strip():
            continue

        # 剔除代码块
        content = re.sub(r'```[\s\S]*?```', '[代码块已省略]', content)
        # 剔除超长行（通常是工具输出/日志）
        lines = content.split('\n')
        lines = [l for l in lines if len(l) < 500]
        content = '\n'.join(lines)
        # 截断单条消息
        if len(content) > 800:
            content = content[:800] + '...'

        cleaned.append(f"[{role}]: {content}")

    return "\n\n".join(cleaned)
```

## LLM 提取 Prompt

### 强制 JSON 结构化输出

```python
TRANSCRIPT_EXTRACTION_PROMPT = """你是一个记忆提炼专家。分析以下最近的对话，提取具有长期跨会话价值的信息。

## 只提取这些类型
- preference：用户偏好、习惯、工作方式要求
- convention：项目约定、规范、必须遵守的规则
- decision：架构决策、技术路径选择及其理由
- fact：重要的技术事实、项目背景、外部约束

## 必须过滤掉
- 工具执行过程（读了什么文件、运行了什么命令）
- 一次性调试步骤和排错细节
- 具体代码实现和文件路径
- 临时任务状态和进度
- 局部 code review 意见

## 已有记忆（避免重复）
{existing_memories}

## 最近对话
{transcript}

## 输出规则
- 每条记忆精炼为一句话，不超过 100 字
- 如果没有任何值得记录的新信息，返回空数组 []
- 宁可漏记，不可记垃圾

请返回 JSON 数组：
[
  {{
    "content": "精炼的一句话结论",
    "type": "preference|convention|decision|fact",
    "importance": "normal|high|critical"
  }}
]

只返回 JSON，不要其他文字。"""
```

## 已有记忆注入

轻量化：在 `transcript.py` 内部直接查 `view_engrams`，不暴露新的公开 API。控制在 20-30 条以内。

```python
def _get_existing_memory_summary(conn: sqlite3.Connection) -> str:
    """从 view_engrams 拉取核心记忆摘要，用于 prompt 去重注入。
    
    这是 transcript.py 的内部 helper，不经过 LocalAPI。
    只查 consolidated 状态、非 forgotten、按 strength 降序取 top 30。
    """
    try:
        rows = conn.execute(
            """SELECT type, content FROM view_engrams
               WHERE forgotten = 0
               ORDER BY strength DESC
               LIMIT 30"""
        ).fetchall()
    except Exception:
        return "（暂无已有记忆）"

    if not rows:
        return "（暂无已有记忆）"

    lines = []
    for r in rows:
        lines.append(f"- [{r['type']}] {r['content'][:80]}")
    return "\n".join(lines)
```

**注意**：这里直接查 `view_engrams` 而不是 `engrams`，因为 `view_engrams` 是 epoch 物化后的只读快照，包含最新的 strength 值，且不会和 Worker 的写路径冲突。

## 节流策略

```python
_last_extract_time: dict[str, float] = {}  # session_id → timestamp
EXTRACT_COOLDOWN = 300  # 5 分钟

def _should_extract(session_id: str) -> bool:
    last = _last_extract_time.get(session_id, 0)
    now = time.time()
    if now - last < EXTRACT_COOLDOWN:
        return False
    _last_extract_time[session_id] = now
    return True
```

## Candidate Disposition（P1 在 capture_log 内表达）

P1 不新建表，用 `capture_log` 的现有字段 + metadata 表达 candidate 语义：

| 字段 | 用途 |
|------|------|
| `origin` | 固定为 `agent` |
| `source_session_id` | 当前 session |
| `content_hash` | 精确去重 |
| `importance` | LLM 输出的重要性 |
| `type` | LLM 输出的类型（preference/convention/decision/fact） |
| `tags` | 包含 `transcript-extracted` 标记，区分来源 |

### 去重逻辑

P1 以 **content_hash + prompt 注入已有记忆摘要** 为主要去重手段，向量语义去重作为 best-effort 补充，不作为强依赖。

1. **精确去重（主）**：`content_hash` 匹配 capture_log 或 engrams 中已有条目 → skip
2. **Prompt 去重（主）**：LLM 提取时已注入已有记忆摘要，prompt 明确指示"不要输出重复内容"
3. **语义去重（辅助，best-effort）**：若 embedding 可用，与已有记忆做向量相似度比对（复用 `observation.py` 中 `_check_semantic_candidate` 的思路，阈值参考现有经验值 0.85）；若 embedding 不可用，退化为仅精确去重 + prompt 去重
4. **同 session 去重**：同 session 内已提取过相同 content_hash → skip

### P1 的 reinforce / revise / duplicate 语义

先作为 candidate disposition，**不做即时 engram mutation**。P1 的所有操作只发生在 candidate 层（capture_log），不直接修改已有 engram 的 strength、content 或 state。

- **duplicate** → suppress candidate，不写入 capture_log
- **reinforce** → 可写入 capture_log 作为额外支持证据；P1 不直接改已有 engram 的 strength
- **revise** → 写入新的 transcript-derived capture，标记为"对已有记忆的候选修订"（tags 中包含 `transcript-revision`）；**P1 不承诺直接替换已有 engram**，最终是否合并/替换由 epoch Phase 2 structuring 或未来 Phase 5 reconsolidation 决定

最终 promote/suppress 仍交给现有 epoch 主链。真正的"更新已有 engram 内容"属于 Phase 5 reconsolidation 的职责范围，不在 P1 transcript extraction 中实现。

## 过滤策略

### 只允许 durable 类型

默认只产出：preference、convention、decision、fact

不产出：debugging、insight
- debugging 容易把临时修复过程记成长期知识
- insight 太宽泛，容易变成垃圾桶

### 必须 suppress 的内容

- 工具过程和执行回显
- 一次性计划和临时报错
- 局部调试细节
- 文件搜索/读写过程
- 代码实现细节

**原则：宁可漏，不可脏。**

## observe 与现有 pipeline 的关系

P1 **不调整** observation 现有语义。PostToolUse → observe 管线保持原样运行。

conversation extraction 上线后，observe 自然会成为低价值的短期上下文层，而 transcript extraction 产出高价值的结论层记忆。两者并行，互不干扰。

是否需要显式削弱 observation 的 importance / epoch 权重，留待 conversation extraction 稳定运行后再观察决定。

## 信任模型

完全复用现有机制：
- transcript 提取的记忆固定 `origin='agent'`
- 强度上限 0.5（未验证）
- 用户可通过 `memento verify <id>` 解除限制

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `plugin/scripts/hook-handler.sh` | 修改 | `flush-and-epoch` 分支新增 transcript extraction 投递 |
| `src/memento/scripts/hook-handler.sh` | 同步修改 | 与 plugin 版本保持一致 |
| `src/memento/worker.py` | 修改 | 新增 `/transcript/extract` 路由 |
| `src/memento/transcript.py` | 新增 | transcript 解析、净化、增量处理、LLM 提取、去重、记忆摘要注入 |
| `src/memento/prompts.py` | 修改 | 新增 `build_transcript_extraction_prompt()` |
| `tests/test_transcript.py` | 新增 | transcript 解析、净化、提取逻辑测试 |

## 落地顺序

1. transcript 解析与净化（读取 JSONL、增量游标、内容清洗）
2. LLM 提取 prompt + JSON 解析
3. Worker `/transcript/extract` 路由 + 节流
4. hook-handler.sh `flush-and-epoch` 分支改造
5. 去重逻辑（content_hash + 语义 + 同 session）
6. 测试和集成验证

## 验收标准

- [ ] Stop hook 触发后，Worker 能读取 transcript 增量
- [ ] 对话中有用户偏好/决策时，自动生成精炼的 capture（<100 字）
- [ ] 对话中只有工具操作时，不产生新 capture
- [ ] 5 分钟内重复触发不会重复提取
- [ ] 已有记忆不会被重复 capture
- [ ] 提取结果 origin=agent，走正常信任模型
- [ ] 不阻塞对话（异步执行）
- [ ] LLM 不可用时优雅降级（skip，不报错）
- [ ] Worker 重启后，不会从 transcript 起点重复提取同一 session 的历史内容
- [ ] transcript extraction 失败不会影响现有 flush-and-epoch 主流程

## 不在 P1 范围内

- 独立 memory_candidates 表（P2：当会话内修订频繁时再引入）
- 即时 engram mutation（reinforce/revise 直接改长期记忆）
- 与 reconsolidation / rigidity / delta 机制深度整合（P3）
- 候选生命周期可视化（Dashboard 扩展）
- 多模型路由（根据对话复杂度选择不同 LLM）
