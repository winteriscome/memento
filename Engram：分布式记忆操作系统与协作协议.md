# Engram：分布式记忆操作系统与协作协议

## 完整系统设计文档

### 阅读导引

本文档包含从 MVP 到远期愿景的完整设计。系统分四个阶段演进：

| 阶段 | 目标 | 核心交付 | 状态 | 详情 |
| ---- | ---- | -------- | ---- | ---- |
| **v0.1** | 极简验证：衰减+强化 vs 纯向量搜索 | `capture` / `recall` / `export` CLI | ✅ 已完成 | Ch23.2 |
| **v0.2** | Agent-Runtime 集成层 | Session Lifecycle、统一 Memory API（7 工具）、Observation Pipeline | ✅ 已完成 | Ch23.2.1 |
| **v0.3** | Runtime 集成闭环 | MCP Server、Plugin + Hooks 自动注册、Worker Service（异步 Observation） | ✅ 已完成 | Ch23.2.2 |
| **v0.5** | 三轨架构重写 | 三轨节律、CQRS、五态状态机、Delta Ledger、Rigidity 衰减、Subconscious 硬化 | ✅ 已完成 | Ch23.3 |
| **v0.5.1** | E2E 集成 + 打包 | Worker 修复、集成测试、`memento plugin install claude`、Entry Points | ✅ 已完成 | — |
| **v0.6.0** | 检索修复 + Agent 感知增强 | awake_recall 向量/FTS5 检索、staleness_level、capture exclusion rules、memento_prime 增强 | ✅ 已完成 | Ch23.3.1 |
| **v0.6.1** | 摄取安全网 + 自动摘要兜底 | session_end 自动摘要兜底、auto_captures_count、`memento://daily/today` 资源 | ✅ 已完成 | Ch23.3.2 |
| **v0.7.0** | LLM 管线 + Epoch 智能化 | Phase 2 L2→L3 结构化、Phase 5 再巩固、Epoch light 自动触发、T5 抽象化 | ✅ 已完成 | Ch23.3.3 |
| **v0.8.0** | Web Dashboard | 本地 Web Dashboard（FastAPI + Vue 3）、12 REST API 端点、记忆/会话/系统三视图 | ✅ 已完成 | Ch23.3.4 |
| **v0.9.0** | Conversation Memory Extraction | Stop hook + transcript 增量提炼、LLM 自动提取对话中的高价值记忆 | ✅ 已完成 | Ch23.3.5 |
| **v0.9.2** | MemPalace-Inspired Enhancements | 分层上下文注入（L0/L1/L2）、本地嵌入优先、时序 Nexus 生命周期 | 🚧 进行中 | Spec: `docs/superpowers/specs/2026-04-10-v092-mempalace-inspired-enhancements-design.md` |
| **v1.0** | 联邦同步 | EFP 协议、跨实例身份、混合检索 | 📋 远期 | Ch23.3 |

不同读者应关注不同章节：

| 读者身份         | 必读                                       | 选读                                | 跳过                     |
| ------------ | ---------------------------------------- | --------------------------------- | ---------------------- |
| **v0.6 实现者** | Ch12-14（三轨/CQRS/状态机）, Ch17（工程约束）, Ch20.5-20.6（Session/Agent 接入层）, Ch23.3.1-23.3.2（v0.6.0/v0.6.1 设计） | Ch15（API） | Ch6-10（社交/联邦）, Ch21 |
| **v0.7 实现者** | Ch20.5-20.6（Agent 接入层）, Ch23.3.3（v0.7.0 设计） | Ch12-14（三轨架构）, Ch18（冷启动） | Ch6-10, Ch21 |
| **v0.9 实现者** | Ch23.3.5（v0.9 Conversation Memory Extraction）, Spec: `docs/superpowers/specs/2026-04-10-v092-mempalace-inspired-enhancements-design.md`（v0.9.2 MemPalace 增强）, Ch12（三轨节律 — Stop hook / priming 定位） | Ch20.5-20.6（Agent 接入层）, Ch23.3.3（Epoch/LLM 管线） | Ch6-10, Ch21 |
| **全栈理解**     | 全文                                       | —                                 | —                      |

> v0.1–v0.5 阶段已全部完成，上述旧版阅读导引（v0.1/v0.2/v0.3/v0.5 实现者）仅保留供历史参考。

Ch6（协作网络）、Ch9（集体智能）、Ch10（联邦架构）、Ch21（EFP 协议）属于 v0.5/v1.0 远期设计，与首要用户（AI Agent 开发者）的核心需求无直接关系。这些章节保留在文档中是为了保持愿景完整性，但**不应影响 v0.1/v0.2 的设计决策和优先级**。

> **3.14-3.16 节**（OperationLog / Operation / ReplayReport）是对 3.7 MemoryPR 的架构修正，解决跨 Projection 的有损投影图合并问题。v0.5 实现 Fork/PR/Merge 时的必读章节。

***

## 第一章：设计哲学

### 三个根基

1.  **记忆是活的**
    记忆不是档案，是不断被重塑的活体组织。每次接触都改变它，不接触它就消亡。

2.  **认知是可共享的**
    人类文明本质上就是记忆的 fork 和 merge。书籍是只读 fork，教育是有损 fork，协作是持续 merge。

3.  **遗忘是特性，不是缺陷**
    无限记忆 = 无法决策（博尔赫斯《博闻强记的富内斯》）。选择性遗忘是智能的核心能力。

### 系统定位与边界

**Engram 是什么**：个人和 AI Agent 的长期记忆引擎——解决"跨会话、跨项目的知识积累和检索"问题。核心价值主张是**自动降权过时信息、自动提权常用信息**，让检索结果的信噪比随使用自然提升。

**Engram 不是什么**：

*   **不是通用知识库**（不替代 Obsidian/Notion——用户仍需要确定性的文档管理工具）
*   **不是社交网络**（社交层是可选的扩展能力，不是核心价值）
*   **不是共识系统**（不追求"所有人看到同一个真相"，只保证个人 Vault 内一致）


**首要用户**：使用 AI Agent（Claude Code / Codex / Gemini CLI）的开发者，需要 Agent 跨会话记住项目知识和用户偏好。其他场景（个人知识管理、团队协作、联邦共享）按 v0.5/v1.0 路线图逐步覆盖，但核心引擎的设计不以这些场景为优先。

**核心赌注与风险**：本系统的全部设计建立在一个核心假设上——**衰减 + 强化是否比纯向量搜索 + 时间排序更好？** v0.1 已验证该假设成立。v0.5.1 已交付完整的三轨架构、E2E 集成和 Plugin 打包。当前处于 v0.9.2 阶段，已完成对话记忆提炼、分层上下文注入（L0/L1/L2）、本地嵌入优先以及时序 Nexus 生命周期增强，重点转向让记忆系统更稳定、更可解释，并为后续基准、审计与多格式导入打基础。

### 与现有系统的本质区别

| 维度   | 传统知识库 | Git     | 社交网络  | **Engram**        |
| ---- | ----- | ------- | ----- | ----------------- |
| 数据模型 | 文档/条目 | 文件树     | 帖子/消息 | **活性记忆单元**        |
| 读操作  | 无副作用  | 无副作用    | 无副作用  | **读触发异步元数据更新**    |
| 时间观  | 永久保存  | 永久历史    | 时间流   | **自然衰减 + 强化**     |
| 版本   | 覆盖/追加 | 完整历史    | 无版本   | **衰减的版本历史**       |
| 社交   | 共享链接  | Fork/PR | 关注/转发 | **认知 Fork/Merge** |
| 删除   | 人工删除  | 人工删除    | 人工删除  | **自动遗忘**          |

***

## 第二章：核心概念词典

| 概念                | 说明                                           | 类比                |
| ----------------- | -------------------------------------------- | ----------------- |
| **Engram (印记)**   | 记忆的最小单元，具有强度、情绪、类型、关联                        | 神经元集群形成的一个记忆痕迹    |
| **Vault (记忆库)**   | 一个主体的完整记忆空间，包含所有 Engram 及其关联网络               | 一个人的全部记忆 / 一个代码仓库 |
| **Nexus (突触)**    | Engram 之间的关联连接，有方向、类型、强度                     | 突触连接 / 知识图谱的边     |
| **Pulse (脉冲)**    | 一次记忆的激活事件（编码/回忆/强化）                          | 神经脉冲 / 版本控制的每次操作  |
| **Epoch (纪元)**    | 一个完整的记忆整合周期（类似一次睡眠），产出一个 Snapshot + 衰减 + 抽象化 | 睡眠整合周期            |
| **Snapshot (快照)** | Epoch 结束时整个 Vault 的状态快照，快照本身也会随时间压缩          | DAG commit（但会衰减）  |
| **Drift (漂移)**    | 一条 Engram 因再巩固而偏离原始内容的累积量                    | 记忆的"失真度"          |
| **Imprint (铭印)**  | 一条 Engram 的来源标记（亲历/学习/继承/注入）                 | 你是亲眼看到的，还是听说的？    |

***

## 第三章：数据模型

### 3.1 Engram（记忆单元）

    Engram {
      id:                   UUID
      content:              Text                # 始终为文本（多模态输入经转换后也存文本描述）
      type:                 episodic | semantic | procedural
      status:               buffered | consolidated | abstracted | archived | forgotten
                                              # 生命周期状态机（见第十四章）
      modality:             text | image | audio | video | mixed
                                              # 原始输入模态（见 12.3.1 节）
      media_ref:            URI | null        # 非文本媒体的对象存储引用
                                              # content 始终为文本描述（模态统一化）

      # === 强度与衰减 ===
      strength:             float [0, 1]      # 当前记忆强度
      rigidity:             float [0, 1]      # 刚性/不可塑性（见 17.3 节）
                                              # 0.1 = 高度可塑（昨天开会的气氛）
                                              # 0.99 = 近乎不可变（Alice 对花生过敏）
      decay_rate:           float             # 衰减速率（个体化）
      reinforcement_count:  int               # 被提取的总次数
      last_accessed_at:     timestamp
      created_at:           timestamp

      # === 情绪标记 ===
      emotional_valence:    float [-1, 1]     # 正面/负面
      emotional_intensity:  float [0, 1]      # 强度，影响 decay_rate

      # === 编码上下文 ===
      encoding_context: {
        source:             string            # 来自哪里
        situation:          string            # 什么场景
        associations:       [Engram.id]       # 同时活跃的其他记忆
      }

      # === 内部版本链 ===
      revision_chain:       [Revision]        # 每次再巩固产生一个 revision

      # === 结构化断言 ===
      claims:               [ClaimRecord.id]  # 从 content 提取的可验证事实断言（见 3.13 节）
                                              # Epoch 期间由 LLM 提取，仅 semantic/procedural 类型
                                              # 空列表 = 无可验证断言（episodic 日记等）

      # === 关联网络 ===
      # 关联关系由独立的 Nexus 实体管理（见 3.8 节）
      # Nexus 是唯一权威的关联数据源，支持边级隐私、拓扑噪声、级联脱敏
      # 此处不内嵌 links 字段，避免双重真相源
    }

### 3.2 Revision（修订记录）

    Revision {
      revision_id:          int               # 单调递增
      timestamp:            timestamp
      trigger:              recall | consolidation | abstraction | external_update
      content_before:       snapshot          # delta 或全量
      content_after:        snapshot
      context:              string            # 触发再巩固时的上下文
      strength_delta:       float             # 这次操作对强度的影响
    }

### 3.3 MemoryCommit（全局快照）

    MemoryCommit {
      commit_id:            UUID
      timestamp:            timestamp
      trigger:              scheduled | event | manual | merge | fork | deep_sleep
      parents:              [commit_id]       # 多父节点 DAG（合并操作产生双亲）

      # 不存全量，存增量
      engram_diffs: [{
        engram_id:          UUID
        diff_type:          created | modified | decayed | pruned | merged |
                            state_changed | shredded
        delta:              patch             # 与上一个 commit 的差异
      }]

      # Epoch 运行记录引用
      epoch_run:            EpochRun.id | null

      # 元信息
      stats: {
        total_engrams:      int
        avg_strength:       float
        abstraction_events: int               # 本周期内的抽象化次数
        pruned_count:       int               # 被遗忘的数量
        debt_resolved:      int               # 本次清偿的认知债务数
        claims_extracted:   int               # 本周期提取的 ClaimRecord 数
        claim_conflicts:    int               # 本周期检测到的事实冲突数（需人工审查的）
      }

      message:              string            # 类似 git commit message
      degraded:             bool              # 是否为降级 Epoch 产生的快照
    }

### 3.4 MemoryVault（记忆仓库）

    MemoryVault {
      id:                   UUID
      owner_id:             UUID
      name:                 string

      # === 来源追踪 ===
      forked_from:          VaultRef | null
      fork_point:           commit_id | null
      upstream:             VaultRef | null

      # === 可见性 ===
      visibility:           public | private | selective
      privacy_mask:         PrivacyMask

      # === 统计 ===
      fork_count:           int
      subscriber_count:     int
    }

### 3.5 ForkedEngram（Fork 后的记忆）

```
ForkedEngram extends Engram {
  origin: {
    vault_id:           UUID
    owner_id:           UUID
    engram_id:          UUID
    fork_timestamp:     timestamp
  }

  acquisition_type:     experienced | learned | inherited
  trust_score:          float [0, 1]
  drift_from_origin:    float [0, 1]      # 每次再巩固累积增加（仅统计用，不触发自动断裂）
                                          # drift > 0.5 时 recall 返回附带操作建议（见下方）
}

```

**Drift 操作建议 (Drift Action Hints)**：

drift\_from\_origin 如果只是一个展示数字而不附带可操作的选项，就是噪声。系统在 recall 返回 ForkedEngram 时，根据 drift 值附带操作建议（非持久化，仅在返回值中）：

| drift 范围   | 行为    | 操作建议                                                       |
| ---------- | ----- | ---------------------------------------------------------- |
| 0.0 \~ 0.3 | 无提示   | —                                                          |
| 0.3 \~ 0.5 | 信息提示  | "此记忆已偏离原始版本 {drift}%，可通过 `engram sync` 查看上游变化"             |
| 0.5 \~ 0.8 | 操作建议  | "此记忆与上游差异较大。可选：`sync`（拉取上游更新）/ `detach`（确认独立演化，停止追踪上游）"    |
| > 0.8      | 强操作建议 | "此记忆已与上游面目全非。建议：`detach`（切断上游关联）或 `diff --origin`（查看具体差异）" |

`detach` 命令将 ForkedEngram 的 `origin` 链接归档为只读历史记录，停止 drift 计算和上游 sync。这是用户主动执行的操作，不是系统自动断裂。

### 3.6 PrivacyMask（隐私面具）

    PrivacyMask {
      # 规则式过滤
      rules: [
        { filter: "emotional_intensity > 0.8", action: "hide" },
        { filter: "tag in ['personal', 'health']", action: "hide" },
        { filter: "type == 'procedural'", action: "readonly" },
      ]

      # 显式黑白名单
      hidden_engrams:       [Engram.id]
      exposed_engrams:      [Engram.id]

      # 脱敏策略
      sanitization:         redact | generalize | noise
    }

### 3.7 MemoryPR（记忆合并请求）

> **架构修正**：原设计中 MemoryPR 携带 `proposed_engrams` + `proposed_links`（快照式提交）。但 Export Projection（5.2 节）引入 PrivacyMask 过滤 + 拓扑噪声后，Bob 拿到的是残缺且掺假的子图，基于该子图计算的快照 diff 在 Alice 的 canonical 图上无法确定性重放。修正方案：PR 携带操作日志（OperationLog），Alice 在 canonical 图上逐条重放操作，引用不存在的实体时静默跳过。详见 3.14-3.16 节。

    MemoryPR {
      id:                   UUID
      source_vault:         VaultRef            # 提交方（如 Bob）的 Vault
      target_vault:         VaultRef            # 接收方（如 Alice）的 Vault
      status:               open | replaying | merged |
                            partially_merged | rejected | conflicted
                            # replaying: 重放引擎正在执行
                            # partially_merged: 部分操作已应用，
                            #   剩余 conflict/blocked 操作等待人工审查

      # === 操作日志（替代旧的快照式提交）===
      operation_log:        OperationLog        # Bob 的操作列表（见 3.14 节）

      # === 重放结果 ===
      replay_report:        ReplayReport | null # 重放后生成（见 3.16 节）

      conflicts:            [MemoryConflict]
      merge_strategy:       MergeStrategy
    }

### 3.8 Nexus（关联连接 — 独立一等实体）

Nexus 从 Engram.links 内嵌字段提升为独立的一等实体，以支持边级隐私控制、拓扑噪声注入和图推断防御。

    Nexus {
      id:                   UUID
      source_id:            Engram.id
      target_id:            Engram.id
      direction:            directed | bidirectional

      type:                 causal | temporal | semantic | spatial |
                            abstracted_to | perspective | fork_origin
      association_strength: float [0, 1]      # 赫布学习动态调整
      created_at:           timestamp
      last_coactivated_at:  timestamp         # 最近一次共同激活

      # 隐私（边级）
      privacy_level:        0 | 1 | 2 | 3    # 与节点隐私独立控制
      cascaded_from:        Engram.id | null  # 如果是级联降级产生的
      is_noise:             bool              # 拓扑噪声注入标记（仅在 Fork 输出中）
    }

### 3.9 PulseEvent（脉冲事件）

三轨异步通信的核心载体。觉醒轨道产出，潜意识轨道消费。

    PulseEvent {
      event_id:             UUID
      timestamp:            timestamp
      type:                 recall | capture | reinforce

      # 事件内容
      engram_ids:           [Engram.id]       # 本次激活涉及的 Engram
      query_context:        string            # 触发时的上下文
      coactivated_pairs:    [(id, id)]        # 共同激活的 Engram 对（赫布学习）

      # 幂等性
      idempotency_key:      string            # 防止重放导致双倍强化
      processed:            bool              # 是否已被潜意识轨道消费
    }

### 3.10 PruneInstruction（修剪指令）

墓碑机制的核心操作对象。用于在不修改历史 Hash 链的前提下实现 Snapshot 压缩。

    PruneInstruction {
      id:                   UUID
      timestamp:            timestamp
      target_commit_id:     MemoryCommit.id   # 被修剪的 Snapshot
      action:               tombstone | archive_to_cold | summarize
      summary:              string | null     # 如果是 summarize，保留的摘要内容
      issued_in_commit:     MemoryCommit.id   # 在哪个 commit 中提交的修剪指令
    }

### 3.11 KeyRef（加密元数据）

加密粉碎机制的 Schema 支撑。DEK 本身不在此结构中（存在独立的 Key Store），这里仅记录加密关系。

    KeyRef {
      engram_id:            Engram.id
      encryption_algorithm: aes-256-gcm       # 固定算法
      key_id:               string            # Key Store 中的 DEK 标识符
      encrypted:            bool              # 当前是否处于加密状态
      shredded:             bool              # DEK 是否已被删除（加密粉碎完成）
      shredded_at:          timestamp | null
    }

### 3.12 EpochRun（Epoch 运行记录）

记录每次 Epoch 的执行状态，用于认知债务追踪和降级标记。

    EpochRun {
      id:                   UUID
      started_at:           timestamp
      completed_at:         timestamp | null
      status:               running | completed | failed | degraded

      # 模式
      mode:                 full_sleep | light_sleep | deep_sleep
      seal_timestamp:       timestamp         # 密封窗口截止时间（见 12.8）

      # 处理统计
      l2_entries_processed: int
      engrams_consolidated: int               # BUFFERED → CONSOLIDATED
      engrams_abstracted:   int               # CONSOLIDATED → ABSTRACTED
      engrams_archived:     int               # → ARCHIVED
      engrams_shredded:     int               # 加密粉碎执行数
      debts_resolved:       int               # 认知债务清偿数
      debts_created:        int               # 新增认知债务（降级时）

      # 产出
      commit_id:            MemoryCommit.id | null
    }

***

## 第四章：记忆生命周期

                            +-------------+
                            |   外部输入    |
                            +------+------+
                                   |
                              (1) 编码 Encode
                                   |
                                   v
                         +------------------+
                         |   工作记忆缓冲区   |  容量: ~7 个 Engram
                         |   (Working Buf)   |  存活: 秒~分钟级
                         +--------+---------+
                                  |
                        (2) 注意筛选 Attention Gate
                        (不被注意的直接丢弃)
                                  |
                                  v
                         +------------------+
                         |    短期记忆层      |  容量: 中等
                         |    (STM / 海马)    |  存活: 分钟~天级
                         +--------+---------+
                                  |
                         (3) 整合 Consolidation
                         (Epoch 期间批量处理)
                                  |
                                  v
                         +------------------+
                         |    长期记忆层      |  容量: 近似无限
                         |    (LTM / 皮层)   |  存活: 天~永久
                         +--------+---------+
                                  |
                  +---------------+---------------+
                  |               |               |
             (4) 再巩固       (5) 衰减        (6) 抽象化
            Reconsolidate      Decay          Abstraction
             (每次回忆)      (持续进行)      (Epoch 期间)
                  |               |               |
                  v               v               v
              记忆被修改      记忆变弱/消亡    情景->语义提炼
              drift 增加     strength -> 0    多条->一条精华
                                  |
                                  v
                         +------------------+
                         |    归档/遗忘      |
                         |    (Archive)      |
                         |  可被唤醒但代价高  |
                         +------------------+

### 各阶段核心规则

**(1) 编码 (Encode)**

*   每条新记忆默认类型为 `episodic`
*   初始强度由情绪强度决定：平淡的事 0.3，震撼的事 0.9
*   自动检测与已有记忆的关联，建立 Nexus

**(2) 注意筛选 (Attention Gate)**

*   工作记忆容量有限，溢出时按强度淘汰
*   被淘汰 ≠ 被遗忘，只是不进入短期记忆（相当于"没注意到"）

**(3) 整合 (Consolidation)**

*   发生在 Epoch 期间（离线批处理）
*   STM 中存活足够久、被访问足够多的 Engram 迁入 LTM
*   迁入时建立更广泛的 Nexus 网络

**(4) 再巩固 (Reconsolidation)** — 核心机制

再巩固有**两层副作用**，必须严格区分：

**Layer A — 元数据更新（用户无感知，每次 recall 触发）**：

*   strength 增加（越用越强），遵循间隔效应：间隔越长，增益越大
*   access\_count / last\_accessed 更新
*   Nexus 权重调整（赫布学习：同时被激活的记忆，彼此关联增强）
*   **用户体验**：与搜索引擎的 click-through 信号类似，用户看不到内容变化，只影响排序

**Layer B — 内容修改（仅限低刚性记忆，仅在 Epoch 期间由 LLM 执行）**：

*   仅当 `rigidity < 0.5` 时才可能发生（见 17.3 节）
*   不是 recall 时即时修改——延迟到 Epoch 期间，由 LLM 评估是否需要用新上下文微调内容
*   高刚性记忆（事实、配置、用户指令，rigidity ≥ 0.5）的内容**永远不被修改**
*   每次内容修改产生 Revision 记录，可审计可回滚
*   **用户体验**：大部分记忆（semantic/procedural 默认 rigidity ≥ 0.5）内容不会变化；只有低刚性的 episodic 记忆（默认 0.15）可能被微调

**关键保证**：`recall()` 返回的内容在当次调用中是稳定的。Agent 基于 recall 结果做决策时，该结果不会在调用过程中改变。内容修改只可能在下一个 Epoch 之后才生效。

*   **工程约束：异步再巩固缓冲池**（见 17.2 节）
    *   `recall()` 在调用层面保持为纯读操作（无副作用，极速响应）
    *   激活事件写入内存中的 Reconsolidation Buffer
    *   真正的数据库写入（strength 更新、Revision 生成、Nexus 调整）延迟到 Epoch 期间或累积到阈值时异步批量执行

**Layer B 内容修改的用户可见性保障**：

episodic 记忆默认 rigidity = 0.15，属于 Layer B 可修改范围。用户可能在两周后 recall 一条记忆时发现措辞与自己记忆中不同，但不知道是哪个 Epoch 改的。仅靠 Revision Chain 不够——普通用户不会翻日志。

    保障措施:
      1. 内容变更标记 (content_modified_since_last_access):
         - Epoch 修改了某条 Engram 的 content 时，设置 modified_flag = true
         - 下次 recall 命中该 Engram 时，返回结果附带提示:
           "此记忆在 [date] 的整合中被微调。查看原始版本: engram diff <id>"
         - 用户确认后清除 modified_flag
         - 这是返回值中的提示 + 数据库中的一个 bool 标记，不是 Revision

      2. 快速回退:
         - engram diff <id>: 显示当前版本与上一版的差异
         - engram revert <id>: 回退到上一个 Revision（一条命令，不需要翻日志）

      3. 全局关闭开关:
         - engram config set reconsolidate_content=false
         - 关闭后 Layer B 完全禁用，所有记忆的 content 永不被 Epoch 修改
         - 仅保留 Layer A 的元数据更新

**(5) 衰减 (Decay)**

*   持续后台进程，基于 Ebbinghaus 遗忘曲线 + FSRS 算法
*   衰减速率受以下因素调节：
    *   被提取次数越多 → 越慢衰减
    *   情绪强度越高 → 越慢衰减
    *   Nexus 连接越多 → 越慢衰减
*   低于阈值 → 休眠 → 进一步降低 → 归档

**(6) 抽象化 (Abstraction)**

*   Epoch 期间检测聚类：多条相似 episodic Engram → 一条 semantic Engram
*   原始 episodic 不立即删除，但强度大幅降低（细节慢慢模糊）
*   新 semantic Engram 继承原始记忆的关联网络
*   同时发现潜在关联（类似"顿悟"）

***

## 第五章：版本管理系统

### 5.1 双层版本模型

**微观层：Engram Revision Chain（单条记忆的演变历史）**

    rev1 ---- rev2 ---- rev3 ---- rev4 (current)
    "原始"   "第一次    "被新     "与别人
              回忆修改"   证据修正"  merge后"

每次再巩固、外部修改、merge 都产生一个 revision。Revision 本身也衰减：远期的 revision 只保留摘要。

**宏观层：Vault Snapshot DAG（全局记忆状态的版本树）**

    S1 -- S2 -- S3 -- S4 -- S5 (HEAD)
                  |
                  +-- S3' -- S4' (branch: "假设")

每个 Epoch 结束自动产生一个 Snapshot，也可以手动触发。

### 5.2 Snapshot 的生命周期（与传统版本控制的核心差异）

传统版本控制中所有 commit 永久保留、同等精度。Engram 中 Snapshot 在表现层上遵循"衰减压缩"逻辑，但**底层 Hash 链保持不可变**。

**关键工程约束：墓碑机制 (Tombstone)**

> 直接修改历史 Snapshot 会破坏 Merkle Hash 链，导致联邦网络中所有 Fork 的上游引用断裂。因此，"压缩"**绝不篡改历史快照本体**。

实现方式：

*   历史 Snapshot 的 Hash 和 diff 数据永久不可变
*   当需要"遗忘/压缩"时，在当前 HEAD 提交一个 **Prune Instruction（修剪指令）**
*   Prune Instruction 将旧 Snapshot 的索引指针置为 tombstone，或将原始数据迁移至冷存储 (Archive)
*   衰减只发生在**索引层**和**表现层**，底层数据结构的不可变性 (Immutability) 是分布式协作的基石

**存储分离约束 (Storage Separation)**：

> Engram 每次 Epoch 都会因衰减更新数以万计的 strength 值（如 0.850→0.842）。高频标量变更不能与低频语义变更混在同一存储层——前者会导致版本历史急剧膨胀。

> **实现说明**：文档中使用"Git 风格的 Merkle DAG"来描述版本管理机制。这是指自研的内容寻址 DAG 结构（Hash 链 + 增量 diff + 不可变历史），**不是指直接使用 Git 二进制工具或 `.git` 目录**。Git 的文件系统假设（一个 blob = 一个文件）和操作语义（branch/checkout/rebase）不适合 Engram 的数据模型。自研 DAG 只借用 Merkle Hash 链的完整性保证。

    Merkle DAG 版本控制的对象 (低频变化，强语义):
      - content           (正文)
      - type              (类型)
      - rigidity          (刚性——仅人工或系统事件修改)
      - encoding_context   (编码上下文)
      - revision_chain     (再巩固历史)
      - 状态转换记录       (T1-T10)

    不进入 Merkle DAG 的对象 (高频变化，弱语义):
      - strength           → SQLite 标量表
      - last_accessed_at   → SQLite 标量表
      - reinforcement_count → SQLite 标量表
      - decay_rate         → SQLite 标量表
      - association_strength (Nexus) → SQLite 邻接表

    全局 Snapshot 时的持久化策略:
      MemoryCommit 中记录:
        dag_commit_hash:   "abc123"     # 指向 Merkle DAG 中的强语义快照
        scalar_snapshot:   "scalars_epoch_42.sqlite"  # 标量的独立快照文件
        (两者都被 commit，但物理分离)

**双层对象模型：Canonical DAG vs Export Projection**

> 联邦同步时，同一个 upstream commit 对不同接收方执行不同的 PrivacyMask，输出内容不同。如果接收方校验的是 canonical commit hash，但收到的是经过隐私过滤的子集，hash 必然不匹配。因此必须区分两层对象。

    Canonical Commit DAG (本地不可变层):
      - 存储完整的、未过滤的 Engram 数据和 Merkle Hash 链
      - 仅在本地存储和同实例内部校验时使用
      - Hash 基于完整内容计算，永远不变
      - 这是 Truth Store 的底层结构

    Export Projection Manifest (跨实例传输层):
      - 每次跨实例传输时，根据接收方身份 + PrivacyMask 动态生成
      - 包含: 过滤后的 Engram 子集 + 脱敏内容 + 拓扑噪声
      - 独立计算 projection_hash = hash(filtered_engrams + manifest_metadata)
      - 接收方校验的是 projection_hash，而非 canonical commit hash

      ProjectionManifest {
        source_commit_id:     MemoryCommit.id    # 来源 commit（供溯源，不用于校验）
        recipient_did:        DID                # 接收方身份
        projection_hash:      string             # 过滤后内容的 hash
        privacy_mask_version: string             # 应用的 PrivacyMask 版本
        noise_seed:           string             # 拓扑噪声的种子（接收方不可见）
                                                 # 确定性约束（见下方）
        engram_manifest:      [{                 # 本次传输包含的 Engram 清单
          engram_id:          UUID
          included_fields:    [string]           # 哪些字段被包含（vs 被脱敏/省略）
          sanitization_applied: bool
          mutable:            bool               # 该 Engram 是否允许接收方在 PR 中修改
                                                 # sanitized 的 Engram: mutable = false
                                                 # 完整导出的 Engram: mutable = true
                                                 # 接收方对 mutable=false 的 Engram
                                                 # 提交 modify_engram_content → unauthorized
        }]
        created_at:           timestamp
        signature:            Ed25519            # 发送方签名
      }

    Noise Seed 确定性约束 (Noise Seed Determinism):

      问题: projection 是按接收方动态生成的，且可加入拓扑噪声。如果同一组输入
      不能稳定产出同一个 projection，那么重试、缓存、审计复现、bug 排查都不可行。

      约束:
        noise_seed = HMAC(
          key   = sender_private_noise_key,    # 发送方的噪声主密钥（本地持久化）
          data  = source_commit_id
                + recipient_did
                + privacy_mask_version
        )

      保证:
        - 确定性: 同一 (commit, recipient, mask_version) 三元组永远产出同一 noise_seed
          → 同一组输入的 projection_hash 永远相同
          → 重试、缓存命中、审计复现都正常工作
        - 不可预测: 接收方不知道 sender_private_noise_key，无法推导 noise_seed
          → 无法区分真实边和噪声边
        - 不可跨接收方关联: 不同 recipient_did 产出不同 noise_seed
          → 两个接收方无法通过对比噪声模式推断真实拓扑

      noise_seed 何时变化:
        - source_commit_id 变化 (新 Epoch) → 自然变化
        - privacy_mask_version 变化 (用户修改隐私规则) → 自然变化
        - 发送方主动轮换 noise_key → 所有未来 projection 的噪声模式改变
          (已缓存的历史 projection 不受影响)

      重算:
        - 发送方可以随时用 noise_seed 重算任意历史 projection（用于审计）
        - 接收方不可重算（不掌握 noise_key）

    Projection 的语义边界 (Projection Semantic Boundary):

      Projection 经过隐私过滤 + 脱敏 + 拓扑噪声，不再是 canonical 数据的精确子集。
      因此必须严格限制 projection 数据的用途:

      允许:
        - 阅读和学习（fork 到本地 Vault 后使用）
        - 向量检索和关联发现
        - 基于 Projection 内容产生操作（capture/modify/nexus），
          通过 OperationLog 提交回发送方（见 3.14 节）

      禁止作为以下机制的输入:
        - **图级 diff/merge 的基准**（Projection 含噪声边且缺失节点，
          基于它的快照 diff 在 canonical 图上无法确定性重放。
          PR 必须提交 OperationLog 而非 Projection 快照 diff）
        - 共识判定（不能用 projection 投票"什么是真的"）
        - 归属计算（drift_from_origin 必须基于 canonical，不能基于 projection）
        - 信任评级（实例信任度不能基于 projection 后的数据质量评估）

      原则: 一切需要"同一对象"语义的机制，只能基于 canonical 可见域内的数据。
            projection 是隐私保护的产物，不是共识的基础。

    校验流程:
      接收方收到数据包后:
      1. 验证 signature（确认来自声称的发送方）
      2. 验证 projection_hash（确认传输中未被篡改）
      3. 不尝试验证 canonical commit hash（接收方无权看到完整数据）

    增量同步时:
      - 发送方对比 canonical DAG 的 diff
      - 对 diff 应用接收方对应的 PrivacyMask
      - 生成新的 ProjectionManifest
      - 接收方用 projection_hash 校验增量包的完整性



    底层存储（不可变）：
      S1 -- S2 -- S3 -- S4 -- S5 -- ... -- S100 -- HEAD
      (所有 Hash 完整保留，任何节点均可被联邦网络校验)

    索引/表现层（可衰减）：
      S1[tomb] -- S2[tomb] -- S30[summary] -- S60[summary] -- S90 -- S100 -- HEAD
      |                       |               |               |      |
      冷存储                   月度摘要         月度摘要         完整    完整

**表现层压缩规则：**

*   最近 7 天：每个 Epoch 保留一个完整 Snapshot 索引
*   7\~30 天：每周保留一个活跃索引，其余标记 tombstone 并生成摘要
*   1\~12 个月：每月保留一个活跃索引
*   1 年以上：每季度保留一个活跃索引，其余迁入冷存储
*   用户可以 `pin` 重要 Snapshot 防止其索引被 tombstone
*   被 tombstone 的 Snapshot 可以从冷存储中"唤醒"，但代价较高（类似大脑中"似乎想起来了"的费力回忆）

### 5.3 操作语义

| 操作              | 语义                 | 触发条件                 |
| --------------- | ------------------ | -------------------- |
| `snapshot`      | 捕获当前 Vault 完整状态    | Epoch 结束 / 手动 / 重大事件 |
| `log`           | 查看 Snapshot 历史     | 用户主动查看               |
| `diff(A, B)`    | 比较两个时间点的认知差异       | "我对X的理解这个月变了多少？"     |
| `restore(S)`    | 回溯到某个历史状态查看        | 注意：查看本身触发再巩固         |
| `branch(name)`  | 从当前/历史节点创建分支       | 假设性探索                |
| `merge(branch)` | 将分支合并回主线           | 探索结果确认后              |
| `pin(S)`        | 钉住一个 Snapshot 防止压缩 | 用户标记重要时刻             |
| `rewind(S)`     | 真正回退到历史状态（破坏性）     | 罕见，需确认               |

### 5.4 分支的用途 — 反事实思维

不同于传统版本控制的功能分支，Engram 的分支模拟的是**反事实思维**：

    主线（实际认知）:
      S1 -- S2 -- S3 -- S4 -- HEAD
                    |
    假设分支:        +-- "如果我忘掉了X的偏见，我的判断会怎样？"
                        S3' -- 移除相关 Engram -- 重新推理 -- S4'

    对比分支:        +-- "如果我采纳了 Alice 的观点而非 Bob 的"
                        S3'' -- merge Alice's PR -- 观察影响 -- S4''

***

## 第六章：协作记忆网络

### 6.1 核心隐喻对照

| GitHub           | Engram        | 脑科学/社会学映射     |
| ---------------- | ------------- | ------------- |
| User/Org         | `MemoryOwner` | 个体意识          |
| Repository       | `MemoryVault` | 一个人的完整记忆空间    |
| Fork             | `fork()`      | 学习/模仿/镜像神经元   |
| Pull Request     | `MemoryPR`    | "我有一段经验想分享给你" |
| Merge            | `merge()`     | 记忆整合/认知重构     |
| Star / Watch     | `subscribe()` | 关注某人的认知演化     |
| `.gitignore`     | `PrivacyMask` | 潜意识/隐私边界      |
| Public / Private | `visibility`  | 选择性自我暴露       |

### 6.2 角色模型

    Individual (个体)
      +-- 拥有一个或多个 Vault
          +-- personal (private)     # 个人生活记忆
          +-- professional (public)  # 专业知识
          +-- project-x (selective)  # 特定项目知识

    Collective (集体)
      +-- Organization Vault
          +-- 由成员的 PR 汇聚而成
          +-- 有独立的整合周期和抽象化
          +-- 代表"组织的集体认知"

### 6.3 Fork 的三种模式

| 模式                         | 说明                                                    | 用途            |
| -------------------------- | ----------------------------------------------------- | ------------- |
| **Deep Fork (深度克隆)**       | 完整复制：Engram + Nexus 网络 + Revision 历史。相当于"继承某人的全部认知遗产" | 导师传承、知识库迁移    |
| **Shallow Fork (浅层克隆)**    | 只复制当前状态的 Engram，不带历史。相当于"读了一本书"——只获得结论，不知道推导过程        | 快速获取知识、参考他人观点 |
| **Selective Fork (选择性克隆)** | 只 fork 符合条件的子集，按主题/标签/时间范围/类型过滤                       | 只学某人的特定领域知识   |

### 6.4 Fork 时的记忆转化规则

| 原始记忆类型               | Fork 后变成                 | 强度变化  | 说明                            |
| -------------------- | ------------------------ | ----- | ----------------------------- |
| episodic "我在巴黎看到"    | learned "Alice在巴黎看到"     | x 0.4 | 别人的经历不是你的经历，可信度取决于对来源的信任      |
| semantic "水在100°C沸腾" | semantic（同）              | x 0.7 | 知识可以较好迁移，但需要自己验证后才满强度         |
| procedural "如何骑自行车"  | procedural (理论)          | x 0.2 | 技能无法通过复制获得，必须通过自身实践 reinforce |
| emotional "那天我很害怕"   | neutralized "Alice曾感到害怕" | x 0.3 | 情绪不可转移，情绪标记被大幅降低              |

### 6.5 Merge 冲突解决模型

**冲突检测的输入**：MemoryPR 采用操作日志模式（3.14 节 OperationLog）后，冲突检测的输入不再是"两组 Engram 快照"，而是"OperationLog 中的 modify\_engram\_content / contradict\_claim 操作 vs 接收方 canonical 图中的 ClaimRecord"。重放引擎在 Phase 1（预扫描）中对每条修改/反驳操作执行以下冲突检测流程。

**冲突检测依据**：事实性冲突的判定基于 ClaimRecord（3.13 节）的结构化比对，而非自由文本的 LLM 推测。两条记忆是否构成事实冲突，由 `claim_key` 归组 + 时间区间重叠 + object 矛盾三重条件共同判定。无 ClaimRecord 的记忆（纯 episodic、无可验证断言）不进入事实冲突判定流程。

                            检测到冲突
                                |
                    +-----------+-----------+
                    |                       |
               事实性冲突                 视角性差异
         (ClaimRecord.claim_key        (都可以是对的)
          匹配 + 时间区间重叠             (或无 ClaimRecord)
          + object 矛盾)
                    |                       |
            +-------+-------+              |
            |               |              v
        有明确证据       无明确证据     保留双方视角
      (evidence_refs    (两条 Claim    创建 "perspective" 类型 Nexus
       + confidence)    的 confidence  两条记忆共存，标注来源
            |           对比)
            v               v
        采纳有证据方    标记为 "disputed"
        (高 confidence   保留双方版本
         + 更可靠         等待更多证据
         source_type)

**特殊规则：**

*   时效性：更近期的记忆在时效敏感话题上优先
*   信任链：直接经历 > 一手转述 > 多手传播
*   共识权重：被更多人独立验证的记忆获得更高可信度

### 6.6 合并策略选项

    MergeStrategy {
      # === 合并模式 ===
      replay_mode:          operation_log | snapshot_diff
                            # operation_log: 基于 OperationLog 逐条重放（v0.5 默认，
                            #   解决 Projection 信息不对称问题，见 3.14 节）
                            # snapshot_diff: 旧模式，基于快照对比
                            #   仅用于同实例内部的分支合并（无 Projection 噪声）

      # === 冲突解决 ===
      conflict_resolution:  theirs | ours | interactive | weighted | diplomat
      strength_merge:       max | avg | weighted_avg
      duplicate_handling:   skip | merge_content | keep_both
      emotion_policy:       keep_mine | adopt | blend
      provenance_tracking:  bool
    }

### 6.6.1 认知外交官代理 (Cognitive Diplomat Agent)

**问题**：大规模 upstream sync 可能产生数百条认知差异。如果全部交由用户 interactive merge，用户会直接放弃使用系统（Merge Conflict Hell）。

**解决方案**：引入 LLM 驱动的 Cognitive Diplomat Agent 作为合并前的预处理层：

    incoming PR (500 条差异)
            |
            v
    +-------------------+
    | Cognitive Diplomat |  ← LLM 预跑 dry-run
    | Agent              |
    +--------+----------+
             |
        +----+----+----+
        |         |    |
        v         v    v
     自动融合   静默   需人工
     (420条)   忽略   审查
               (50条)  (30条)

**分流规则：**

*   **自动静默融合**（仅限以下安全操作）：
    *   重复内容去重（语义相似度 > 0.98 且长度差 < 5%，见下方详细规则）
    *   元数据合并（strength、reinforcement\_count 取较大值）
    *   格式统一（不改变语义）
    *   低情绪 + 低刚性的非事实类差异
*   **静默忽略**：差异过小或涉及纯时效性更新 → 取较新版本
*   **升级为人工审查**：
    *   高情绪权重 (`emotional_intensity > 0.8`) 或高刚性 (`rigidity > 0.7`)
    *   涉及事实、因果、时间线、置信度的差异（**即使看似"小"也必须保留双方版本**）
    *   带明确出处的陈述（不可改写为无出处断言）

**防止静默语义腐蚀**：

*   自动融合**绝不合并事实分歧为虚假共识**——遇到事实性差异时保留双方版本为 `perspective` 类型 Nexus
*   每次自动融合必须保留机器可读的 `merge_provenance`（来源溯源记录）
*   用户可事后在审计日志中查看并回滚任何自动融合决策

**置信度分级与审计疲劳防护 (Confidence-Gated Merge)**：

> 没有用户会定期阅读 400 行 JSON 审计日志。如果 Diplomat 在静默合并中改错了一个 IP 地址最后一位，用户要花几天 debug 才能发现。一次这样的事故就会让用户永久禁用 Diplomat，系统退化回手动冲突地狱。

    每条自动融合操作必须计算 merge_confidence:

      merge_confidence = f(
        semantic_similarity,        # 两个版本的语义相似度
        change_magnitude,           # 变更幅度（一个字符 vs 整段重写）
        field_sensitivity,          # 涉及的字段敏感度（IP/密码/数值 vs 措辞/格式）
        source_trust                # 来源信任度
      )

    Diplomat 操作权限分级 (不按置信度，按操作类型):

      允许静默执行（无需确认）:
        - 完全相同内容的去重（语义相似度 > 0.98 且长度差 < 5%）
        - 格式归一化（空格、换行、标点、大小写统一，不改变任何词）
        - 元数据折叠（strength、access_count 取较大值）

      允许聚合确认（批量摘要 + 用户一次确认）:
        - 措辞改写但语义不变（同义替换、句式调整）
        - 时效性更新（"2024年" → "2025年"，有明确时间戳证据）

      绝对禁止静默执行（必须逐条人工审查）:
        - 事实性内容的任何差异（数值、ID、URL、配置项、人名、日期）
        - 因果关系的任何变化
        - 时序的任何调整
        - 置信度/来源的任何变更
        - 断言的增加或删除

      Diplomat 默认状态: OFF
        用户必须显式启用。启用后首周为"预览模式":
        所有操作都生成建议但不执行，用户逐条确认。
        预览模式中用户接受率 > 95% 后，自动升级为正常模式。
        任何一次被用户标记为"错误"的操作 → 回退到预览模式 30 天。

      核心原则:
        问题不是置信度能不能算准，而是哪些动作机器根本不应该碰。
        语义层面的合并（改了意思的任何操作）永远不静默。
        只有结构层面的操作（去重、格式、元数据）才允许静默。

**Diplomat 对 OperationLog 的分流规则（操作日志模式补充）**：

> 当 MergeStrategy.replay\_mode = operation\_log 时，Diplomat 的分流粒度从"Engram 级差异"细化为"Operation 级操作"。以下规则替代上方的通用规则，仅在操作日志模式下生效。

    Diplomat 对 OperationLog 中每条 Operation 的分流:

      ── 允许静默执行 ──

      create_engram:
        - 新 Engram 不与接收方任何 ClaimRecord 冲突
        - origin = 'external_pr', verified = false, strength 按 fork 规则降权
        - 静默入库（不修改接收方已有记忆）

      create_nexus:
        - 两端都在 canonical 中存在
        - nexus_type 不是 causal（因果推断风险高，需审查）
        - 初始 association_strength 上限 0.3（外部 PR 创建的关联不应强权重）

      modify_engram_meta:
        - 仅 tags 变更（不涉及 type/importance）
        - 且 old_value 与 canonical 当前值一致（无并发修改）

      ── 允许聚合确认 ──

      create_engram:
        - 与接收方已有记忆语义相似度 > 0.7
        - Diplomat 展示: "提交方新增了 N 条与你现有知识相似的记忆"

      modify_engram_content:
        - content_patch 变更幅度小（< 20% 字符变化）
        - 无 ClaimRecord 冲突

      ── 绝对禁止静默执行 ──

      modify_engram_content:
        - 涉及 ClaimRecord 的任何变更
        - 涉及 rigidity >= 0.5 的 Engram
        - content_patch 变更幅度 >= 50%

      contradict_claim:
        - 始终逐条人工审查（显式反驳事实断言）

      delete_engram / delete_nexus:
        - 始终需人工确认（防止恶意批量删除）

      create_nexus (nexus_type = causal):
        - 因果关联有重大语义影响，必须审查

### 6.7 Upstream Sync（上游同步）

Fork 之后，原始记忆库还在演化。需要一个机制来同步上游变化。

> **架构修正**：与 PR（Bob → Alice）一样，Upstream Sync（Alice → Bob）也面临 Projection 信息不对称问题。解法一致：同步的传输单元是操作日志（SyncOperationLog），不是快照 diff。

    Alice's Vault (upstream)
        |
        +-- commit4  <-- Alice 新增了记忆
        +-- commit3  <-- Alice 的记忆发生了再巩固
        |
        == fork point ========================+
        |                                     |
        +-- commit2                       Bob's Fork
        +-- commit1                         +-- bob_commit2 (Bob 自己的变化)
                                            +-- bob_commit1
                                            +-- fork_commit

**同步流程（操作日志模式）**：

    1. Bob 的实例向 Alice 的实例请求同步:
       "自 commit_id=X (Bob 上次同步点) 以来有哪些变化？"

    2. Alice 的实例:
       a. 计算 canonical diff (commit_X → HEAD)
          → 得到 Engram 和 Nexus 的变更列表
       b. 对变更列表应用 Bob 的 PrivacyMask:
          → 过滤掉 Bob 不可见的 Engram 变更
          → 过滤掉涉及 Bob 不可见 Nexus 的变更
          → 噪声边的变更不传输
            （噪声只在 Projection 生成时注入，不在增量同步中出现 —
             噪声种子与 commit_id 绑定，Bob 重新获取 Projection 时
             会自动包含新的噪声模式）
       c. 将过滤后的变更列表转换为操作日志格式:
          → Alice 新增的 Engram → create_engram
          → Alice 修改的 Engram → modify_engram_content / modify_engram_meta
          → Alice 新增的 Nexus → create_nexus
          → Alice 删除的 Engram → delete_engram
          → Alice 的 ClaimRecord 变更 → create_claim / modify_claim
       d. 打包为 SyncOperationLog:

       SyncOperationLog {
         source_did:           DID                 # Alice 的 DID
         target_did:           DID                 # Bob 的 DID
         base_commit_id:       MemoryCommit.id     # 同步起点
         head_commit_id:       MemoryCommit.id     # 同步终点
         projection_hash:      string              # 新 Projection 的 hash
         operations:           [Operation]         # 操作列表（3.15 节格式）
         signature:            Ed25519
       }

    3. Bob 侧重放:
       → Bob 的引擎逐条重放 operations（与 PR 重放流程一致）
       → 与 Bob 本地修改的冲突走 ClaimRecord 检测（6.5 节）
       → 冲突操作需 Bob 审查（或 Diplomat 处理）
       → 非冲突操作自动应用
       → 上游记忆的 strength 按 fork 转换规则降权（6.4 节）

    4. Bob 的 fork_commit 指针更新为 Alice 的 head_commit_id

**噪声边在增量同步中的生命周期**：

    Fork 时 (T0):
      Alice 的 Projection 包含 100 条真实 Nexus + 10 条噪声 Nexus
      Bob 本地 Vault 中有 110 条 Nexus（Bob 不知道哪些是噪声）

    增量同步时 (T1):
      SyncOperationLog 中只有真实 Nexus 的变更（噪声边不在 canonical 中）
      Bob 重放后: 原有 10 条噪声边保持原样，真实 Nexus 正常更新

      噪声边累积的影响:
      - Bob 长期使用且从未 re-fork → 噪声边比例逐渐稀释
        （真实 Nexus 越来越多，噪声边总量不变）
      - Bob re-fork（重新获取完整 Projection）→ 旧噪声被替换为新噪声
      - 噪声边连接的是真实节点但关联关系是虚构的
        → 相当于 Bob 有一些"不太准"的关联，不影响核心功能

### 6.8 社交交互完整示例

    1. Alice 公开了她的 ML 知识记忆库
       alice/ml-knowledge (public, 1.2k engrams)

    2. Bob fork 了 Alice 的库
       bob/ml-knowledge (forked from alice/ml-knowledge)
       -> Alice 的 episodic 变成 Bob 的 learned
       -> strength 打 0.5 折
       -> 隐私记忆被过滤

    3. Bob 在自己的 fork 上学习，产生新记忆
       -> 新的 episodic 记忆（自己做实验的经历）
       -> Alice 的某些 semantic 记忆被 Bob 的新经验 reconsolidate
       -> drift_from_origin 逐渐增大

    4. Bob 发现了 Alice 记忆中的一个错误，提了 PR
       -> MemoryPR: "SGD 收敛条件应该是..."
       -> Alice 审查，发现 Bob 说得对
       -> merge，Alice 的记忆更新

    5. 半年后，Alice 的上游有大量新记忆
       -> Bob sync upstream
       -> 出现冲突：Alice 对 Transformer 的理解更新了
       -> Bob 的版本因为自己的实验经历，再巩固成了不同方向
       -> interactive merge：Bob 逐条决定采纳还是保留自己的

    6. Carol 发现 Bob 的 fork 比 Alice 的原版更好
       -> Carol fork 了 bob/ml-knowledge
       -> 记忆传播网络形成

***

## 第七章：隐私系统

### 7.1 隐私层级

| 层级          | 名称                    | 说明                                                                                             |
| ----------- | --------------------- | ---------------------------------------------------------------------------------------------- |
| **Layer 0** | Core Private (绝对私密)   | 永远不可被 fork，不出现在任何对外接口中。不可导出原文、脱敏摘要、embedding、能力标签中的任何一种。用途：创伤记忆、极私密体验、密码/密钥相关                  |
| **Layer 1** | Sanitized (脱敏可见)      | 对外展示时自动脱敏处理。**不可 fork 原文**——仅允许导出脱敏摘要或能力标签。"和X在Y地争吵关于Z" → "曾有人际冲突经历"。DEK 永不外发                  |
| **Layer 2** | Trusted Circle (圈子可见) | 仅对指定的信任圈开放。可以被圈内人 fork，但带有"不可再传播"标记。DEK 随 fork 传输——**一旦传输即进入"不可全局撤回"模式**，用户在 fork 授权时必须显式确认此风险 |
| **Layer 3** | Public (完全公开)         | 任何人可以 fork。适用于知识、技能、非敏感经验。DEK 公开分发，不可全局撤回                                                      |

**隐私降级的产品边界 (Privacy Degradation Boundary)**：

> "分享后隐私降级"不只是 UI 文案提示，而是必须编码进产品默认行为的硬边界。用户不应能"误操作"成不可逆的隐私暴露。

    不可逆操作的门控:

      Layer 0 → 任何外发操作:
        系统级阻断。不存在"确认后允许"的路径。
        如果用户确实需要分享 Layer 0 内容，必须先手动将其重新分类为 Layer 1+。

      Layer 1 → fork:
        仅允许导出: 脱敏摘要 / 能力标签 / 受限 capability
        不允许导出: 原文 / embedding / revision history
        DEK 不外发。接收方永远无法还原原文。

      Layer 2 → fork (圈内):
        DEK 随 fork 传输。传输前系统弹出不可跳过的确认:
        "此操作将向 [接收方] 传输加密密钥。传输后您仍可请求对方删除，
         但无法强制全球范围内的彻底擦除。确认继续？"
        用户必须输入确认文本（非单击按钮），防止误操作。

      Layer 3 → fork:
        无额外确认（已公开）。

### 7.2 传播控制标记（类似 Creative Commons）

| 标记    | 含义                      |
| ----- | ----------------------- |
| `[F]` | 可 Fork                  |
| `[M]` | 可 Merge 回上游             |
| `[R]` | 可再传播（fork 的 fork）       |
| `[A]` | 需署名原始来源                 |
| `[S]` | 同等条件分享（fork 后必须保持同等开放度） |

示例：`[F][A][S]` = 可 fork，须署名，fork 后须同样开放

### 7.3 Nexus 级联脱敏 (Cascading Desensitization)

**问题：Graph Inference Attack**

图数据库存在经典漏洞：即使隐藏了节点 A（例如某疾病），但 A 连接的节点 B（去某医院的经历）和节点 C（服用某种药物）仍然可见。攻击者通过 B 和 C 的三角拓扑结构和 Nexus 权重，可以反向推断出节点 A 的存在和性质。

**解决方案：**

PrivacyMask 必须同时作用于 Engram（节点）和 Nexus（边）两个维度：

    隐藏前:
      [就医经历 B] ──nexus──> [疾病 A (Layer 0)] <──nexus── [药物 C]
                                  |
                              (被隐藏)

    错误的隐藏（仅隐藏节点）:
      [就医经历 B] ──nexus──> [??? 推断可得] <──nexus── [药物 C]
                       攻击者通过 B+C 反推出 A

    正确的隐藏（级联脱敏）:
      [就医经历 B'] ──(nexus 被剪断)    (nexus 被剪断)── [药物 C']
       降级为 Layer 1                                    降级为 Layer 1
       "曾去过某医疗机构"                                 "曾使用某类药物"

**级联规则：**

*   当一个 Engram 被标记为 Layer 0 / Layer 1 时，所有直连 Nexus 被强制剪断
*   直连邻居节点自动降级一个隐私级别（Layer 3 → Layer 2, Layer 2 → Layer 1）
*   降级的邻居节点在 fork 输出时应用该层级对应的脱敏策略
*   可配置级联深度（默认 1 跳，高敏感场景可设为 2 跳）
*   级联降级不修改原始数据，仅影响 fork/对外呈现时的投影视图

**防止级联过度激进 (Cascade Damping)**：

*   **受影响上限**：单次级联降级影响的邻居节点不超过 `MAX_CASCADE_VICTIMS`（默认 50）。超出时按 Nexus 的 `association_strength` 排序，仅降级关联最强的前 N 个
*   **边类型权重**：不同 Nexus 类型的推断风险不同。`causal` 和 `temporal` 边推断风险高（权重 1.0），`semantic` 边中等（0.5），`spatial` 边低（0.2）。仅对权重超过阈值的边执行级联
*   **dry-run 预览**：用户修改隐私设置时，系统先展示"此操作将影响 N 个关联记忆"的预览，用户确认后才执行
*   **Hub 节点保护**：如果一个 Engram 的连接度 > `HUB_THRESHOLD`（默认 100），级联前强制弹窗警告（防止隐藏一个高连接节点导致 Vault 大面积不可 Fork）

### 7.4 加密粉碎 — 不可变历史与被遗忘权的和解 (Crypto-shredding)

**终极矛盾**：GDPR 要求"彻底删除"，但 Merkle Hash 链不允许篡改历史。联邦网络中 Fork 出去的数据更是鞭长莫及。看似死结。

**核心原则**：

> **永远不要在不可变存储中明文保存敏感内容。**
> **让"删除密钥"等价于"删除数据"。**

**机制**：

    Engram 创建时:

      敏感度判定:
        Layer 0 / Layer 1 的 Engram → 强制加密
        Layer 2 / Layer 3 → 可选加密

      加密流程:
        1. 生成一次性对称密钥 DEK (Data Encryption Key)
        2. 加密: ciphertext = Encrypt(engram.content, DEK)
        3. 存入不可变历史 (Merkle DAG/Snapshot): 只存 ciphertext
        4. DEK 存入独立的本地 Key Store (可变，不参与版本控制)

      存储分离:
        +---------------------------+     +-------------------+
        | 不可变存储 (DAG/Snapshot)  |     | Key Store (可变)   |
        |                           |     |                   |
        | engram_123: {             |     | engram_123: DEK_a |
        |   content: "a7f3...密文"  |     | engram_456: DEK_b |
        |   hash: "3e8c..."        |     | engram_789: DEK_c |
        | }                        |     |                   |
        | (Hash 链完整)             |     | (独立存储，可删除) |
        +---------------------------+     +-------------------+

**行使"被遗忘权"**：

    用户请求删除 engram_123:

      1. 从 Key Store 中删除 DEK_a        ← 核心操作
      2. 所有历史 Snapshot 中的 engram_123 密文瞬间变为不可解密的乱码
      3. Merkle Hash 链完全不受影响（密文未变，Hash 未变）
      4. 同步清除所有派生物（见下方"派生物生命周期"）
      5. 在法律和物理意义上实现了"彻底销毁"

      联邦网络中的 Fork 处理:
      - Fork 时，DEK 随数据一起传输（经过对方公钥加密）
      - 当原作者行使被遗忘权 → 通过 EFP 协议广播 DeleteRequest
      - 各实例收到后删除本地 Key Store 中对应的 DEK + 全部派生物
      - 拒绝执行 DeleteRequest 的实例 → 信任评级下降 → 逐步隔离

**派生物生命周期管理 (Derivative Lifecycle)**：

> 仅删除正文密钥不够——embedding、摘要、聚类标签、Revision diff、LLM prompt/response 日志、只读视图缓存都是可泄露语义的派生物。攻击者可通过向量近邻、抽象摘要或历史 diff 重建被删内容。

    可删除对象的完整清单 (Erasure Manifest):

      engram_123 的 forget()/shred() 触发时，必须原子清除:

      1. content DEK          ← Key Store 删除（正文不可解密）
      2. embedding vector     ← 从向量索引中物理删除该条目
      3. summaries            ← 删除任何以该 Engram 为素材的摘要片段
      4. abstraction refs     ← 如果该 Engram 是某 Semantic Engram 的源素材:
                                 源素材列表中移除引用;
                                 该 Semantic Engram 立即标记为 tainted_pending_redaction:
                                   - 从 View Store 中摘除（recall 不再返回）
                                   - 从 Fork 输出中排除
                                   - 下一个 Epoch 中 LLM 重新评估:
                                     · 剩余源素材仍能支撑结论 → 重写 Semantic 内容,
                                       移除依赖被删素材的部分, 解除 tainted 标记
                                     · 无法支撑 → 标记为 orphaned, 状态迁移至 ARCHIVED
                                     · 用户也可手动确认保留/删除
                                 (不等所有源素材都删光才处理——任一被删源素材
                                  参与生成过的 Semantic 都必须立即停止对外暴露)
      5. revision diffs       ← 所有 Revision 的 content_before/content_after 密文化
                                 (与正文共用同一 DEK，DEK 删除即不可读)
      6. Nexus connections    ← 所有关联的 Nexus 断开并清理（已有规则）
      7. audit/LLM logs       ← 删除包含该 Engram 明文的 prompt/response 日志条目
                                 (审计日志仅保留 "engram_123: SHREDDED at T" 的墓碑记录)
      8. view store cache     ← 从只读视图中移除（下次视图重建时自动排除）
      9. L2 raw entries       ← 如果 BUFFERED 态尚未结构化，删除 L2 流水日志中的原始条目
      10. replica/export cache ← 清除所有已生成的 fork export 缓存中包含该 Engram 的条目

    执行顺序: 2→6→3→4→5→7→8→9→10→1 (最后删 DEK，确保前序步骤可用 DEK 定位密文)
    失败回滚: 任一步骤失败 → 整体回滚，记录为 CognitiveDebt(type: pending_shred)

**Layer 0 / Layer 1 的派生物隔离**：

    预防性规则 (Preventive Rules):

      Layer 0 的 Engram:
        - 禁止进入共享向量索引（使用独立的 private embedding space）
        - 禁止参与聚类和抽象化流程
        - 禁止出现在 LLM prompt 中（Epoch 处理时跳过）
        - Revision diff 强制加密（与正文共用 DEK）

      Layer 1 的 Engram:
        - 向量索引中仅存储脱敏后的 embedding（非原文 embedding）
        - 参与聚类时仅贡献脱敏版本
        - 抽象化产出的 Semantic Engram 不得包含可逆向推断原文的细节
        - LLM prompt 中使用脱敏版本

      原则: 与其事后清除派生物，不如从源头阻止敏感内容进入派生链路。

**保证边界（必须向用户明确声明）**：

*   **保证**：本地不可读性——DEK 删除后，本地所有历史 Snapshot 中的密文永久不可解密，Merkle Hash 链完整不受影响
*   **保证**：结构完整性——粉碎操作不影响系统的任何其他功能
*   **尽力保证**：联邦网络中的撤销——通过 EFP 广播 `DeleteRequest`，合规实例会删除本地 DEK。但恶意实例可能在被降信任/隔离之前已提取 DEK
*   **不保证**：已被 Fork 且 DEK 已传输后的全球擦除——一旦数据离开本实例的控制范围，无法保证全球范围内的彻底删除。这是所有分布式系统的固有限制，与区块链/联邦社交网络面临的问题一致

**与现有设计的整合**：

*   加密粉碎对上层完全透明——觉醒轨道读取时自动解密，用户无感知
*   Tombstone 机制 (5.2 节) + Crypto-shredding 构成双层遗忘保障：Tombstone 隐藏索引，Crypto-shredding 销毁内容
*   Key Store 需要独立备份策略（丢失 DEK = 永久丢失数据，这是有意为之的特性）
*   FORGOTTEN 状态 (Ch14) 是加密粉碎在状态机中的体现——进入 FORGOTTEN 即意味着 DEK 已删除

***

## 第八章：免疫系统（记忆安全）

### 8.1 入口免疫 (Innate Immunity)

*   PR 内容自动扫描：事实核查、一致性检查
*   来源信誉评分：低信誉来源的 PR 自动标记审查
*   异常检测：与现有认知差异过大的记忆触发警告

### 8.2 适应性免疫 (Adaptive Immunity)

*   记忆抗体：曾经被拒绝/标记为有害的记忆模式 → 类似模式再次出现时自动拦截
*   免疫记忆：系统记住攻击模式，下次识别更快
*   交叉免疫：从社交网络中其他人的拒绝记录中学习

### 8.3 自体免疫防护 (Autoimmune Protection)

*   防止过度怀疑导致拒绝所有外部记忆
*   信任校准：定期评估各来源的历史准确率
*   开放性阈值：可调节，过低=封闭，过高=易受攻击

### 8.4 认知疫苗 (Cognitive Vaccine)

*   预接种：对已知的错误信息模式提前标记
*   来源于社区的共享威胁情报

***

## 第九章：集体智能涌现

### 9.1 涌现结构

    Individual         Individual         Individual
     Vaults             Vaults             Vaults
      +-+ +-+ +-+      +-+ +-+           +-+ +-+
      |A| |B| |C|      |D| |E|           |F| |G|
      +-+ +-+ +-+      +-+ +-+           +-+ +-+
       |   |   |        |   |              |   |
       +---+---+        +---+              +---+
           |              |                  |
           v              v                  v
       +-------+     +-------+          +-------+
       | Team  |     | Team  |          | Team  |
       | Vault |     | Vault |          | Vault |
       |  a    |     |  b    |          |  g    |
       +---+---+     +---+---+          +---+---+
           |             |                  |
           +-------------+------------------+
                         |
                         v
                  +------------+
                  |  Org Vault |  <-- 涌现出"组织认知"
                  |            |      没有任何一个人完整拥有
                  |            |      但整体大于部分之和
                  +------------+

### 9.2 涌现分析

| 涌现现象     | 定义                                  | 价值            | 适用范围      |
| -------- | ----------------------------------- | ------------- | --------- |
| **局部趋同** | 同一 canonical 域内多人 fork/merge 后趋同的记忆 | 域内参考信号（非全局真相） | 单实例或互信实例组 |
| **知识缺口** | 组织内所有人都没有覆盖的知识区域                    | 发现团队知识盲点      | 单组织 Vault |
| **观点光谱** | 同一话题存在的不同视角分布                       | 理解分歧的本质       | 单实例       |
| **知识流向** | 记忆在社交网络中的传播路径                       | 识别关键知识节点      | 单实例       |
| **创新交叉** | 原本不相关的记忆在某人的 Vault 中被关联             | 创新和顿悟的来源      | 个人 Vault  |

> **边界说明**：涌现分析仅在 canonical 可见域内有效。跨实例的 projection 数据不能作为涌现分析的输入（见 5.2 节 Projection 语义边界）。"多人趋同"是局部观测信号，不等于"高置信度知识"——趋同可能源于共同偏见。

### 9.3 社交发现

*   **相似发现**：语义空间中距离最近的记忆库
*   **互补发现**：你缺少的知识领域，别人有丰富记忆的
*   **影响力追踪**：追踪一条记忆被 fork 后在网络中的传播和变异（类似学术引用追踪）

***

## 第十章：系统拓扑 — 联邦制架构

### 10.1 为什么选择联邦制

| 方案                                | 问题                                                |
| --------------------------------- | ------------------------------------------------- |
| 完全中心化（GitHub 模式）                  | 记忆是最私密的数据，不应该有单点信任；单点故障 = 所有人失忆                   |
| 完全去中心化（纯 P2P）                     | 发现他人困难，社交功能受限；大规模 diff/merge 性能差                  |
| **联邦制（Mastodon/Matrix/Email 模式）** | 每个人/组织可以自己托管 Vault；实例之间通过协议互联；可以选择信任的实例；数据主权在个人手中 |

### 10.2 架构示意

    +----------+        协议         +----------+
    | Instance |<------------------->| Instance |
    |    A     |   fork / PR /       |    B     |
    |          |   sync / discover   |          |
    | +------+ |                     | +------+ |
    | |User 1| |                     | |User 3| |
    | |User 2| |                     | |User 4| |
    | +------+ |                     | +------+ |
    +-----+----+                     +----+-----+
          |           协议                 |
          |      +----------+             |
          +----->| Instance |<------------+
                 |    C     |
                 | (self-   |
                 |  hosted) |
                 | +------+ |
                 | |User 5| |  <-- 个人自托管
                 | +------+ |
                 +----------+

### 10.3 联邦协议核心能力

| 能力            | 说明                                             |
| ------------- | ---------------------------------------------- |
| **Identity**  | 跨实例身份，基于密钥对。格式：`user@instance.domain`          |
| **Discovery** | 发布可 fork 的 Vault 目录，语义搜索 + 主题分类                |
| **Fork**      | 跨实例 fork，拉取到本地实例，保持 upstream 引用                |
| **PR**        | 跨实例发起 Merge Request，双方审查 + 冲突解决                |
| **Sync**      | upstream 变更通知，增量同步，非全量拉取                       |
| **Trust**     | 实例间互信评级，传递信任：A 信任 B，B 信任 C → A 部分信任 C          |
| **Privacy**   | 跨实例传输时强制执行 PrivacyMask，发送方加密，接收方无法看到 masked 内容 |

***

## 第十一章：系统全景图

    +------------------------------------------------------------------+
    |                         Engram System                             |
    |                                                                   |
    |  +--------------------------------------------------------------+ |
    |  |                      接口层 (API / CLI / UI)                  | |
    |  |  Query:   recall . preview . log . diff . discover . stats   | |
    |  |  Capture: capture                                            | |
    |  |  Command: forget . reinforce . snapshot . restore . rewind   | |
    |  |           branch . merge . fork . pr . sync . subscribe      | |
    |  +------------------------------+-------------------------------+ |
    |                                 |                                 |
    |  +------------------------------+-------------------------------+ |
    |  |                      核心引擎层                               | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  |  | 编码引擎  | | 检索引擎  | | 再巩固引擎  | | 衰减引擎  |      | |
    |  |  | Encoder  | | Retriever| | Reconsoli- | | Decay    |      | |
    |  |  |          | |          | | dator      | | Engine   |      | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  |  | 整合引擎  | | 抽象化   | | 版本引擎    | | 冲突解决  |      | |
    |  |  | Consoli- | | Abstrac- | | Version    | | Conflict |      | |
    |  |  | dator    | | tor      | | Manager    | | Resolver |      | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  +------------------------------+-------------------------------+ |
    |                                 |                                 |
    |  +------------------------------+-------------------------------+ |
    |  |                      社交层                                   | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  |  | Fork     | | PR /     | | Discovery  | | Privacy  |      | |
    |  |  | Manager  | | Merge    | | Service    | | & Trust  |      | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  +------------------------------+-------------------------------+ |
    |                                 |                                 |
    |  +------------------------------+-------------------------------+ |
    |  |                      安全层                                   | |
    |  |  +----------+ +----------+ +------------+                   | |
    |  |  | Immune   | | Audit    | | Encryption |                   | |
    |  |  | System   | | Trail    | | Layer      |                   | |
    |  |  +----------+ +----------+ +------------+                   | |
    |  +------------------------------+-------------------------------+ |
    |                                 |                                 |
    |  +------------------------------+-------------------------------+ |
    |  |                      存储层                                   | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  |  | 向量存储  | | 图存储   | | 文档存储    | | 快照存储  |      | |
    |  |  | Embedding| | Nexus    | | Engram     | | Snapshot |      | |
    |  |  | Index    | | Graph    | | Store      | | DAG      |      | |
    |  |  +----------+ +----------+ +------------+ +----------+      | |
    |  +--------------------------------------------------------------+ |
    |                                                                   |
    |  +--------------------------------------------------------------+ |
    |  |                   联邦协议层                                  | |
    |  |           跨实例通信 . 身份验证 . 增量同步                     | |
    |  +--------------------------------------------------------------+ |
    +------------------------------------------------------------------+

### 存储层职责

*   **向量存储**：存 embedding，用于语义相似度检索（recall 时的 retrieval）
*   **图存储**：存 Engram 之间的关联网络（赫布学习的 Nexus links）
*   **文档存储**：存 Engram 完整数据、Revision Chain
*   **快照存储**：存 MemoryCommit DAG 和增量 diff

***

## 第十二章：三重认知节律 (The Three Cognitive Rhythms)

> 传统软件只有一个时间维度（运行期），但大脑有多个并行的时间节律。
> 系统的复杂性不应该体现在凌乱的互相调用中，而应该被封装在清晰的**节律边界**里。

### 12.1 核心洞察

"极速交互"与"重度计算"必须在架构层面物理隔离。试图在同一条执行路径上同时完成毫秒级响应和 LLM 推理，是导致系统脆弱的根源。

解决方案：将系统运行分为三条独立的时间轨道，每条轨道有严格的职责边界和资源约束。

### 12.2 三轨全景

    时间尺度    毫秒~秒              分钟~小时              日级 / 手动触发
                |                    |                     |
                v                    v                     v
         +-------------+     +----------------+     +-----------------+
         |  觉醒轨道    |     |  潜意识轨道     |     |  睡眠/纪元轨道   |
         |  Awake      |     |  Subconscious  |     |  Sleep/Epoch   |
         |  Track      |     |  Track         |     |  Track         |
         +------+------+     +-------+--------+     +-------+---------+
                |                     |                      |
      极速响应用户交互        静默后台内务管理          重度整合与持久化
      极速返回查询结果        无感知的强化与衰减        LLM 推理与版本提交
                |                     |                      |
         操作对象:              操作对象:               操作对象:
         L1 工作记忆缓冲        L2 流水日志              L3 长期记忆核心库
         + 高速只读视图          + 向量索引聚类           + Snapshot DAG

### 12.3 觉醒轨道 (Awake Track)

**时间尺度**：毫秒 \~ 秒

**职责**：维持工作记忆 (L1)，捕获外部输入，极速响应查询

**硬性约束**：

*   禁止调用 LLM
*   禁止执行 DAG commit
*   禁止直接写入 L3 核心库
*   禁止执行图遍历超过 2 跳

**动作流**：

    Capture 路径 (旧 encode):
      外部输入 --> 轻量 Embedding --> 写入 L2 流水日志 (append-only) --> 返回 CaptureAck
      (无 LLM 参与，仅向量化。非文本输入暂存原始文件 + 排队等待模态转换)

    Recall 路径:
      查询 --> 检索高速只读视图 (向量库 + 图谱快照) --> 返回结果
           \--> 异步抛出 PulseEvent --> 不等待，不阻塞
      (查询结果从只读视图获取，再巩固的副作用延迟到后续轨道)

#### 12.3.1 非文本输入的处理

> 觉醒轨道禁止调用 LLM。非文本输入的模态转换是推理任务，归属于**睡眠轨道**。

    觉醒轨道 (capture 时):
      文本输入 → 直接 Embedding → 写入 L2
      非文本输入 → 存储原始文件到对象存储 → 写入 L2 (仅含 media_ref + modality 标记)
                  不做任何模型推理，仅暂存

    睡眠轨道 (Epoch 期间，Phase 0 — 模态转换，在 Phase 1 结构化之前):
      检测 L2 中 modality != text 的条目
      → 调用模态转换器:
        图像 → 多模态模型生成 text description
        音频 → Whisper 转录
        视频 → 关键帧采样 + 描述
      → 将生成的文本回写到 L2 条目的 content 字段
      → 标记为 modality_resolved
      → 然后正常进入 Phase 1 (LLM 结构化)

      模态转换不可用时: 标记为 CognitiveDebt(type: pending_modality_conversion)
      转换完成前: 非文本记忆仅通过 media_ref 的元数据可被检索（降级但不丢失）

**设计要点**：

*   Engram 的 `content` 字段**最终始终是文本**（多模态模型生成的描述）
*   原始媒体通过 `media_ref` 引用，需要时可回溯查看原始图片/音频
*   衰减、再巩固、抽象化——所有核心引擎只处理文本，无需为多模态做任何修改
*   **模态转换归属睡眠轨道**（Whisper、多模态模型都是推理任务，与 LLM 结构化同属重度计算）
*   潜意识轨道的"纯数学、无推理模型、资源极低"约束不被破坏
*   转换完成前，非文本记忆仅通过 media\_ref 的元数据可被检索（降级但不丢失）

**程序性记忆的局限性说明**：

> 将所有模态统一为文本对知识类记忆有效，但对真正的 procedural skill（如编程手感、调试直觉、操作流程的肌肉记忆）会有损失——文本描述"如何骑自行车"和真正会骑是两回事。

    当前版本的妥协:
      - procedural 类型的 Engram 允许保留 executable_ref 字段:
        · 代码片段 → media_ref 指向可执行的代码文件/snippet
        · 操作流程 → media_ref 指向录屏/步骤截图序列
        · content 仍为文本描述（用于检索和抽象化）
      - procedural Engram 的抽象化策略不同于 episodic:
        · 不做内容压缩（"5 次调试经历 → 1 条调试方法论"）
        · 而是提取 pattern（"每次都是先查日志 → 检查配置 → 重启服务"）
        · 原始步骤序列保留在 media_ref 中，不丢弃

    未来扩展方向 (非 MVP 范围):
      - 引入 SkillGraph: 程序性记忆的专用子图，节点是 step/action，
        边是 sequence/condition，支持流程回放和变体比较

**L2 热缓存视图 (Hot Buffer View)**：

> capture() 后的内容在下一个 Epoch 前不会成为正式 Engram，也不出现在 recall() 结果中。对"记忆系统"来说，用户刚记下一件事随后就查不到，会认为系统"没记住"。

    解法: 为 BUFFERED 态提供弱查询能力

      L2 Hot Buffer View:
        - 与只读视图（View Store）并列的轻量级索引
        - capture() 写入 L2 时，同步将 embedding 写入 Hot Buffer Index
        - Hot Buffer Index 是临时的、非权威的、仅本地可用的

      recall() 的增强行为:
        1. 首先查询 View Store (CONSOLIDATED 态，权威结果)
        2. 其次查询 Hot Buffer Index (BUFFERED 态，补充结果)
        3. BUFFERED 结果带有显式标记:
           { status: "buffered", provisional: true, message: "尚未整合，内容可能在下次 Epoch 后变化" }
        4. 排序时 BUFFERED 结果降权（排在 CONSOLIDATED 之后）
        5. BUFFERED 结果不触发 PulseEvent（不参与再巩固）

      Epoch 完成后:
        - 已结构化的条目从 Hot Buffer Index 中移除
        - 被丢弃的噪声条目也从 Hot Buffer Index 中移除
        - Hot Buffer Index 重置

      约束:
        - Hot Buffer Index 不参与聚类、抽象化、Nexus 建立
        - Hot Buffer Index 不出现在 Fork 输出中
        - Hot Buffer Index 仅支持向量相似度检索，不支持图遍历

      幽灵数据防护 (Ghost Data Protection):
        - provisional 记忆可能在 Epoch 后被丢弃 (T2: 判定为噪声)
        - 如果 Agent 已基于 provisional 记忆执行了物理动作 (代码修改/架构决策)
          → 该动作的支撑记忆凭空消失，因果链断裂
        - 防护规则:
          · provisional 结果在返回时附带显式警告:
            "此记忆尚未整合，可能在下次 Epoch 后被丢弃，不应作为关键决策的唯一依据"
          · Agent 指令文件中必须声明:
            "带 provisional:true 的记忆仅作为背景参考，不可作为架构决策的核心依据"
          · 如果 Agent 基于 provisional 记忆做了重要操作，应同时 capture 该决策本身
            → 即使原始 provisional 被丢弃，决策记录仍然存在

**脑科学映射**：清醒状态下的即时反应——你回答问题时不需要等大脑完成"这段记忆要因为被回忆而强化"的后台处理。刚听到的话虽然还没"记住"，但你能立刻回忆起"刚才有人说了什么"。

### 12.4 潜意识轨道 (Subconscious Track)

**时间尺度**：分钟 \~ 小时

**职责**：处理觉醒轨道抛出的碎片事件，执行不影响主线的内务管理

**硬性约束**：

*   运行在独立后台守护进程
*   资源占用极低（纯数学运算，无 LLM）
*   不生成新的 Engram 版本
*   不修改 L3 核心库

**动作流**：

    消费 PulseEvent (分工明确，两条支路):
      从事件队列读取 -->
        支路 A: 写入 Delta Ledger
                { engram_id, delta_type: reinforce, delta_value: +X, timestamp }
                (strength 变更的唯一入口，与衰减 delta 写同一个 Ledger)
        支路 B: 写入 Reconsolidation Buffer
                { engram_id, query_context, coactivated_pairs, timestamp }
                (仅记录上下文和共激活信息，用于 Epoch 生成 Revision 和 Nexus 调整)
                (Buffer 不产生任何 strength 变更)
      (两者均持久化为本地 append-only WAL 文件，非纯内存
       每个 PulseEvent 携带 idempotency_key，防止崩溃恢复时重放)

    持续衰减计算:
      遍历活跃 Engram 索引 --> 计算 strength delta --> 写入 Delta Ledger
                           --> 标记低于阈值的为 pending_archive
      (惰性求值：只计算近期被访问过的 Engram，冷数据跳过)

    聚类监控:
      向量空间 KNN 扫描 --> 发现相似情景记忆聚类
                        --> 簇内成员数 >= 阈值 --> 打上 pending_abstraction 标签
      (纯数学，不涉及 LLM)

**Strength 唯一权威源 (Canonical Strength)**：

> 潜意识轨道计算衰减和强化，但它不能直接修改 L3 中的最终 strength 值，否则 Query（读旧视图的 strength）和 Command（潜意识改的 strength）会产生双重真相。

    解法: Delta Ledger 模式

      潜意识轨道:
        - 只能向 Delta Ledger (append-only WAL) 写入 strength 变更记录:
          { engram_id, delta_type: decay|reinforce, delta_value: -0.02, timestamp }
        - 不能直接修改任何 Engram 的 strength 字段
        - pending_archive 标记也是"建议"，不是最终判定

      睡眠轨道 (Epoch):
        - 读取 Delta Ledger 中 seal_timestamp 之前的所有记录
        - 折叠 (fold) 为每个 Engram 的净 strength 变更
        - 在 L3 Truth Store 中原子更新最终 strength 值
        - 重建只读视图时写入新的 strength

      觉醒轨道:
        - 读取只读视图中的 strength（来自上一次 Epoch 的结果）
        - 可选: 用 Delta Ledger 中的暂存值做内存补偿（显示近似实时值）
        - 但补偿值不参与任何业务判断（排序、阈值比较等仍用视图中的值）

      唯一权威源: L3 Truth Store 中的 strength 字段
      唯一有权修改者: 睡眠轨道

**脑科学映射**：白天的潜意识处理——你不会意识到大脑在后台默默地强化/弱化各种记忆连接。

### 12.5 睡眠/纪元轨道 (Sleep/Epoch Track)

**时间尺度**：日级 / 手动触发

**职责**：执行 LLM 重度推理、生成语义概念、解决冲突、提交全局 Snapshot

**硬性约束**：

*   在系统空闲时运行（类似手机夜间充电时备份）
*   **唯一有权限修改 L3 核心库的轨道**
*   唯一有权限调用 LLM 和推理模型的轨道（抽象化、再巩固、冲突解决、模态转换）
*   唯一有权限执行 DAG commit 的轨道

**动作流**：

    Phase 0 - 模态转换 (见 12.3.1):
      检测 L2 中 modality != text 的条目
      → 调用推理模型 (Whisper / 多模态模型) 转换为文本
      → 回写 L2 的 content 字段，标记 modality_resolved
      → 转换失败 → CognitiveDebt(type: pending_modality_conversion)

    Phase 1 - 抽取与再巩固:
      读取 L2 流水日志 --> LLM 结构化为正式 Episodic Engram
                       --> 对比 L3 现有记忆，执行再巩固（受 rigidity 约束）
      消费 Delta Ledger  --> 折叠为每个 Engram 的净 strength 变更 --> 写入 L3
                            (strength 的唯一写入路径)
      消费 Recon Buffer  --> 生成 Revision 记录 + 调整 Nexus 权重
                            (不改 strength，仅产出内容/关联变更)

    Phase 2 - 抽象化 (顿悟):
      读取 pending_abstraction 标签的记忆簇
      --> LLM 将多条情景记忆压缩为一条 Semantic Engram
      --> 原始情景记忆 strength 降低，状态迁移为 abstracted

    Phase 3 - 清理与归档:
      处理 pending_archive 标记 --> 迁移到冷存储
      执行 Nexus 网络优化 --> 发现潜在关联（"顿悟"）

    Phase 4 - 持久化与快照 (两阶段提交):
      ┌─ Prepare Phase ─────────────────────────────────────────────┐
      │ 4a. 生成 StagingManifest:                                    │
      │     - 本次 Epoch 的所有变更清单 (Engram diff + Nexus diff)    │
      │     - 预计算的向量索引增量                                     │
      │     - 预计算的图谱变更                                        │
      │     - 新的 strength 值快照                                    │
      │     - manifest_hash = hash(所有变更)                          │
      │ 4b. 写入 staging 目录 (独立于所有正式存储)                      │
      │ 4c. fsync 确保 StagingManifest 持久化                         │
      └──────────────────────────────────────────────────────────────┘
      ┌─ Commit Phase (原子切换) ────────────────────────────────────┐
      │ 4d. 按顺序写入各存储:                                         │
      │     DAG commit (Truth Store) → 向量索引重建 → 图谱更新        │
      │     → SQLite Nexus 表更新                                     │
      │ 4e. 写入 active_view_pointer → 指向新视图                     │
      │     (觉醒轨道在此瞬间原子切换到新视图)                          │
      │ 4f. 删除 StagingManifest (标记 Epoch 完成)                    │
      └──────────────────────────────────────────────────────────────┘

      崩溃恢复:
        - 如果在 Prepare Phase 崩溃 → staging 目录存在但不完整
          → 下次 Epoch 启动时检测到 → 丢弃 staging，重新执行 Epoch
        - 如果在 Commit Phase 崩溃 → staging 完整，部分存储已写入
          → 下次启动时检测到完整的 StagingManifest → 从断点恢复:
            按 manifest 重放未完成的写入 → 完成 active_view_pointer 切换
        - active_view_pointer 是唯一的"事实成功标志":
          指向旧视图 = Epoch 未生效，指向新视图 = Epoch 已完成

      --> 执行历史 Snapshot 的 Tombstone 压缩 (在 Commit Phase 之后)

**脑科学映射**：睡眠期间的记忆整合——海马体将白天的经历重放并固化到新皮层，同时进行突触修剪和记忆重组。

### 12.6 三轨交互协议

    觉醒轨道                    潜意识轨道                  睡眠轨道
        |                           |                          |
        |--- Pulse Event ---------> |                          |
        |    (异步，不等待)           |                          |
        |                           |                          |
        |                           |--- pending_abstraction -->|
        |                           |--- pending_archive ------>|
        |                           |--- Recon Buffer --------->|
        |                           |    (Epoch 开始时移交)      |
        |                           |                          |
        |                           |                          |--- 重建只读视图
        |<------------------------------------------------------|
        |    (Epoch 结束后，觉醒轨道                              |
        |     切换到新的只读视图)                                  |
        |                           |                          |

**关键不变量 (Invariants)**：

1.  觉醒轨道**永远不等待**其他轨道
2.  三条轨道之间**仅通过事件和标签通信**，无直接函数调用
3.  L3 核心库的写锁**仅在 Epoch 期间被睡眠轨道持有**
4.  只读视图的切换是**原子操作**——觉醒轨道要么看到旧视图，要么看到新视图，不存在中间态

### 12.8 Epoch 并发控制 — 密封窗口语义 (Sealed Window)

> 如果用户在 Epoch 运行期间手动触发 snapshot()，或两个 worker 同时启动 Epoch，会怎样？
> 没有并发控制的 Epoch 是定时炸弹。

**问题场景**：

*   用户在定时 Epoch 运行中手动触发 `snapshot()`
*   两个进程同时尝试启动 Epoch
*   Epoch 运行中用户执行 `restore()` / `rewind()` / `merge()`
*   潜意识轨道仍有未消费的 PulseEvent 时 Epoch 开始

**解法：Epoch 租约 + 密封时间戳**

    Epoch 启动流程:

    1. 尝试获取 Epoch Lease (排他锁)
       - 每个 Vault 同一时刻只允许一个活跃 Epoch 租约
       - 如果已有活跃 Epoch → 拒绝启动，返回 "epoch_in_progress"
       - 租约有超时（防止死锁）: 默认 1 小时（v0.5.0 实现值，避免长时间 Epoch 误过期）

    2. 设定密封时间戳 seal_timestamp = now()
       - Epoch N 只处理 seal_timestamp 之前产生的:
         · L2 流水日志条目
         · PulseEvent
         · Reconsolidation Buffer 内容
         · pending_* 标签
       - seal_timestamp 之后的所有事件属于 Epoch N+1

    3. 执行 Epoch (Phase 1-4)
       - 觉醒轨道在此期间继续正常工作:
         · capture() 继续追加 L2 (这些条目时间戳 > seal_timestamp，不被当前 Epoch 处理)
         · recall() 继续使用上一次 commit 的只读视图
       - 命令队列中的 snapshot()/restore()/merge() 排队等待当前 Epoch 完成后执行

    4. 提交 & 释放租约
       - 生成 MemoryCommit
       - 原子切换只读视图
       - 释放 Epoch Lease
       - 处理排队的命令

**关键规则**：

*   **密封不可变**：一旦 seal\_timestamp 设定，当前 Epoch 的输入集就固定了。不会因为 Epoch 运行时间长而"追加"新事件
*   **租约超时**：如果 Epoch 异常中断（崩溃），租约自动过期，下次 Epoch 可以重新开始。未完成的 Epoch 不产生 commit，所有中间状态丢弃
*   **命令排队与语义绑定**：Epoch 期间收到的 Command API 调用进入 FIFO 队列，但必须绑定语义锚点：



    CommandEnvelope {
      command:              Command              # snapshot / restore / merge / rewind 等
      enqueued_at:          timestamp            # 入队时间
      intent_timestamp:     timestamp            # 用户意图时间点 = enqueued_at
      base_commit_id:       MemoryCommit.id      # 用户发起命令时的 HEAD commit

      # 执行时校验:
      #   如果 base_commit_id != 当前 HEAD (Epoch 产生了新 commit):
      #     snapshot() → 基于 base_commit_id 的状态生成快照 (而非当前 HEAD)
      #     restore()  → 仍可执行 (语义不变: 回到指定 commit)
      #     rewind()   → 需要用户重新确认 (Epoch 后状态已变化)
      #     merge()    → 基于 base_commit_id 重新计算 diff，可能产生新冲突
    }

这确保用户在 10:00 点击 snapshot()，即使 10:20 Epoch 结束后才执行，快照的仍是 10:00 时的逻辑状态

***

### 12.7 认知债务池 — 离线与弱算力降级策略 (Cognitive Debt Pool)

> 人在极度疲劳或高压下，也能经历事情，只是"没过脑子"。
> 系统在断网/弱算力环境下的行为应该与此一致。

**问题**：睡眠轨道重度依赖 LLM（结构化、抽象化、再巩固内容修改）。如果本地设备无法运行大模型，或网络不可用，Epoch 怎么办？

**解法：引入"认知债务"概念**

    系统状态检测:
      if LLM 可用 (本地 Ollama / 远程 API):
        → 正常 Epoch (Full Sleep)
      else:
        → 降级 Epoch (Light Sleep)

**降级 Epoch (Light Sleep) — 只做能做的事**：

    正常 Epoch (Full Sleep):                降级 Epoch (Light Sleep):
      Phase 1: LLM 结构化 L2 日志      →     跳过，L2 原始日志打包存档
      Phase 2: LLM 抽象化              →     跳过，pending 标签保留
      Phase 3: 衰减 + 清理             →     正常执行（纯数学，不需要 LLM）
      Phase 4: DAG commit              →     正常执行，但 Snapshot 标记为
                                              "degraded" (含未处理的认知债务)

**认知债务的数据结构**：

    CognitiveDebt {
      debt_id:              UUID
      created_at:           timestamp
      type:                 pending_consolidation |    # L2 日志未结构化
                            pending_abstraction |      # 聚类未被 LLM 提炼
                            pending_reconsolidation    # 再巩固内容未更新
      raw_data:             reference                  # 指向未处理的原始数据
      priority:             float                      # 基于数据量和紧迫性
      accumulated_epochs:   int                        # 已积压了多少个 Epoch
    }

**债务清偿：两种模式**：

    模式 A: Deep Sleep（深度睡眠）— 集中清偿

      触发条件:
        - 设备接入高速网络 + 外部算力可用
        - 或用户手动触发 "deep_sleep()"
        - 或认知债务累积超过 DEBT_CEILING（强制提醒用户）

      执行流程:
        1. 按时间顺序回放所有 pending_consolidation 的 L2 日志
           → LLM 批量结构化为 Engram
        2. 处理所有 pending_abstraction 的聚类
           → LLM 批量抽象化
        3. 处理所有 pending_reconsolidation
           → 按积压的 Pulse Event 批量再巩固
        4. 生成一个特殊的 "Deep Sleep Commit"
           → 一次性清偿所有认知债务

    模式 B: Micro-batching（流式微批处理）— 化整为零 [推荐]

      > Deep Sleep 对低配设备不现实。积累 3 天数百条记录的集中处理
      > 可能需要跑 12 小时，设备发热严重，用户会放弃使用系统。

      触发条件:
        - 后台守护进程持续监测 CPU 闲置率
        - 闲置率 > 80% 时开始处理，< 50% 时暂停
        - 每次只处理 1-2 条认知债务

      执行流程:
        1. 从 CognitiveDebt 队列取优先级最高的 1 条
        2. 执行单条 LLM 处理 (结构化 / 抽象化 / 再巩固)
        3. 写入结果，标记该 debt 为 resolved
        4. 如果 CPU 仍空闲 → 取下一条；否则 → 暂停等待

      优势:
        - 算力开销平摊到全天的空闲时段
        - 用户无感知（不会出现"系统正在处理，请等待 12 小时"）
        - 即使设备性能差，只要有碎片空闲时间就能逐步清偿
        - 不需要专门的"周末补觉"，债务持续、渐进地消化

      约束:
        - 每条 micro-batch 的处理必须是原子的（处理到一半崩溃不会污染数据）
        - 处理顺序按 priority 排序，不必严格按时间顺序
        - 每次处理后立即更新 View Store（增量更新，非全量重建）

      与 Deep Sleep 的关系:
        - Micro-batching 是默认模式
        - Deep Sleep 作为手动兜底：用户可以显式触发 deep_sleep() 清偿全部残余
        - 如果 Micro-batching 运行良好，用户可能永远不需要 Deep Sleep

**降级期间的用户体验保障**：

*   觉醒轨道**完全不受影响**——recall 依然使用只读视图极速响应
*   潜意识轨道**完全不受影响**——衰减、聚类都是纯数学
*   唯一的影响：新输入的内容暂时不会变成正式的 Engram，但可通过 Hot Buffer View 以降权 provisional 结果出现在 recall 中（见 12.3 节）
*   系统 `stats()` 中显示 `cognitive_debt_count`，用户可感知积压状态

***

## 第十三章：认知 CQRS 模式 (Cognitive CQRS)

> 在 Engram 中，读和写是两种完全不同的认知过程。
> 查询是有意识的瞬间反应，修改是无意识的延迟处理。

### 13.1 为什么需要 CQRS

传统数据库的 CRUD 模型假设读写发生在同一个数据结构上。但 Engram 系统有一个根本性矛盾：

| 维度    | 查询 (Query)  | 命令 (Command)   |
| ----- | ----------- | -------------- |
| 时效要求  | 亚毫秒         | 可延迟数小时         |
| 数据一致性 | 允许最终一致      | 需要强一致          |
| 频率    | 极高 (100x/s) | 极低 (1x/day 批量) |
| 计算复杂度 | 轻量（向量检索）    | 重度（LLM + 图遍历）  |
| 所在轨道  | 觉醒轨道        | 睡眠轨道           |

强行在同一模型上同时满足这两种需求，必然导致要么查询变慢，要么写入丢失。CQRS 模式将两者彻底分离。

### 13.2 双模型架构

    [用户 / Agent 查询]
          |
          v
    +----------------------------+    快速读取    +---------------------------+
    |  查询模型 (Query Model)     | <------------ | 高速只读视图 (View Store) |
    |                            |               |                           |
    |  - 内存中的工作记忆 (L1)    |               |  - 向量索引 (Embedding)    |
    |  - 只读图谱快照             |               |  - 只读图谱副本            |
    |  - 无任何写操作             |               |  - 物化的 strength 值      |
    +-------------+--------------+               +-----------^---------------+
                  |                                           |
                  | 异步抛出                                    | 重建
                  | Pulse Event                               | (Epoch 结束时)
                  v                                           |
    +----------------------------+    重度写入    +---------------------------+
    |  命令模型 (Command Model)   | ------------> | 核心真相库 (Truth Store)   |
    |                            |               |                           |
    |  - 再巩固引擎               |               |  - Engram 完整数据         |
    |  - 衰减引擎                |               |  - Revision Chain         |
    |  - 抽象化引擎 (LLM)         |               |  - Nexus 完整图谱          |
    |  - 版本引擎       |               |  - Snapshot DAG           |
    +----------------------------+               +---------------------------+

### 13.3 数据流向

    写入方向 (Command Path):
      外部输入 --> L2 流水日志 --> [Epoch] --> 命令模型处理 --> Truth Store 更新

    读取方向 (Query Path):
      查询请求 --> View Store (只读) --> 返回结果

    视图同步 (View Rebuild):
      [Epoch 结束] --> Truth Store --> 重建 View Store --> 原子切换

### 13.4 最终一致性窗口

View Store 和 Truth Store 之间存在一个**最终一致性窗口**——从觉醒轨道的视角看，记忆的 strength 值、Nexus 权重等可能滞后一个 Epoch 周期。

**这是特性，不是缺陷。**

*   人类的大脑也是如此：你不会实时感知到"这段记忆刚刚因为被回忆而变强了 0.03"
*   查询结果的**语义正确性**不受影响（内容不变），只有**元数据精度**略有滞后
*   对于需要即时反馈的场景（如 reinforcement\_count 的显示），可以用 Reconsolidation Buffer 中的暂存值做内存补偿

### 13.5 CQRS 与三轨的映射

    觉醒轨道    →  纯 Query Model  (只读，极速)
    潜意识轨道  →  Event 预处理层   (聚合、标记，不落盘)
    睡眠轨道    →  纯 Command Model (重写，批量)

CQRS 是三重节律在数据访问模式上的自然投影。两者不是独立的设计，而是同一个洞察的两个面。

***

## 第十四章：Engram 状态机 (Engram State Machine)

> 一条记忆在系统中的生命周期是一个**单向状态机**。
> 状态机让转换规则变得显式、可审计、不可违反。

### 14.1 五态模型

> 注：早期设计曾称"六态"，将 [丢弃] 计为独立状态。正式定义中 [丢弃] 是 T2 转换的结果（不入库），不是持久状态。五个持久状态：BUFFERED / CONSOLIDATED / ABSTRACTED / ARCHIVED / FORGOTTEN。

       capture()                      Epoch 整合                     聚类抽象
      +---------+    L2 日志 LLM 结构化    +---------------+    LLM 提炼    +------------+
      | BUFFERED|------------------------->| CONSOLIDATED  |-------------->| ABSTRACTED |
      | (缓冲态) |                          | (巩固态)       |               | (被抽象态)  |
      +---------+                          +-------+-------+               +-----+------+
           |                                       |                             |
           | Epoch 判定为                    +------+------+                      |
           | 噪声/碎片                       |             |                      |
           v                          strength    forget()                strength
        [丢弃]                         跌破阈值    或 shred()               跌破阈值
                                         |             |                      |
                                         v             v                      v
                                  +------------+  +------------+        +----------+
                                  | ARCHIVED   |  | FORGOTTEN  |        | ARCHIVED |
                                  | (归档/休眠) |  | (终态)     |        |          |
                                  +-----+------+  +------------+        +----------+
                                        |
                                        | 深度唤醒 (用户确认)
                                        v
                                  CONSOLIDATED

      冷启动旁路 (Ch18):
      +---------+    直接入库    +---------------+
      | 外部数据 |-------------->| CONSOLIDATED  |  (跳过 BUFFERED)
      +---------+               +---------------+
           |    重复主题直接    +------------+
           +------------------->| ABSTRACTED |        (跳过 CONSOLIDATED)
                                +------------+

      漂移统计 (仅观测，不自动执行):
      ForkedEngram 的 drift_from_origin 持续累积（仅供用户参考）
      自动断裂 (Genesis) 已从主路线移除——归属判定需人类治理

### 14.2 各状态详解

| 状态               | 存储位置                       | 可被检索                                                                          | 可被再巩固                     | 可被 Fork                 | 说明                                                         |
| ---------------- | -------------------------- | ----------------------------------------------------------------------------- | ------------------------- | ----------------------- | ---------------------------------------------------------- |
| **BUFFERED**     | L2 流水日志 + Hot Buffer Index | 弱可查（recall 可命中但降权，标记 provisional，仅本地可见，不触发 PulseEvent。见 12.3 Hot Buffer View） | 否                         | 否                       | 原始输入，未经 LLM 结构化。类比：刚听到的话还没"记住"，但能立刻回忆起"刚才有人说了什么"           |
| **CONSOLIDATED** | L3 核心库 + 只读视图              | 是                                                                             | 是（受 rigidity 约束）          | 是                       | 标准的长期记忆。系统中的"一等公民"                                         |
| **ABSTRACTED**   | L3 核心库（降权）                 | 仅作为 Semantic Engram 的支撑证据间接引用                                                 | 否（rigidity 自动设为 1.0，内容冻结） | 否（仅衍生的 Semantic 可 fork） | 已被提炼为更高维概念的原始素材                                            |
| **ARCHIVED**     | 冷存储 / DAG 历史 + 墓碑索引        | 否（需深度唤醒，但墓碑索引可命中）                                                             | 否                         | 否                       | 被系统"遗忘"，不在主索引和视图中，但保留极小型墓碑索引供唤醒路径发现                        |
| **FORGOTTEN**    | 仅 DAG 历史中的密文残留             | 否                                                                             | 否                         | 否                       | **终态**。对应 `forget()` 显式遗忘或 `shred()` 加密粉碎。DEK 已删除，内容永久不可恢复 |

### 14.3 完整状态转换规则

| #       | 转换                                  | 触发条件                                    | 执行轨道           | 可逆性                      |
| ------- | ----------------------------------- | --------------------------------------- | -------------- | ------------------------ |
| T1      | BUFFERED → CONSOLIDATED             | Epoch 整合，LLM 结构化成功                      | 睡眠轨道           | 不可逆                      |
| T2      | BUFFERED → \[丢弃]                    | Epoch 判定为噪声/碎片                          | 睡眠轨道           | 永久丢失（无 DAG 记录）           |
| T3      | BUFFERED → CONSOLIDATED (冷启动)       | 摄入管道直接入库                                | 睡眠轨道 (离线)      | 不可逆                      |
| T4      | BUFFERED → ABSTRACTED (冷启动)         | 摄入管道检测到重复主题                             | 睡眠轨道 (离线)      | 不可逆                      |
| T5      | CONSOLIDATED → ABSTRACTED           | 聚类阈值 + LLM 生成 Semantic Engram           | 睡眠轨道           | 不可逆                      |
| T6      | CONSOLIDATED → ARCHIVED             | strength 跌破 `ARCHIVE_THRESHOLD`         | 睡眠轨道           | **可逆** (T9)              |
| T7      | CONSOLIDATED → FORGOTTEN            | `forget(soft=false)` 或 `shred()` (加密粉碎) | 睡眠轨道           | **不可逆**                  |
| T8      | ABSTRACTED → ARCHIVED               | 衍生 Semantic 也衰减后，支撑价值消失                 | 睡眠轨道           | 可逆 (T9)                  |
| T9      | ARCHIVED → CONSOLIDATED             | 深度唤醒：精确搜索命中 + 用户显式确认                    | 手动触发 (经睡眠轨道执行) | -                        |
| T10     | ARCHIVED → FORGOTTEN                | 冷存储清理或用户显式删除                            | 睡眠轨道           | 不可逆                      |
| ~~T11~~ | ~~ForkedEngram → Engram (Genesis)~~ | ~~drift > DRIFT\_RUPTURE\_THRESHOLD~~   | ~~已从主路线移除~~    | ~~归属自动判定需人类治理，不做系统自动执行~~ |

### 14.4 状态机的保护性约束

**不变量 (Invariants)**：

1.  **FORGOTTEN 是吸收态**：任何进入 FORGOTTEN 的 Engram 永远不能回到任何其他状态
2.  **轨道约束**：只有睡眠轨道有权执行状态转换。觉醒轨道和潜意识轨道**永远不能改变** Engram 的状态
3.  **原子性**：状态转换与 MemoryCommit 绑定——转换要么完整记录在 Snapshot 中，要么完全不发生
4.  **可审计性**：每次状态转换都记录在 Engram 的 Revision Chain 中，包括转换编号 (T1-T10)、触发原因和时间戳
5.  **密封窗口约束** (见 12.8 节)：状态转换只处理密封时间戳之前的数据

**防御性规则**：

*   BUFFERED 态的数据**永远不会出现在** Fork 输出中；在 Query API (recall) 中可作为 provisional 降权结果返回（仅本地可见，不触发 PulseEvent，见 12.3 Hot Buffer View）
*   ARCHIVED 态的数据**不占用**主向量索引和图谱只读视图的空间（性能保护），但保留墓碑索引（见下方）
*   ABSTRACTED 态的 Engram 的 `rigidity` 自动设为 1.0（内容冻结），但允许追加反证层（见下方）
*   FORGOTTEN 态的 Engram 的所有 Nexus 连接自动断开并清理

**ARCHIVED 墓碑索引 (Archive Tombstone Index)**：

> ARCHIVED 不在主索引中，但如果完全从检索层消失，系统无法知道该去唤醒哪条记忆。

    ArchiveTombstone {
      engram_id:            UUID
      archived_at:          timestamp
      original_type:        episodic | semantic | procedural
      time_range:           [created_at, last_accessed_at]  # 活跃时间跨度
      topic_summary:        string (< 100 chars)            # 极简主题摘要
      entity_tags:          [string]                        # 关键实体 (人名、概念、地点)
      original_strength:    float                           # 归档前的 strength
      wake_hint_embedding:  vector (低维, 64d)              # 压缩后的 embedding (非全精度)
    }

    存储: 独立的轻量级 SQLite 表 (不在 View Store 中)
    大小: 每条约 500 bytes，10 万条 ARCHIVED 仅占 ~50MB

    唤醒搜索路径:
      1. 用户查询未在 View Store 命中足够结果
      2. 系统自动降级搜索 Archive Tombstone Index:
         - wake_hint_embedding 做粗粒度相似度匹配
         - entity_tags 做关键词匹配
         - time_range 做时间范围过滤
      3. 候选墓碑展示给用户:
         "找到 3 条已归档的相关记忆: [主题摘要]，是否唤醒？"
      4. 用户确认 → 从冷存储加载完整 Engram → 执行 T9 (ARCHIVED → CONSOLIDATED)

**ABSTRACTED 反证层 (Counter-Evidence Layer)**：

> 将 ABSTRACTED 的 rigidity 设为 1.0 完全冻结内容，会导致早期抽象错误无法纠偏。更合理的是"内容冻结但可追加反证"。

    ABSTRACTED 态的修正规则:

      content: 冻结 (rigidity = 1.0，不可修改原始抽象内容)

      但允许:
      1. 追加 counter_evidence Nexus:
         - 类型: contradiction | refinement | superseded_by
         - 指向: 新的 CONSOLIDATED 或 ABSTRACTED Engram
         - 语义: "此抽象结论已被新证据质疑/修正/替代"

      2. 追加 confidence_override:
         - 当积累足够多 contradiction Nexus 时
         - ABSTRACTED Engram 的 effective_confidence 自动降低
         - effective_confidence = original_confidence × (1 - contradiction_weight)

      3. 触发重新抽象:
         - 当 effective_confidence < REABSTRACTION_THRESHOLD (默认 0.3):
           → 标记为 pending_reabstraction
           → 下一个 Epoch 中 LLM 重新评估:
             收集所有相关 CONSOLIDATED 记忆 + 反证
             → 生成新的 Semantic Engram (替代旧的)
             → 旧 ABSTRACTED 记为 superseded，状态迁移到 ARCHIVED

      效果: 抽象内容有稳定性（不会被随意修改），但有纠偏通道（不会永远错下去）

### 14.5 状态机与三轨、CQRS 的统一视图

                          觉醒轨道 (Query + Capture)
                               |
              Query: 只能看到 CONSOLIDATED 态的只读视图
              Capture: 只能追加 BUFFERED 态到 L2
                               |
      -------- PulseEvent -----+---- pending 标签 ----
                               |                     |
                          潜意识轨道                   |
                        (Event 预处理)                 |
                               |                     |
      ---- Recon Buffer -------+---- 标签聚合 --------
                               |
                          睡眠轨道 (Command)
                               |
              唯一有权执行状态转换的轨道 (T1-T10)
                               |
        +-------+----------+----------+----------+
        |       |          |          |          |
     BUFFERED  CONSOL.   ABSTRACTED  ARCHIVED  FORGOTTEN
     →T1,T3,T4 →T5,T6,T7  →T8        →T9,T10   (吸收态)
     →T2(丢弃)

三轨节律、CQRS 模式、状态机——三者不是三个独立的设计，而是**同一个架构洞察的三个投影**：

| 投影维度 | 回答的问题                  |
| ---- | ---------------------- |
| 三重节律 | **何时**处理？（时间边界）        |
| CQRS | **怎样**处理？（读写分离）        |
| 状态机  | 处理的**对象**处于什么阶段？（生命周期） |

***

## 第十五章：对外 API 总览

API 按 CQRS 模式分为三类，严格对齐三轨边界。

### Query API（觉醒轨道 — 同步，纯读，亚毫秒）

    # 查询与检索（View Store + Hot Buffer View，BUFFERED 结果标记 provisional）
    recall(query, context)                       -> [Engram]
      # 数据源: View Store (CONSOLIDATED, 权威) + Hot Buffer Index (BUFFERED, 降权)
      # BUFFERED 结果: provisional=true, 不触发 PulseEvent, 不出现在 Fork 输出中
      # CONSOLIDATED 结果: 隐式副作用 → 异步抛出 PulseEvent，不阻塞返回

    # 版本查看（只读）
    log(since?, until?)                          -> [MemoryCommit]
    diff(commit_a, commit_b)                     -> [EngramDiff]
    preview(commit_id)                           -> MemoryState    # 只读历史快照预览
                                                                   # 不触发再巩固，不改变活跃视图

    # 社交发现
    discover(query, mode?)                       -> [VaultRef]

    # 系统状态
    stats()                                      -> MemoryStats

### Capture API（觉醒轨道 — 同步，仅追加 L2，不入 L3）

    # 记忆捕获（写入 L2 流水日志，不触发 LLM，不入核心库）
    capture(content, context, emotion?)          -> CaptureAck
      # 写入 L2 append-only 日志
      # 返回 capture_id（非 Engram UUID，Epoch 结构化后才分配 UUID）
      # 这是觉醒轨道唯一的写操作，且仅写 L2

### Command API（睡眠轨道 — 异步，写入 L3，Epoch 内执行）

    # 显式操作（排入命令队列，Epoch 内执行）
    forget(engram_id, soft=true)                 -> CommandAck
    reinforce(engram_id)                         -> CommandAck

    # 版本管理
    snapshot(message?)                           -> MemoryCommit
    branch(name, from_commit?)                   -> MemoryBranch
    merge(branch_a, branch_b, strategy?)         -> MemoryCommit
    pin(commit_id)                               -> void
    restore(commit_id)                           -> MemoryState    # 切换活跃视图，触发再巩固
    rewind(commit_id)                            -> MemoryState    # 破坏性回退，需确认

    # 社交操作
    fork(source_vault, options?)                 -> MemoryVault
    pr(source_vault, target_vault, operation_log) -> MemoryPR
                                                    # 提交操作日志（3.14 节），非快照 diff
    sync_upstream(vault)                         -> SyncOperationLog
                                                    # 返回操作日志（6.7 节），非快照 diff
    subscribe(vault_id)                          -> Subscription
    trace_influence(engram_id)                   -> InfluenceGraph

### 设计说明

*   **三类 API 严格对齐三轨**：Query = 觉醒轨道纯读，Capture = 觉醒轨道仅追加 L2，Command = 睡眠轨道写 L3
*   **旧 `encode()` 拆分为两阶段**：`capture()` 在觉醒轨道同步写 L2（用户立即得到确认），`consolidate` 在 Epoch 内由睡眠轨道自动执行（L2 → L3 结构化），用户无需显式调用
*   **旧 `restore()` 拆分为两个动词**：`preview()` 是 Query（只读查看历史快照），`restore()` 是 Command（真正切换活跃视图并触发再巩固）
*   `recall()` 对调用者而言是**纯 Query**——再巩固副作用完全封装在异步 PulseEvent 中
*   所有 Command API 返回 `CommandAck`（确认已入队），实际执行在下一个 Epoch

***

## 第十六章：与现有系统的关系定位

                            社交协作能力
                                ^
                                |
                       GitHub   |          Engram
                         *      |            *
                                |
                                |
             VCS *              |
                                |
      --------------------------+-----------------------------> 记忆/认知建模能力
                                |
                  Obsidian *    |       Mem0 *
                                |
                      Notion *  |    MemGPT *
                                |
                                |

Engram 的独特位置：**既有完整的版本管理 + 社交协作能力，又有脑科学启发的活性记忆模型**。目前没有任何系统占据这个位置。

***

## 第十七章：工程约束与架构修正

> 本章记录从理想化设计到可落地工程之间必须解决的核心矛盾，以及对应的修正方案。

### 17.1 哈希链不可变性 vs 记忆衰减（Merkle Tree 保护）

**矛盾**：设计哲学要求 Snapshot "像记忆一样衰减压缩"，但 Snapshot 构成的 DAG 底层是 Merkle Hash 链。修改任何历史节点会导致后续所有 Hash 失效，在联邦网络中引发所有下游 Fork 的上游引用断裂——这是毁灭性的。

**修正原则**：

> **底层不可变，表现层可衰减。衰减是索引操作，不是数据操作。**

**方案：墓碑机制 (Tombstone) + 冷热分层**

*   历史 Snapshot 的完整数据（Hash、diff、元信息）永久保持不可变
*   "压缩"通过在 HEAD 提交 `PruneInstruction` 实现，将旧 Snapshot 的索引指针标记为 tombstone
*   Tombstone 化的数据迁移至冷存储 (Archive Layer)，热存储中仅保留摘要
*   任何时刻都可以从冷存储中"唤醒"完整历史（代价较高但可行）
*   联邦网络中的其他节点可以独立验证任意 Hash，因为底层数据从未被修改

**脑科学对应**：这恰好更符合大脑的真实机制——记忆并非真正"删除"，而是提取路径断开（类似索引 tombstone），在特定刺激下仍可能被唤醒。

### 17.2 读放大灾难 vs "读即写"（I/O 性能保护）

**矛盾**：再巩固机制要求每次 `recall()` 都触发写入（更新 strength、生成 Revision、调整 Nexus 权重）。真实系统中读写比为 100:1，如果 AI Agent 每秒检索 10 次记忆，数据库会被写操作锁死。

**修正原则**：

> **调用层面读写分离。recall() 是纯函数，再巩固是异步批处理。**

**方案：再巩固缓冲池 (Reconsolidation Buffer)**

    用户/Agent 调用 recall()
            |
            v
      +------------------+
      | 检索引擎          |  ← 纯读，无副作用，亚毫秒响应
      | (向量 + 图查询)   |
      +--------+---------+
               |
               | 同时写入（仅内存操作，极快）
               v
      +------------------+
      | Reconsolidation  |  ← 内存中的环形缓冲区
      | Buffer           |  ← 记录：哪条记忆、何时、什么上下文被激活
      +--------+---------+
               |
               | 异步刷写（Epoch 期间 / 缓冲区满时 / 定时批量）
               v
      +------------------+
      | 批量写入引擎       |
      | - strength 更新   |
      | - Revision 生成   |
      | - Nexus 权重调整  |
      | - 赫布学习计算     |
      +------------------+

**关键细节**：

*   Delta Ledger 中同一 Engram 的多条 reinforce delta 在 Epoch 折叠时合并：recall 10 次 → 折叠为 1 次净 strength 变更 + reinforcement\_count += 10
*   如果系统崩溃，Delta Ledger / Recon Buffer 的 WAL 文件支持崩溃恢复；最坏情况丢失最后几条未 fsync 的事件（可接受）
*   对外 API 语义不变：`recall()` 返回的结果中 strength 可以用 Delta Ledger 中的暂存值做内存补偿，用户感知不到延迟写入

### 17.3 记忆漂移失控 vs 核心事实保护（刚性参数）

**矛盾**：再巩固机制让所有记忆都会漂移，但某些记忆**绝对不能漂移**——银行卡密码、过敏信息、法律条款、物理常数。如果这些也被"当前上下文重染"，后果不堪设想。

**修正原则**：

> **记忆的可塑性不是二元的，是一个连续光谱。引入 `rigidity` 参数作为再巩固的刹车。**

**方案：Engram.rigidity 参数**

    rigidity 值    含义                       再巩固行为
    ────────────────────────────────────────────────────────────
    0.0 ~ 0.2     高度可塑                   完全允许内容修改
                   (昨天聚会的气氛)           drift 无上限

    0.2 ~ 0.5     中等可塑                   允许轻微修改
                   (某次技术讨论的要点)        drift 限速

    0.5 ~ 0.8     低可塑                     仅允许添加关联 (Nexus)
                   (教科书上的定理)            内容本身不可改

    0.8 ~ 1.0     近乎刚性                   完全冻结内容
                   (密码、过敏源、法律事实)     仅允许 strength 变化

**刚性来源**：

*   系统自动推断：带有 `procedural` 标签的安全关键记忆自动设高刚性
*   用户手动设定：用户可以 `pin` 某条记忆的 rigidity
*   Fork 继承：从上游 fork 来的高刚性记忆，保持其刚性值
*   类型默认值：`semantic` (事实) 默认 0.5，`episodic` (经历) 默认 0.15，`procedural` (技能/安全) 默认 0.7

**再巩固引擎中的刚性检查**：

    if engram.rigidity > RIGIDITY_CONTENT_LOCK_THRESHOLD (0.5):
        # 拒绝修改 content，仅允许：
        # - strength 更新
        # - 新增 Nexus 关联
        # - encoding_context 补充
        skip content reconsolidation
    else:
        # 允许再巩固修改 content
        # 但修改幅度受 rigidity 约束：
        max_drift_per_recall = (1.0 - rigidity) * MAX_DRIFT_STEP
        apply bounded reconsolidation

### 17.4 图推断攻击 vs 隐私保护（级联脱敏）

**矛盾**：PrivacyMask 作用于 Engram（节点），但图数据库的拓扑结构本身就在泄露信息。隐藏了"疾病 A"，但"去某医院 B"和"吃某种药 C"仍然可见，攻击者通过 B-C 的关联结构和权重可以反推出 A。

**修正原则**：

> **隐私保护必须同时作用于节点和边。隐藏一个节点时，其邻域拓扑也必须被扰动。**

**方案：Nexus 级联脱敏 (Cascading Desensitization)**

*   详见 7.3 节
*   核心：当节点被标记为 Layer 0/1 时，所有直连 Nexus 剪断，邻居节点自动降级一个隐私级别
*   级联深度可配置（默认 1 跳）
*   不修改原始数据，仅影响 fork 输出时的投影视图

**补充防御：拓扑噪声注入**

*   在 fork 输出的关联网络中，随机注入少量虚假 Nexus（噪声边）
*   噪声边的权重和类型与真实边统计分布一致
*   攻击者无法区分真实关联和噪声关联，图推断攻击的准确率大幅下降
*   噪声比例可调（默认 5\~10%），过高会影响 fork 质量

### 17.5 合并冲突地狱 vs 用户体验（认知外交官）

**矛盾**：长时间未同步的 Fork 与上游 diff 可能产生数百条差异。让用户逐条 interactive merge 是不可接受的——用户会直接放弃使用系统。

**修正原则**：

> **用户只应处理真正重要的冲突。90%+ 的差异应由系统自动、静默、正确地处理。**

**方案：认知外交官代理 (Cognitive Diplomat Agent)**

*   详见 6.6.1 节
*   核心：LLM 驱动的预处理层，在合并前对所有差异做 dry-run 分流
*   按 `emotional_intensity` + `rigidity` + 冲突性质三维分流
*   自动融合（~85%）+ 静默忽略（~10%）+ 升级人工（\~5%）
*   每次自动融合的决策都记录审计日志，用户事后可查看和回滚

### 17.6 抽象化方法：混合架构（已确定方案）

**问题**：情景→语义抽象化是用 LLM 做摘要提炼，还是纯统计聚类？

**确定方案：两阶段混合架构**

    Stage 1: 纯数学聚类（持续后台运行，低成本）
            |
            | 向量数据库持续做 KNN 聚类
            | 监控每个聚类簇的成员数量
            |
            v
      聚类簇内相似情景记忆 >= ABSTRACTION_THRESHOLD (例: 5 条)
            |
            | 触发中断
            v
    Stage 2: LLM 摘要提炼（按需唤醒，精准但昂贵）
            |
            | LLM 将 5 条情景记忆压缩为 1 条语义记忆
            | 提取共性模式、核心要点、因果关系
            |
            v
      新的 Semantic Engram 入库
      原始 Episodic Engram 强度降低 (× DETAIL_FADE_FACTOR)

**成本控制**：

*   Stage 1 是纯向量运算，成本极低，可持续运行
*   Stage 2 的 LLM 调用仅在聚类超过阈值时触发，预计每个 Epoch 只有少量触发
*   可配置 LLM 的模型级别：日常用轻量模型（如 Haiku），重要聚类用高能力模型（如 Opus）

***

## 第十八章：冷启动 — 前世记忆摄入管道 (Past-Life Ingestion Pipeline)

> 没有用户会愿意面对一个"失忆"的新系统。
> 如果用户有 5 年的 Obsidian 笔记、10 年的聊天记录、2 万条推文，系统必须能把这些消化掉。

### 18.1 为什么不能走常规流程

常规路径 `BUFFERED → (Epoch) → CONSOLIDATED` 的前提是：输入是实时的、碎片化的、需要 LLM 结构化的。但冷启动的数据特征完全不同：

| 维度   | 实时输入   | 冷启动数据                      |
| ---- | ------ | -------------------------- |
| 量级   | 单条     | 数万\~数十万条                   |
| 结构   | 非结构化片段 | 已有结构（Markdown / JSON / 对话） |
| 时间信息 | 当前时刻   | 跨越数年                       |
| 元数据  | 需要现场采集 | 需要逆向推断                     |

冷启动数据必须走一条**旁路管道**，直接生产 `CONSOLIDATED` 甚至 `ABSTRACTED` 态的 Engram。

### 18.2 摄入管道架构

                     +------------------+
                     | 外部数据源        |
                     | Obsidian / 微信   |
                     | Twitter / Notion  |
                     | 浏览器历史 / Email |
                     +--------+---------+
                              |
                         (1) 适配器层
                         Source Adapters
                              |
                              v
                     +------------------+
                     | 统一中间表示      |
                     | (Raw Document)   |
                     +--------+---------+
                              |
                         (2) 元数据逆向推断
                         Metadata Inference
                              |
                              v
                     +------------------+
                     | 带元数据的文档     |
                     | (Enriched Doc)   |
                     +--------+---------+
                              |
                         (3) LLM 批量结构化
                         Batch Structuring
                              |
                              v
                     +------------------+
                     | Engram 候选集     |
                     | (Draft Engrams)  |
                     +--------+---------+
                              |
                         (4) 去重与关联建立
                         Dedup & Linking
                              |
                              v
                     +------------------+
                     | 入库 & 初始快照    |
                     | (Inception Commit)|
                     +------------------+

### 18.3 各阶段详解

**(1) 适配器层 (Source Adapters)**

每种数据源一个适配器，输出统一的 Raw Document 格式：

    RawDocument {
      source_type:          obsidian | wechat | twitter | notion | browser | email
      content:              string
      created_at:           timestamp | null
      modified_at:          timestamp | null
      modification_count:   int | null         # 如果数据源能提供
      tags:                 [string] | null
      linked_documents:     [ref] | null       # 内部链接（如 Obsidian wiki links）
      conversation_context: string | null      # 对话类数据的上下文
    }

**(2) 元数据逆向推断 (Metadata Inference)**

冷启动的核心难题：历史数据没有 strength、rigidity、emotional\_intensity。需要逆向推断：

    推断规则:

    strength 初始值:
      = f(修改次数, 最近访问时间, 内容长度)
      - 修改次数越多 → strength 越高（说明用户反复关注）
      - 最近修改时间越近 → strength 越高
      - 从未修改过的5年前笔记 → strength 很低，可能直接进入 ARCHIVED

    reinforcement_count:
      = modification_count (如果数据源提供)
      = estimated from version history (Obsidian/Notion 有版本记录)
      = 1 (无法推断时的默认值)

    rigidity:
      - 含有 #密码 #安全 #法律 #医疗 等标签 → 0.9
      - 代码片段 / 技术文档 → 0.6
      - 日记 / 随笔 / 对话 → 0.15
      - LLM 辅助推断：对内容做分类，判断是事实记录还是主观感受

    emotional_intensity:
      - LLM 情感分析：对每条内容做情感极性和强度打分
      - 聊天记录中的感叹号、大写、表情符号密度作为辅助信号
      - 日记类内容的情感通常高于技术笔记

    decay_rate:
      - 基于 type 和 rigidity 自动设定
      - 冷启动数据的 decay_rate 初始偏高（因为缺乏真实的强化历史）

**(3) LLM 批量结构化 (Batch Structuring)**

    处理策略:

    单条笔记 → 通常生成 1 条 Episodic 或 Semantic Engram
      - 短笔记（< 200 字）: 直接作为一条 Engram
      - 长笔记（> 1000 字）: LLM 拆分为多条原子 Engram

    对话记录 → 生成多条 Engram + Nexus
      - 每个话题转折点切分
      - 对话中的结论/决策提取为独立的 Semantic Engram

    高频重复主题 → 直接生成 ABSTRACTED + Semantic
      - 如果 5 篇笔记都在讨论"React 性能优化"
      - 直接生成 1 条 Semantic Engram + 5 条 ABSTRACTED 态的原始 Episodic
      - 跳过 CONSOLIDATED 态（它们已经"被整合过"了）

    LLM 选型:
      - 大批量用轻量模型（Haiku 级）: 结构化、分类、情感分析
      - 抽象化用重度模型（Opus 级）: 跨文档主题提炼
      - 可并行处理，吞吐量优先

**(4) 去重与关联建立 (Dedup & Linking)**

    去重:
      - episodic 类型: 向量相似度 > 0.95 的 Engram 可自动合并
      - semantic / fact 类型: 向量相似度 > 0.95 仅标记为候选，
        必须经 LLM 确认语义等价后才合并
        （高维 Embedding 空间中，结构相似但关键值不同的句子
         如"使用单引号" vs "使用双引号"相似度可能 > 0.95，
         自动合并会吞掉关键配置差异）
      - 保留 strength 更高的版本
      - 来自不同数据源的同一事件（笔记 + 聊天同时提到）合并后 strength 增强

    关联建立 (Nexus):
      - Obsidian 的 wiki links → 直接映射为 semantic 类型 Nexus
      - 时间相近（同一天/同一小时）的 Engram → temporal 类型 Nexus
      - LLM 推断因果关系 → causal 类型 Nexus
      - 共享标签 → semantic 类型 Nexus（弱关联）

### 18.4 创世快照 (Inception Commit)

冷启动完成后，生成系统的第一个 Snapshot：

    MemoryCommit {
      commit_id:    "genesis"
      trigger:      "cold_start"
      message:      "Past-Life Ingestion: {N} engrams from {sources}"
      stats: {
        total_engrams:      N
        by_status:          { consolidated: X, abstracted: Y, archived: Z }
        by_source:          { obsidian: A, wechat: B, twitter: C }
        avg_strength:       0.45   # 冷启动数据的平均强度偏低
      }
    }

**重要约束**：Inception Commit 之后，系统立即触发一次完整的 Epoch 周期，对冷启动数据进行第一轮整合——补充 LLM 未发现的潜在关联、执行首次衰减计算、生成初始的聚类标签。

### 18.5 冷启动安全约束 (Cold Start Safety Rails)

> 冷启动旁路允许数据直接进入 CONSOLIDATED 甚至 ABSTRACTED 态，绕过了正常的渐进整合流程。LLM 一次性把多年笔记错误抽象为高刚性语义记忆，后续系统会围绕这个错误继续强化，形成"错误基石"效应。

    冷启动安全默认值:

      所有冷启动导入的 Engram:
        strength:           最高 0.5 (无论推断值多高)
        confidence:         最高 0.6 (未经系统内验证)
        rigidity:           最高 0.4 (禁止直接设为高刚性)
        status_tag:         cold_start_unverified   # 特殊标签，区别于正常入库

      冷启动直接生成的 ABSTRACTED:
        rigidity:           固定 0.3 (非常低，允许后续纠偏)
        confidence:         固定 0.4
        requires_validation: true                   # 标记为"待验证语义"

    验证提升机制 (Validation Promotion):

      冷启动数据不会永远低权:
      1. 用户通过 recall() 激活冷启动记忆 → strength 按正常再巩固规则增长
      2. 冷启动记忆在 Merge 冲突中被保留 → confidence += 0.1
      3. 冷启动的 ABSTRACTED 经过至少 3 个 Epoch 的验证:
         - 无 contradiction Nexus 累积 → confidence 提升至正常水平
         - 有 contradiction → 触发重新抽象 (18.5 → 14.4 反证层)
      4. 经过验证的记忆移除 cold_start_unverified 标签

      原则: 冷启动数据以"待验证假说"的身份入库，
            通过使用和时间逐步升级为"确认知识"。
            与其信任一次性 LLM 判断，不如让系统自身的
            再巩固和衰减机制去验证和筛选。

***

## 第十九章：记忆主权 — 忒修斯之船与漂移断裂 ⚠️ 已降格为研究备忘

> **本章已从主路线移除。** drift 统计仍保留为观测指标，但自动断裂 (Genesis)、权利分配表、反博弈设计均不纳入实现计划。归属判定是法律/伦理/社区治理问题，不能由 LLM 概率模型自动裁决。以下内容保留为研究备忘，供未来独立研究项目参考。

> 当组成这艘船的木板全部被替换，它还是原来那艘船吗？
> 当一条 Fork 来的记忆经过无数次再巩固，原作者还有署名权吗？

### 19.1 问题的本质

在传统版权体系中，"原创"和"衍生"有清晰的边界。但 Engram 的再巩固机制让这个边界变得模糊——每次回忆都在修改记忆，drift 持续累积。这不是 bug，这是系统的核心特性。

我们需要一个**连续的、可量化的主权过渡模型**，而不是二元的"是/否"判断。

### 19.2 Drift 的度量 — 多信号融合

纯语义相似度度量存在根本缺陷：

| 场景                | 语义相似度    | 实际含义变化    |
| ----------------- | -------- | --------- |
| 翻译成另一种语言          | 低（表面差异大） | 无变化       |
| 改写措辞但保留观点         | 中（表面变化）  | 无变化       |
| 关键事实取反（"有效"→"无效"） | 高（大部分相同） | **根本性变化** |

因此 drift 必须采用**多信号融合**：

    drift_from_origin 的计算 (每次 Reconsolidation 时由 LLM 在 Epoch 评估):

      signals = {
        semantic_distance:    1.0 - semantic_similarity(current, origin)     # 权重 0.2
        entity_retention:     1.0 - overlap(entities(current), entities(origin))  # 权重 0.3
        assertion_alignment:  contradiction_score(assertions(current), assertions(origin))  # 权重 0.35
        transformation_type:  classify(translation | summary | rewrite | contradiction)     # 调节系数
      }

      # 翻译/摘要类变换 → transformation_discount = 0.3 (大幅降低 drift)
      # 事实矛盾类变换 → transformation_amplifier = 1.5 (放大 drift)

      drift_from_origin = weighted_sum(signals) * transformation_factor

      # 范围 [0, 1]
      # 0.0 = 与原始内容完全一致
      # 0.5 = 实质性变化，但核心主张尚在
      # 0.8 = 核心主张已反转或面目全非 → 触发断裂预警

**关键设计**：

*   `entity_retention`：提取关键实体（人名、概念、数值），检测保留率
*   `assertion_alignment`：提取核心断言/主张，检测是否矛盾或反转（最关键信号）
*   `transformation_type`：识别变换的性质——翻译/摘要不应增加 drift，事实反转应大幅增加
*   drift 评估在 Epoch 期间由 LLM 执行（非实时计算）

### 19.3 漂移断裂机制 (Drift Rupture)

    drift_from_origin 的连续光谱:

      0.0         0.3           0.5           0.8          1.0
       |-----------|-------------|-------------|------------|
       完全一致     轻微演化       实质性变化     面目全非      完全无关
       |           |             |             |
       全额归属     署名+注释      共同归属       断裂 (Genesis)
       原作者       "基于X的       "受X启发,      origin 切断
                   观点演化"       由Y发展"       成为原生记忆

**断裂时发生什么**：

1.  `origin` 链接被切断，替换为 `genesis_event` 记录
2.  原始溯源信息降级为只读的历史归档（可查但不再活跃）
3.  该 Engram 从原作者的 `trace_influence()` 统计中移除
4.  如果该 Engram 已被他人 Fork，其下游 Fork 的 origin 指向当前 Vault（而非原始作者）

**断裂前的人工确认**：

*   drift > 0.6 时：系统发出**预警**，标记为 `drift_warning`（信息性，不阻断）
*   drift > 0.8 时：系统生成**断裂提案**，需用户显式确认才执行 Genesis
*   用户可以选择：确认断裂 / 驳回（手动降低 drift）/ 与上游 sync 消除漂移
*   这防止了因 LLM drift 评估偏差导致的错误断裂

**脑科学对应**：这就像知识的内化过程——你读了一本书，最初能清晰记得"这是某某说的"，但经过多年的思考和实践，这些观点已经与你自己的经验融合，变成了"你自己的想法"。这是正常的认知演化。

### 19.4 主权光谱上的权利分配

| drift 范围   | 归属状态 | 原作者权利                | 当前持有者权利      |
| ---------- | ---- | -------------------- | ------------ |
| 0.0 \~ 0.3 | 全额归属 | 完整署名权 + 影响力统计 + 传播控制 | 使用权 + 再巩固权   |
| 0.3 \~ 0.5 | 共同归属 | 署名权（"基于X"）+ 部分影响力统计  | 内容修改权 + 再传播权 |
| 0.5 \~ 0.8 | 弱归属  | 历史溯源可查（"受X启发"）       | 近乎完整的主权      |
| > 0.8      | 断裂   | 无（仅历史归档）             | 完全主权，视为原生记忆  |

### 19.5 反博弈设计

**防止恶意加速漂移**：如果有人故意对 Fork 来的记忆做无意义的反复再巩固来加速 drift、逃避归属：

*   drift 的增量必须来自**语义层面的真实变化**，不是形式上的修改
*   每次 drift 增量由 LLM 判定语义差异是否真实（Epoch 期间执行）
*   如果检测到 drift 增量与实际语义变化不匹配，标记为 `suspicious_drift`，该 Engram 的 drift 进度冻结

***

## 第二十章：Agent 记忆 — AI 作为记忆系统的一等公民

> AI Agent 不是记忆系统的用户，它就是记忆系统的原住民。

### 20.1 Agent 作为 MemoryOwner

AI Agent 在系统中享有与人类用户完全相同的身份地位：

    MemoryOwner {
      id:                   UUID
      type:                 human | agent
      display_name:         string
      identity_key:         PublicKey          # 密钥对身份

      # Agent 特有字段
      agent_config: {
        model:              string             # 底层 LLM 型号
        epoch_trigger:      EpochTriggerPolicy # 见 20.2
        autonomy_level:     float [0, 1]       # 自治程度
      } | null                                 # 人类用户为 null
    }

Agent 可以：

*   拥有自己的 Vault
*   Fork 人类或其他 Agent 的 Vault
*   向人类或 Agent 发起 PR
*   被人类或 Agent Fork
*   参与集体记忆的涌现

### 20.2 Agent 的认知节律差异

人类的三轨节律由生物钟驱动（白天觉醒/夜间睡眠）。Agent 没有生物钟，其 Epoch 触发策略完全不同：

    EpochTriggerPolicy {
      mode:                 task_based | budget_based | interval_based | hybrid

      # task_based: 完成一次复杂 Task 后触发 Epoch
      task_completion_trigger: bool

      # budget_based: 消耗了 N 个 token 后触发 Epoch
      token_budget_per_epoch: int

      # interval_based: 每 N 分钟/小时触发
      interval:             duration

      # hybrid: 以上条件任一满足即触发
    }

**示例场景**：

    人类用户 Alice:
      觉醒轨道: 工作时间 (9am ~ 11pm)
      睡眠轨道: 每天凌晨 3am 自动 Epoch
      节律: 固定，由生物钟驱动

    Agent Bob (Alice 的 AI 助手):
      觉醒轨道: 7x24 持续运行
      睡眠轨道: 每完成一个 Task 触发 mini-Epoch
                或每消耗 100k token 触发 full-Epoch
      节律: 弹性，由算力和任务驱动

### 20.3 Agent 记忆的特殊规则

| 维度           | 人类                 | Agent                                     |
| ------------ | ------------------ | ----------------------------------------- |
| 情绪标记         | 真实情绪               | 无真实情绪，但可以继承 Fork 来源的情绪标记作为元数据             |
| 遗忘曲线         | Ebbinghaus 生物衰减    | 可配置的衰减函数（可以更慢甚至关闭衰减，用于知识库型 Agent）         |
| 工作记忆容量       | \~7 个 Engram       | 等于 context window 大小，可远大于人类               |
| 再巩固          | 受当前情绪和情境影响         | 纯基于语义相关性，无情绪偏差                            |
| rigidity 默认值 | 因类型而异              | 整体偏高（Agent 应该更忠于事实，较少主观漂移）                |
| Fork 时的类型转换  | episodic → learned | Agent 没有"亲历"的概念，所有记忆都是 learned 或 semantic |

**Agent 幻觉防护 (Hallucination Guard)**：

> Agent 的错误认知一旦入库，会被再巩固机制无限放大。Agent 幻觉 capture 了一条错误信息 → 后续 recall 命中 → strength 增长 → 更容易被 recall → 更多强化。这是一个正反馈死循环，最终幻觉变成 Vault 中坚不可摧的"高强度基石记忆"。

    防护机制: origin 标记 + verified 门控 + strength 硬上限

      Engram 新增字段:
        origin:     human | agent         # 写入者身份
        verified:   bool (默认 false)     # 是否经过人类验证

      写入规则:
        人类通过 CLI / UI 直接写入:
          origin = 'human', verified = true
        Agent 自动 capture:
          origin = 'agent', verified = false

      strength 固定上限:
        if origin == 'agent' AND verified == false:
          AGENT_UNVERIFIED_CAP = 0.5                # 固定常量

          # ⚠️ 设计说明 — 为什么不用动态公式:
          #
          # 曾考虑过 cap = lerp(0.4, 0.7, 1.0 - verified_ratio)，
          # 但该公式存在"倒挂悖论":
          #   - 用户越勤奋验证 (verified_ratio → 1.0) → cap 越低 (0.4)
          #   - 用户越摆烂 (verified_ratio → 0.0) → cap 越高 (0.7)
          # 效果是惩罚勤奋用户、放任摆烂用户，与设计意图相悖。
          #
          # 固定 0.5 的优势:
          #   - 已验证记忆上限 1.0，未验证上限 0.5 → 明确的 2:1 优先级
          #   - 纯 Agent Vault 中，未验证记忆之间通过 access_count 和
          #     衰减自然产生区分度，不需要动态 cap
          #   - 简单、可预测、无反直觉行为
          #
          # v0.2 如有需要，可引入更精细的策略（如按 type 分级 cap）

          strength 增长上限 = AGENT_UNVERIFIED_CAP
          # 保证: 未验证记忆上限 (0.5) < 已验证记忆上限 (1.0)

      验证提升:
        以下行为将 Agent 记忆标记为 verified = true，解除 strength 上限:
        - 用户显式确认: engram verify <id>
        - 用户对 Agent 基于该记忆的输出表示认可 (如 Code Review 接受)
        - 另一条 human origin 的记忆与其内容一致 (交叉验证)

      验证降级:
        - 用户纠正 Agent 时，被纠正的记忆 strength 直接降至 0.1
        - 连续 N 次 recall 后未被采纳的 Agent 记忆 → 自然衰减更快

### 20.4 人机协作记忆模式

    Alice (Human)                          Agent-A (Alice 的 AI 助手)
      Vault: alice/personal                  Vault: agent-a/workspace
        |                                      |
        |------ Fork (selective) ------------->|  Alice 共享工作知识给 Agent
        |                                      |
        |                                      |-- Agent 执行任务,产生新记忆
        |                                      |-- Agent 完成 Task, 触发 Epoch
        |                                      |-- Agent 整理出结论
        |                                      |
        |<----- PR (研究结果) -----------------|  Agent 将成果 PR 回 Alice
        |                                      |
        | Alice 审查,merge                     |
        | Alice 的知识因此增长                   |

### 20.5 Agent 接入层架构 (Agent Integration Layer)

> Ch20.1-20.4 定义了 Agent 的身份和节律，但没有回答：Claude Code / Codex / Gemini CLI **怎么连上** Engram？
> 接入层的设计目标：让 AI Agent 像使用自己的长期记忆一样使用 Engram——无需理解底层三轨/CQRS/状态机，只需调用几个语义清晰的工具。

#### 20.5.1 接入层全景

    +-------------------------------------------------------------+
    |  AI Agent Runtime                                            |
    |  (Claude Code / Codex / Gemini CLI / 任意 LLM Agent)         |
    |                                                              |
    |  Context Window = L1 工作记忆                                 |
    |  (Agent 自身的 context 就是 Engram 的工作记忆缓冲区)            |
    +---------------------------+----------------------------------+
                                |
                        Tool/Function Calls
                                |
    +---------------------------v----------------------------------+
    |  Engram Agent SDK (适配层)                                    |
    |                                                              |
    |  +------------------+  +------------------+  +--------------+|
    |  | CLI Tool         |  | MCP Server       |  | OpenAI Func  ||
    |  | (v0.1 全 Agent   |  | (v0.3 Claude Code|  | Schema       ||
    |  |  通用接入)        |  |  原生接入)        |  | (v0.5)       ||
    |  +--------+---------+  +--------+---------+  +------+-------+|
    |           |                     |                    |        |
    |           +---------------------+--------------------+        |
    |                                 |                             |
    |                    统一 Agent API 层                           |
    |           (session / recall / capture / status)               |
    +---------------------------+----------------------------------+
                                |
                       Engram Core (Ch3-19 定义的完整引擎)

#### 20.5.2 统一 Agent API — 7 个工具

无论底层用 MCP、Function Calling 还是 CLI，Agent 看到的是同一组语义工具（v0.2 新增 `ingest_observation` 为一级入口，见 23.2.1.2）：

    # ═══════════════════════════════════════════════════════
    # Session 生命周期
    # ═══════════════════════════════════════════════════════

    engram_session_start(project_context?, task_description?)
      → { session_id, priming_memories: [Engram{layer?}], project_conventions: [Engram] }

      触发时机: Agent 会话/任务开始时
      行为:
        1. 创建 session 记录 (关联 Agent DID + 项目路径)
        2. 自动 priming: 基于 project_context + task_description 执行三层上下文注入
        3. 返回 priming_memories:
           - L0 Identity: preference / convention，按 raw strength 选取，保证身份与核心约定始终在场
           - L1 Core: decision / fact / insight，按 effective_strength 选取，强调近期仍有效的核心知识
           - L2 Context: 基于 query 的 task-relevant recall，填充剩余预算
        4. priming 带 project boundary：当前项目可见“本项目 + 全局”记忆；无项目会话仅拉取全局记忆，避免跨项目污染
        5. 返回的每条 priming memory 可带可选 `layer` 字段，供 MCP prompt 和调试消费方使用
        6. 返回 project_conventions: 用户偏好、编码规范、架构决策等高 rigidity 记忆

    engram_session_end(session_id, outcome?, summary?)
      → { session_id, status, captures_count, observations_count }

      触发时机: Agent 会话/任务结束时
      行为:
        1. summary 存入 sessions.summary（一等字段，不落 engrams）
        2. 统计本次会话事件数（captures / observations）
        3. 关闭 session 记录
        4. 返回 None 如果 session_id 不存在或已结束

      ⚠️ v0.2 与远期设计的差异:
        - v0.2: session_end 不自动 capture outcome/learnings，不触发 Epoch
          长期记忆由调用方显式 capture，session_summary 不污染 engrams 层
        - v0.5+: 引入 EpochTriggerPolicy 后，session_end 可自动触发 mini-Epoch
          learnings 参数届时恢复，自动 capture 为独立 Engram

    # ═══════════════════════════════════════════════════════
    # 记忆操作 (映射到 Ch15 API)
    # ═══════════════════════════════════════════════════════

    engram_recall(query, scope?, max_results?)
      → [{ content, type, strength, source, provisional }]

      映射: Ch15 Query API → recall()
      scope 选项:
        - "project"  → 仅当前项目 Vault 的记忆
        - "personal" → 仅个人全局记忆
        - "all"      → 项目 + 个人 (默认)
      返回: 包含 CONSOLIDATED 权威结果 + BUFFERED provisional 结果 (见 12.3 Hot Buffer View)

    engram_capture(content, type?, importance?, tags[]?)
      → { capture_id, status: "buffered" }

      映射: Ch15 Capture API → capture()
      type: "decision" | "insight" | "convention" | "debugging" | "preference" | "fact"
           (语法糖，底层映射为 Engram.type + 对应的默认 rigidity)
      importance: "low" | "normal" | "high" | "critical"
           (映射为初始 strength 和 emotional_intensity)

    # ═══════════════════════════════════════════════════════
    # 状态查询
    # ═══════════════════════════════════════════════════════

    engram_status()
      → { vault_stats, recent_captures, cognitive_debt_count, last_epoch }

      Agent 用于判断: 记忆系统是否健康、是否需要触发 Epoch、积压了多少未整合记忆

    engram_forget(query_or_id, reason?)
      → { command_ack, scheduled_for_next_epoch }

      映射: Ch15 Command API → forget()
      用途: Agent 发现某条记忆已过时或有误时主动标记遗忘

**type 语法糖映射表**：

| Agent capture type | Engram.type | 默认 rigidity | 说明                     |
| ------------------ | ----------- | ----------- | ---------------------- |
| `decision`         | semantic    | 0.6         | 架构决策、技术选型              |
| `insight`          | semantic    | 0.4         | 调试发现、性能优化经验            |
| `convention`       | semantic    | 0.8         | 编码规范、命名约定、用户偏好         |
| `debugging`        | episodic    | 0.2         | 具体的调试过程记录              |
| `preference`       | semantic    | 0.9         | 用户明确要求的行为偏好            |
| `fact`             | semantic    | 0.7         | 项目事实: API 端点、依赖版本、环境配置 |

#### 20.5.3 三种接入协议的具体实现

**协议 A: MCP Server (Claude Code 原生接入)**

    MCP Server: engram-memory

    Resources:
      engram://vault/{vault_id}/stats          → Vault 状态概要
      engram://vault/{vault_id}/recent         → 最近 N 条记忆
      engram://session/{session_id}/context    → 当前 session 的记忆上下文

    Tools:
      engram_session_start    → 20.5.2 定义
      engram_session_end      → 20.5.2 定义
      engram_recall           → 20.5.2 定义
      engram_capture          → 20.5.2 定义
      engram_status           → 20.5.2 定义
      engram_forget           → 20.5.2 定义

    Prompts:
      engram_prime            → 生成 session_start 的 priming prompt
                                 包含项目上下文 + 相关记忆 + 用户偏好

    配置 (claude_desktop_config.json / settings.json):
      {
        "mcpServers": {
          "engram": {
            "command": "engram-mcp-server",
            "args": ["--vault", "~/.engram/vaults/default"],
            "env": { "ENGRAM_AGENT_DID": "did:engram:z6Mk..." }
          }
        }
      }

    Claude Code 的 hooks 集成:
      # settings.json hooks
      {
        "hooks": {
          "on_session_start": ["engram-mcp-server prime"],
          "on_session_end":   ["engram-mcp-server summarize"]
        }
      }

**协议 B: OpenAI Function Schema (Codex / 兼容 Agent)**

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "engram_recall",
        "description": "从长期记忆中检索相关知识。在遇到不确定的项目约定、架构决策、调试经验时调用。",
        "parameters": {
          "type": "object",
          "properties": {
            "query": { "type": "string", "description": "自然语言检索查询" },
            "scope": { "type": "string", "enum": ["project", "personal", "all"] },
            "max_results": { "type": "integer", "default": 5 }
          },
          "required": ["query"]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "engram_capture",
        "description": "将重要发现、决策、用户偏好存入长期记忆。仅在遇到值得跨会话记住的信息时调用。",
        "parameters": {
          "type": "object",
          "properties": {
            "content": { "type": "string" },
            "type": { "type": "string", "enum": ["decision","insight","convention","debugging","preference","fact"] },
            "importance": { "type": "string", "enum": ["low","normal","high","critical"] },
            "tags": { "type": "array", "items": { "type": "string" } }
          },
          "required": ["content"]
        }
      }
    }
  ]
}
```

**协议 C: CLI Wrapper (通用降级方案)**

```bash
# 任何能执行 shell 命令的 Agent 都可以使用

# Session
engram session start --project "$(pwd)" --task "fix auth bug"
engram session end <session_id> --outcome "completed" --summary "修复了 JWT token 过期配置问题"

# 记忆操作
engram recall "这个项目的认证机制是怎么实现的"
engram recall "用户对代码风格有什么偏好" --scope personal
engram capture "该项目使用 RS256 签名 JWT" --type fact --importance high
engram capture "用户偏好 snake_case 命名" --type preference

# 状态
engram status
engram forget "旧的 API 端点 /v1/auth" --reason "已迁移到 /v2/auth"

# 输出格式: JSON (方便 Agent 解析)
# 所有命令支持 --format json | text | compact
```

### 20.6 Agent 会话生命周期与自动记忆 (Session Lifecycle)

> Agent 不会主动"决定"要记住什么——它需要明确的触发规则。

#### 20.6.1 会话三阶段

    Phase 1: 会话启动 (Context Priming)
    ══════════════════════════════════════════════════════════

      Agent 启动 / 用户开始新对话
           |
           v
      engram_session_start(
        project_context = pwd + git repo info + 当前分支,
        task_description = 用户的第一条消息 (如果有)
      )
           |
           v
      Engram 返回:
        priming_memories = [
          { "该项目使用 Next.js 14 + App Router", strength: 0.9, type: "fact" },
          { "用户要求所有新函数必须有单元测试", strength: 0.95, type: "convention" },
          { "上次调试时发现 Redis 连接池泄漏", strength: 0.7, type: "insight" },
        ]
           |
           v
      Agent 将 priming_memories 注入 system prompt 或首条上下文
      → Agent 从"第一天上班的新人"变成"了解项目历史的老员工"


    Phase 2: 工作期间 (Active Session)
    ══════════════════════════════════════════════════════════

      Agent 正常工作，在以下时机调用 Engram:

      自动 recall 触发器:
        - Agent 读取陌生文件/模块 → recall("这个模块的设计意图是什么")
        - Agent 准备修改代码 → recall("这个函数有什么已知问题")
        - Agent 遇到报错 → recall("之前遇到过类似错误吗")
        - Agent 需要做技术选型 → recall("项目技术栈的约束和偏好")

      自动 capture 触发器:
        - 用户纠正 Agent 的行为 → capture(type: "preference")
          "用户说不要用 any 类型" → { content: "禁止使用 TypeScript any 类型",
                                     type: "convention", importance: "high" }
        - Agent 解决了一个 bug → capture(type: "debugging")
        - Agent 做了架构决策 → capture(type: "decision")
        - 用户说"记住这个" → capture(type: 由内容推断, importance: "critical")

      判断规则 — Agent 何时应该 capture:
        ┌──────────────────────────────────────────────────────┐
        │ 用户明确说"记住/以后都/每次/总是/不要再" → 必须 capture │
        │ 解决了耗时 > 10 分钟的问题            → 应该 capture  │
        │ 发现了文档中没有的项目约定             → 应该 capture  │
        │ 第一次使用某个 API/工具的正确用法       → 可以 capture  │
        │ 日常的代码修改、普通对话               → 不 capture    │
        └──────────────────────────────────────────────────────┘


    Phase 3: 会话结束 (Session Wrap-up)
    ══════════════════════════════════════════════════════════

      用户退出 / Agent 完成任务 / 会话超时
           |
           v
      engram_session_end(
        session_id,
        outcome = "completed" | "abandoned" | "error",
        summary = "修复了 JWT token 过期配置问题"
      )
           |
           v
      Engram:
        1. summary 存入 sessions.summary（不落 engrams）
        2. 统计本次会话事件数（captures / observations）
        3. 关闭 session 记录
        4. 值得跨会话复用的信息由调用方显式 capture

      ⚠️ v0.5+ 扩展:
        - 引入 EpochTriggerPolicy 后，session_end 可自动触发 mini-Epoch
        - learnings 参数届时恢复，自动 capture 为独立 Engram

#### 20.6.2 Agent 的 Context Window 即 L1

    传统 Engram 三层:
      L1 (工作记忆)  = 有限容量的缓冲区 (~7 个 Engram)
      L2 (流水日志)  = capture 的暂存区
      L3 (核心库)    = 长期记忆

    Agent 的天然映射:
      L1 = Agent 的 Context Window (128k~1M tokens)
           Agent 的 context 就是它的工作记忆
           context 被压缩/截断 = 工作记忆容量溢出
           → Agent 应在 context 即将压缩前 capture 关键信息

      L2 = Engram L2 (不变)

      L3 = Engram L3 (不变)

    关键推论:
      - Agent 不需要 Engram 维护 L1——Agent 自己的 runtime 就是 L1
      - engram_recall() 是 L3 → L1 的加载操作 (长期记忆 → 工作记忆)
      - engram_capture() 是 L1 → L2 的持久化操作 (工作记忆 → 流水日志)
      - Epoch 是 L2 → L3 的整合 (不变)

### 20.7 项目级 Vault 与多 Agent 协作

> 一个项目可能被多个 Agent 访问：开发者 A 用 Claude Code，开发者 B 用 Codex。它们应该共享项目知识。

    项目记忆拓扑:

      +-------------------+
      | Project Vault     |  ← 共享的项目知识库
      | (project-x/main)  |     存储: 架构决策、API 文档、编码规范、已知问题
      +---------+---------+
                |
        +-------+-------+-------+
        |               |       |
        v               v       v
      Alice's           Bob's   CI Bot
      Agent Vault       Agent   Agent Vault
      (fork)            Vault   (fork)
                        (fork)
        |               |       |
        | 工作期间产生    |       | 构建/测试结果
        | 的新发现       |       | capture 为 fact
        |               |       |
        +--- PR ------->+       |
        |       <--- PR-+       |
        +------ PR ----->-------+

      规则:
      - 每个 Agent 会话开始时 fork (或 sync) Project Vault 的最新状态
      - Agent 工作期间的 capture 写入自己的 Vault
      - 会话结束时，高 importance 的 capture 自动生成 PR 到 Project Vault
      - Project Vault 的无冲突 PR 默认排队等待人工确认
        (如果用户启用了 Diplomat Agent，可由 Diplomat 按操作类型门控处理——
         但 Diplomat 默认 OFF，不是系统默认调度器，见 6.6.1 节)
      - 事实性冲突升级为人工审查 (通过 ClaimRecord 结构化检测)

**项目 Vault 的初始化**：

    首次在项目中使用 Engram 时:

      engram init --project $(pwd)

      自动行为:
      1. 扫描项目根目录:
         - README.md / CONTRIBUTING.md → capture 为 convention
         - package.json / Cargo.toml → capture 为 fact (依赖、版本)
         - .eslintrc / tsconfig.json → capture 为 convention (代码规范)
         - CLAUDE.md / .cursorrules → capture 为 preference (AI 指令)
         - .github/workflows/ → capture 为 fact (CI/CD 配置)
      2. 分析 git log (最近 100 条 commit):
         → 提取高频修改模式、活跃贡献者、模块变更频率
      3. 生成 Project Vault 的 Inception Commit
         → 走冷启动管道 (Ch18)，但 scope 限定为项目文件
         → 所有导入记忆遵循冷启动安全约束 (18.5): 低 strength、低 confidence

### 20.8 接入层的三轨映射与 Epoch 策略

#### 20.8.1 Agent 三轨的工程实现

    觉醒轨道 (Agent 会话期间):
      ┌─────────────────────────────────────────────┐
      │ Agent Runtime (Claude Code / Codex / etc.)  │
      │                                             │
      │ engram_recall()  → View Store + Hot Buffer  │
      │ engram_capture() → L2 + Hot Buffer Index    │
      │                                             │
      │ 约束: 与 Ch12.3 一致                         │
      │ - 不调 LLM (Engram 侧不调，Agent 自身照常)   │
      │ - 不写 L3                                   │
      │ - recall 亚毫秒响应                          │
      └─────────────────────────────────────────────┘

    潜意识轨道 (后台守护进程，与 Agent 会话无关):
      ┌─────────────────────────────────────────────┐
      │ engram-daemon (常驻后台)                     │
      │                                             │
      │ - 消费 PulseEvent → Delta Ledger (强化)      │
      │ - 衰减计算 → Delta Ledger (衰减)             │
      │ - 聚类监控 → pending_abstraction 标签        │
      │                                             │
      │ 与 Agent 的会话完全解耦                       │
      │ Agent 是否在线不影响潜意识轨道的运行           │
      └─────────────────────────────────────────────┘

    睡眠轨道 (Epoch):
      ┌─────────────────────────────────────────────┐
      │ 触发条件 (Agent 特化):                       │
      │                                             │
      │ 1. 会话结束时累积检查:                        │
      │    captures_since_last_epoch > 20 → Epoch   │
      │                                             │
      │ 2. 时间间隔:                                 │
      │    距离上次 Epoch > 4 小时 → Epoch            │
      │                                             │
      │ 3. 手动触发:                                 │
      │    engram epoch --vault project-x            │
      │                                             │
      │ 4. 空闲检测:                                 │
      │    无活跃会话超过 30 分钟 → 自动 Epoch         │
      │                                             │
      │ Epoch 内容: 与 Ch12.5 完全一致               │
      │ Delta Ledger 折叠 + Recon Buffer 生成        │
      │ Revision + 抽象化 + 两阶段提交               │
      └─────────────────────────────────────────────┘

#### 20.8.2 Agent 应该记住什么 vs 不记住什么

    应该记住 (高信号):                    不应该记住 (噪声):
    ─────────────────────                ─────────────────────
    用户明确说"记住/总是/不要"            普通的代码修改细节
    架构决策和原因                        临时的调试过程中间步骤
    反复出现的 bug 模式                   已写入代码注释的信息
    项目特有的非显式约定                   一次性的查询结果
    用户的工作习惯和偏好                   从文件中读取就能获得的信息
    API 的非直觉行为                     Agent 自身的推理过程
    跨模块/跨服务的依赖关系               已有文档明确覆盖的内容

    判定原则: 如果删掉这条记忆，下次 Agent 会犯同样的错误吗？
             是 → capture。否 → 不 capture。

#### 20.8.3 与现有 Agent 记忆系统的关系

    现有机制            Engram 的关系          迁移策略
    ─────────────────  ─────────────────────  ──────────────────
    CLAUDE.md          Project Vault 的       engram init 时自动
                       高 rigidity 记忆源      导入为 convention 类型
                                              双向同步: Engram 可导出
                                              高 strength convention
                                              回 CLAUDE.md

    .cursorrules       同上                   同上

    Mem0 / MemGPT      Engram 是其超集        提供迁移适配器
                       (Ch18 冷启动管道)       Mem0 export → Engram import

    Git history        Project Vault 的       engram init --history
                       冷启动数据源            分析 commit 提取模式

    IDE 上下文          L1 工作记忆            不迁移 (Agent context = L1)

***

## 第二十一章：联邦协议 — Engram Federation Protocol (EFP)

> 记忆是最私密的数据，不应该有单点信任。
> 但完全去中心化又会让社交发现变得不可能。
> 联邦制是两者之间的优雅平衡。

### 21.1 协议定位

EFP 不重新发明轮子，而是在已有协议的基础上扩展：

                    AT Protocol (Bluesky)
                          |
            身份层 (DID) + 数据仓库
                          |
            +-------------+-------------+
            |                           |
       ActivityPub                  EFP 扩展
       (Mastodon 生态)             (Engram 特有)
       社交互动基础                 记忆语义操作

**选择 AT Protocol 风格而非纯 ActivityPub 的理由**：

*   AT Protocol 的"数据仓库归用户所有"理念与 Engram 的数据主权一致
*   内置的身份可迁移性：用户可以带着 Vault 在实例间迁移
*   更适合结构化数据（Engram Schema）而非松散的 Activity 流

### 21.2 协议层次

    +------------------------------------------------------------------+
    |                        EFP 协议栈                                  |
    +------------------------------------------------------------------+
    |                                                                    |
    |  Layer 4: 语义操作层 (Semantic Operations)                          |
    |    fork() / pr() / merge() / sync() / discover()                  |
    |    记忆特有的语义操作，定义操作的请求/响应格式                         |
    |                                                                    |
    +------------------------------------------------------------------+
    |                                                                    |
    |  Layer 3: 同步层 (Synchronization)                                 |
    |    基于 Merkle Hash 的增量同步                                      |
    |    Gossip 协议传播 Vault 状态摘要                                    |
    |    冲突检测与合并协调                                                |
    |                                                                    |
    +------------------------------------------------------------------+
    |                                                                    |
    |  Layer 2: 信任与加密层 (Trust & Encryption)                         |
    |    实例间互信评级与传递                                              |
    |    端到端加密（PrivacyMask 的跨实例强制执行）                         |
    |    数字签名（防篡改校验）                                            |
    |                                                                    |
    +------------------------------------------------------------------+
    |                                                                    |
    |  Layer 1: 身份与传输层 (Identity & Transport)                       |
    |    DID (去中心化身份): did:engram:<key-fingerprint>                 |
    |    Handle (可变句柄): user@instance.domain (见 21.3 双层标识)       |
    |    密钥对管理与轮换                                                  |
    |    HTTPS / WebSocket 传输                                          |
    |                                                                    |
    +------------------------------------------------------------------+

### 21.3 身份系统 — 双层标识模型

> `did:engram:alice@memory.example.com` 把用户名和域名嵌入 DID，迁移后字符串必然变化，违反 DID 的"稳定不可变"语义。因此身份必须拆分为两层。

    Layer 1: 稳定身份 — DID (不可变)

      did:engram:<key-fingerprint>

      示例: did:engram:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK

      生成规则:
        - 基于用户 Ed25519 公钥的指纹（Multibase 编码）
        - 创建时生成，终身不变
        - 不包含任何实例信息——纯密码学身份
        - 所有 Fork 引用、upstream 引用、influence 统计绑定 DID
        - 密钥轮换时: 旧密钥签署 rotation proof，DID 可映射到新密钥
                       DID 字符串本身不变（指向 DID Document，Document 内更新密钥）

    Layer 2: 可变句柄 — Handle (可变)

      alice@memory.example.com

      功能:
        - 人类可读的发现地址（类似 email / Bluesky handle）
        - 实例内唯一，跨实例不保证唯一
        - 可随时修改用户名或迁移实例
        - 通过 DNS TXT 记录或 .well-known 端点解析到 DID

    解析流程:
      alice@memory.example.com
        → GET https://memory.example.com/.well-known/engram-did/alice
        → 返回: { "did": "did:engram:z6Mkha...", "publicKey": "..." }
        → 后续所有操作使用 DID，不再依赖 handle

    实例迁移:
      - 用户将 Vault 从 instance-A 迁移到 instance-B
      - DID 不变: did:engram:z6Mkha... (始终相同)
      - Handle 变化: alice@instance-a.com → alice@instance-b.com
      - 旧实例设置 handle 重定向 (HTTP 301 + DID Document 更新)
      - 所有 Fork 引用绑定的是 DID，迁移后自动跟随

    密钥对:
      - 每个用户持有一对 Ed25519 签名密钥
      - 私钥本地保存，永不上传
      - 公钥通过 DID Document 公开，可在任意实例注册
      - 支持密钥轮换（旧密钥签署新密钥的 rotation proof）

### 21.4 跨实例操作流程

**Fork 流程**：

    Bob@instance-B 要 Fork Alice@instance-A 的 Vault

    1. Bob 发送 ForkRequest:
       { source: "did:engram:z6MkAlice...", vault: "ml-knowledge", mode: "shallow" }
       # 使用稳定 DID (基于密钥指纹)，非 handle

    2. Instance-B → Instance-A: 验证 Bob 的身份签名

    3. Instance-A: 执行 PrivacyMask 过滤 + 级联脱敏

    4. Instance-A → Instance-B: 传输过滤后的 Engram 数据包
       (签名校验，确保传输中未被篡改)

    5. Instance-B: 本地创建 Vault，执行类型转换 (episodic→learned)
       设置 upstream 引用: "did:engram:z6MkAlice.../ml-knowledge"
       # upstream 绑定 DID，Alice 迁移实例后引用自动跟随

    6. 完成。后续 sync 通过增量协议进行。

**PR 流程（Bob → Alice，操作日志模式）**：

    Bob@instance-B 要向 Alice@instance-A 提交修改

    1. Bob 的实例打包 OperationLog (3.14 节):
       - 包含 Bob 在 fork 后执行的所有变更操作
       - base_projection_hash 指向 Bob fork 时的 Projection 版本
       - 签名确保传输中未被篡改

    2. Instance-B → Instance-A: 发送 MemoryPR (含 OperationLog)

    3. Instance-A 执行 Canonical Replay:
       a. Phase 0 (验证): 校验签名 + base_projection_hash 有效性
       b. Phase 1 (预扫描): 逐条检查操作 —
          - target_id 在 canonical 中存在 → resolvable
          - target_id 不存在 (噪声边/隐私过滤/已删除) → dangling (静默跳过)
          - 涉及 ClaimRecord 冲突 → conflict (升级人工审查)
          - 操作越权 (修改 rigidity >= 0.5 的 Engram) → unauthorized
       c. Phase 2 (分流): Diplomat 按操作类型分流 (见 6.6.1 节)
       d. Phase 3 (原子应用): 在 Epoch Command 阶段批量执行

    4. Instance-A → Instance-B: 返回 ReplayReport (3.16 节)
       - skipped 原因统一显示"目标在接收方视图中不可达"
       - 不区分噪声/隐私/已删除（防止隐私泄露）

**Upstream Sync 流程（Alice → Bob，操作日志模式）**：

    1. Instance-B 定期向 Instance-A 请求:
       "自 commit_id=X 以来有哪些变化？"

    2. Instance-A:
       a. 计算 canonical diff (commit_X → HEAD)
       b. 应用 Bob 的 PrivacyMask 过滤
       c. 将过滤后的变更转换为 SyncOperationLog (见 6.7 节)
       d. 签名后发送

    3. Instance-B 逐条重放 operations:
       - 与 Bob 本地修改冲突 → ClaimRecord 检测 (6.5 节)
       - 非冲突操作自动应用 (或经 Diplomat 分流)
       - 上游记忆 strength 按 fork 转换规则降权

### 21.5 信任网络

    信任模型:

    直接信任 (Direct Trust):
      Alice 显式信任 Bob → trust(Alice, Bob) = 0.9

    传递信任 (Transitive Trust):
      Alice 信任 Bob (0.9), Bob 信任 Carol (0.8)
      → trust(Alice, Carol) = 0.9 × 0.8 × DECAY = 0.9 × 0.8 × 0.7 = 0.504
      (传递信任有衰减系数，防止无限传递)

    实例信任 (Instance Trust):
      - 实例之间也有互信评级
      - 基于历史交互的质量（PR 被接受率、数据完整性、在线率）
      - 新实例的默认信任度低，需要通过行为积累

    信任的影响:
      - trust < 0.3: Fork/PR 请求默认拒绝
      - trust 0.3~0.7: 请求被标记为需审查
      - trust > 0.7: 请求正常处理
      - trust > 0.9: 可启用自动同步（无需逐条审查）

### 21.6 恶意实例隔离

    检测信号:
      - 大量发送含恶意/虚假内容的 PR
      - Sybil 攻击模式（大量空壳用户互相 Fork 刷信誉）
      - 拒绝执行 PrivacyMask（返回未脱敏的数据）
      - 篡改传输数据（签名校验失败）

    响应机制:
      - 单个实例可以屏蔽另一个实例 (类似 Mastodon 的 domain block)
      - 联邦共享黑名单 (可选订阅，非强制)
      - 渐进式降信任：异常行为 → 降低信任度 → 最终隔离
      - 不存在"全局管理员"——每个实例自主决定信任谁

### 21.7 传输层防护 (Transport-Level Protection)

信任评分是战略层防护（长期信誉），但系统还需要战术层防护（即时限流和反滥用）：

    速率限制 (Rate Limiting):
      - 每实例每小时: 最多 N 次 fork_request (默认 10)
      - 每实例每小时: 最多 N 次 pr_submit (默认 50)
      - 每实例每天: 最多 N 次 sync_request (默认 100)
      - 高成本操作 (merge/diff 大规模 Vault): 额外节流，基于 Vault 大小动态调整

    反垃圾 (Anti-Spam):
      - PR 内容大小上限 (默认 10MB/次)
      - Fork 请求需携带 Proof-of-Work nonce (轻量级，防止批量刷)
      - 未经互信的实例首次请求需完成握手挑战

    重放保护 (Replay Protection):
      - 每条 EFP Message 包含 nonce + timestamp
      - 接收方维护 nonce 滑动窗口 (默认 24 小时)
      - 超过窗口的消息或重复 nonce 直接丢弃

    幂等性 (Idempotency):
      - fork_request / pr_submit 携带 idempotency_key
      - 重复请求返回缓存的响应，不重复执行

    退避策略 (Backoff):
      - 对低信任实例: 指数退避 (1min → 2min → 4min → ... → 1day)
      - 对触发限流的实例: 临时冷却期 (默认 1 小时)
      - 对签名校验失败的实例: 立即断开，人工审查后才恢复

### 21.8 协议消息格式（概要）

    EFP Message {
      version:              "efp/1.0"
      type:                 fork_request | fork_response |
                            pr_submit | pr_response |       # payload = OperationLog (3.14) / ReplayReport (3.16)
                            sync_request | sync_operations | # payload = SyncOperationLog (6.7)
                            discover_query | discover_result |
                            trust_update | instance_announce
      sender:               DID
      recipient:            DID
      timestamp:            ISO 8601
      signature:            Ed25519 签名
      payload:              type-specific data
      encryption:           none | aes-256-gcm (for private data)
    }

***

## 第二十二章：生态层与增强模块 (Ecosystem & Enhancements)

为了进一步提升系统的上下文获取能力与评测基准，Memento 将借鉴业界领先实践（如 Supermemory）的工程优点，构建可扩展的“生态层”。这些模块将作为外围系统接入，保持核心引擎（三轨架构）的轻量与纯粹。

### 22.1 数据注入与连接器 (Data Injection & Connectors)

传统的 `capture` 依赖 Agent 或人类主动写入。增强模块将引入持续的自动数据同步通道，让知识入库变为后台无缝过程。

*   **多源连接器 (Webhooks & API Connectors)**：
    *   支持与外部应用（Google Drive, Notion, GitHub, Gmail, OneDrive 等）双向或单向同步。
    *   通过实时 Webhook 捕获变更，提取其中的事实与动态，经由统一的 `ingest` 端点（底层复用 `capture` 写路径）写入 L2 流水日志（工作记忆），完全绕过人工 CLI 操作，不破坏三轨架构的核心边界。
*   **网络与流媒体抓取 (Web & Social Scraper)**：
    *   支持无头网页抓取与 RSS/公开 API 等结构化数据流的自动抽取；社交媒体平台（如 Twitter/X）因 API 政策限制与合规复杂性，降格为**社区插件**，不纳入核心路线图。
    *   将非结构化流转化为具备 `source_ref` 与时间戳的初始记忆形态（BUFFERED），并交由睡眠轨道（Epoch）执行抽象化提炼；抓取行为须遵守目标站点的 `robots.txt` 及相关数据保护法规。

### 22.2 用户画像与上下文缓存 (Context Caching & Profiles)

为了解决“长上下文”中 Agent 冷启动时需要的极速上下文读取问题，引入“User Profiles”式的高速摘要缓存。

*   **动静结合的 Profile 视图**：
    *   **静态事实 (Static Facts)**：高 rigidity、长半衰期的基础事实与偏好（如"资深开发者"、"偏好 Python"），直接作为常驻上下文。
    *   **动态上下文 (Dynamic Context)**：近期高活跃度的短期记忆（STM）和 L2 热缓存，反映用户或项目"当下在做什么"。
*   **极速注入 (Sub-50ms Injection)**：
    *   将上述 Profile 进行预聚合，并在 `recall` 或 `context` 阶段只需单次极速读取（目标 < 50ms）即可完整注入给 Agent。无需每次基于冷库执行重度向量检索，将“被动搜索”转换为“主动感知”。

### 22.3 混合检索与长文本基准 (Hybrid Search & LongMemEval)

*   **统一的混合检索 (Hybrid RAG + Memory)**：
    *   不再仅仅做纯粹的情景记忆召回，而是支持将项目内固化的知识库文档（Document/RAG）与用户级个性化记忆（Memory）同权检索。
    *   记忆处理用户的偏好、过时信息和矛盾冲突；文档提供底层的知识基础，在一次查询中统一完成（Hybrid Search）。
*   **评测基准对齐 (LongMemEval / LoCoMo 兼容)**：
    *   引入长期记忆相关的业界标准测试（如 LongMemEval、LoCoMo），量化测试系统跨会话（Cross-Session）的长文本记忆准确率、事实更新与知识矛盾解决能力。
    *   将 memento 的 A/B 隔离测试机制（v0.1 的 `eval`）升级并提供外部 Benchmark 工具，对标业界最严苛的“动态记忆提取”标准。

***

## 第二十三章：MVP 路线图 — 从"缸中之脑"到"全球心智网络"

> 22 章的系统不可能一次性实现。
> 如果一口气全做，这注定是烂尾工程。
> 每个阶段必须独立可交付、独立有价值。

### 23.1 演进路线（更新于 2026-04-10，v0.9.2 进行中）

    v0.1 ✅       v0.5 ✅        v0.6 ✅        v0.7 ✅        v0.8 ✅        v0.9 ✅        v1.0
    极简验证       三轨架构        Agent 感知      LLM 管线       Web Dashboard  对话记忆提炼    联邦
      |             |              |              |              |              |              |
      | capture     | 三轨节律      | 向量检索      | L2→L3 结构化 | FastAPI+Vue3 | transcript   | EFP 协议
      | recall      | CQRS         | staleness    | 再巩固        | 记忆浏览管理  | Stop hook    | 跨实例身份
      | 衰减        | 状态机        | exclusion    | Epoch 自动化  | 搜索过滤      | LLM 提取     | 信任网络
      | Session     | Delta Ledger | LLM 管线     | T5 抽象化     | verify/pin   | 增量去重      |
      | MCP+Hook    | rigidity     |              |              | 离线可用      | 自动过滤      |
      |             |              |              |              |              |              |
      核心假设验证   三轨引擎        Agent 感知      系统自主整合    可视化管理      对话→记忆       跨实例
                    E2E 闭环       质量+LLM       高质量记忆      运维观察面板    自动积累        数据主权

    说明:
    - v0.1–v0.3 已合并为 v0.1 里程碑（全部完成）
    - v0.5 含 v0.5.0（核心架构）+ v0.5.1（E2E 集成 + 打包 + Subconscious 硬化）
    - v0.6 分两阶段: v0.6.0（检索修复 + 感知增强）, v0.6.1（摄取安全网 + 自动摘要兜底）
    - v0.8 Web Dashboard: 本地运维观察面板（FastAPI + Vue 3 无构建）
    - v0.9 从 event ingestion 升级到 conversation memory extraction（已完成）

      ┌─────────────────────────────────────────────────────────────────┐
      │ 已从主路线移除 (原 v2.0):                                        │
      │                                                                 │
      │ × 归属自动判定 (drift/Genesis 自动执行)                            │
      │   → 原因: LLM 概率模型不能裁决法律/经济权利                        │
      │   → 如果需要: 转为社区治理 + 人类仲裁委员会                        │
      │                                                                 │
      │ 这不是 postponed feature，是在当前设计框架下不可行的方向。           │
      │ 重新纳入需要独立的研究项目和完全不同的设计。                        │
      └─────────────────────────────────────────────────────────────────┘

      系统定位修正:
        旧定位: 个人记忆 OS → 社交知识网络 → 联邦真相系统
        新定位: 个人/Agent 记忆引擎 → 有限共享 → 联邦同步（非共享真相）
        核心区别: 不追求"网络上所有人看到同一个真相"，
                  只保证"每个人在自己的 canonical 域内有一致的真相"

### 23.2 v0.1 "极简验证" — 一个 SQLite 文件的 MVP

> **设计原则：在第一行代码之前不做架构决策。**
> v0.1 的唯一目标是验证核心假设：**衰减 + 强化是否比纯向量搜索 + 时间排序更好？**
> 如果验证不通过，省下几个月工程量。如果通过，v0.2 先补 agent-runtime 集成层，v0.5 再引入三轨/CQRS/状态机。
>
> **v0.1 → v0.2 是增量演进，v0.2 → v0.5 才是架构重写。** v0.2 复用 v0.1 的 engrams 表数据和衰减模型代码，在其上新增 session / event / observation 层。v0.1 的单进程同步读写模型在 v0.2 中保持不变——三轨异步架构推迟到 v0.5。v0.5 的三轨/CQRS 与 v0.2 的单进程模型之间没有渐进过渡路径，届时应从零开始用正确架构重写，延续的是**数据**（SQLite 中的记忆内容和元数据），不是代码。

**只做三件事**：

1.  `memento capture` — 存入记忆
2.  `memento recall` — 带衰减权重的检索
3.  `memento export / import` — 离线记忆传递

**砍掉的一切（相比前版 v0.1 进一步砍掉）**：

*   ~~三轨节律~~ → 单进程，无后台 worker
*   ~~CQRS~~ → 单 SQLite，读写同库
*   ~~五态状态机~~ → 只有 active / forgotten 两态
*   ~~Delta Ledger~~ → 衰减在 recall 时惰性计算
*   ~~两阶段提交~~ → SQLite 事务即可
*   ~~Epoch 批处理~~ → 无 Epoch，衰减和强化实时生效
*   ~~LLM 依赖~~ → v0.1 零 LLM 调用，抽象化推迟到 v0.5
*   ~~Hot Buffer View~~ → 没有 BUFFERED 态，capture 直接写入可检索
*   ~~Merkle DAG 版本管理~~ → 不需要
*   无社交、无联邦、无 MCP

**技术栈（一个文件）**：

    +-------------------------------+
    |  CLI (pip install memento)    |
    |                               |
    |  memento capture "content"    |
    |  memento recall "query"       |
    |  memento export / import       |
    |  memento status / forget       |
    +---------------+---------------+
                    |
       AI Agent 通过 Bash/Shell 调用
       (Claude Code / Codex / Gemini CLI)
                    |
                    v
    +--------------------------------------------------+
    |           Engram Core (Python)                    |
    |                                                   |
    |  capture(content, origin='human'):                 |
    |    1. 调用 Embedding API 生成向量                   |
    |    2. INSERT INTO engrams (..., origin, verified)   |
    |       origin='human' → verified=1 (用户直接输入)     |
    |       origin='agent' → verified=0 (Agent 自动写入)   |
    |    3. 完成（同步，无队列）                            |
    |                                                   |
    |  recall(query):                                   |
    |    1. 查询向量生成 embedding                        |
    |    2. 向量相似度检索 top-K 候选                      |
    |    3. 对候选计算 effective_strength:                |
    |       base_strength                                |
    |         × decay(now - last_accessed)               |
    |         × similarity_score                         |
    |    4. 按 effective_strength 排序返回                 |
    |    5. 命中的记忆: UPDATE strength, last_accessed    |
    |       (读即写的再巩固，但在单库里就是一条 UPDATE)       |
    |                                                   |
    +-------------------------+------------------------+
                              |
                   +----------+----------+
                   |                     |
            +------+-------+    +-------+--------+
            | SQLite       |    | Embedding API  |
            | (sqlite-vec) |    | (可选后端):      |
            |              |    |  - OpenAI       |
            | engrams 表    |    |  - Ollama       |
            | 含向量列      |    |  - 本地模型      |
            +--------------+    +----------------+

**并发安全（SQLite WAL 模式）**：

    v0.1 是 CLI 工具，天然面临多终端/多 Agent 并发调用。
    SQLite 默认的 journal_mode=delete 在写入时锁定整个数据库，并发 recall() 会互相阻塞。

    初始化时强制开启 WAL (Write-Ahead Logging):

      PRAGMA journal_mode=WAL;          -- 允许读写并发（多读单写）
      PRAGMA busy_timeout=5000;         -- 写锁等待 5 秒而非立即失败
      PRAGMA wal_autocheckpoint=1000;   -- 每 1000 页自动 checkpoint

    WAL 保证:
      - 多个 recall() 可以同时读（不互相阻塞）
      - recall() 的原子 UPDATE 与其他 recall() 串行化（由 SQLite 保证）
      - capture() 与 recall() 可以并发（读不阻塞写，写不阻塞读）
      - 最坏情况: 两个写操作同时发生 → busy_timeout 内自动重试

    所有 strength 更新使用原子 SQL（见 recall 代码），不在 Python 侧 read-modify-write。

**CLI 自动化与知识共建（Agent Hook）**：

    虽然 v0.1 核心严格遵循“零 LLM 调用”，但通过在 AI Agent 客户端（如 Claude Code / Gemini CLI / Codex）注入行为规范，
    可完美实现高度自动化的“总结-写入-分享”工作流：

      1. 自动提炼与写入 (Auto-Capture):
         在 Agent 的自定义配置（如 Custom Instructions 或 .clauderc）中注入规则：
         "完成复杂任务或结束对话前，主动总结核心避坑经验与架构决策（<200字），
          并立刻在终端执行：`memento capture '<你的总结>'`"
         → 效果: Agent 成为自动档案员，Engram 退到幕后作为纯粹的持久化网关。

      2. 隐式团队传承 (Export & Share):
         核心开发者通过 `memento export > memory.json` 导出沉淀后的项目 SQLite 记忆库。
         新加入项目的成员执行 `memento import memory.json` 即可继承完整的项目上下文。
         → 效果: 新成员的 Agent 此后在触发 `memento recall` 时，能直接命中并使用
                 前辈留下的集体经验，在 v0.1 阶段即以“零架构成本”实现了高维度的知识协同。

**Embedding 离线降级策略**：

    v0.1 声明"零 LLM 调用"，但 Embedding API 本身是外部依赖。
    如果 API 不可用（断网 / Ollama 未启动 / OpenAI 配额耗尽），
    capture() 和 recall() 都无法工作——系统完全不可用。

    三级降级方案:

      Level 0 — 正常模式 (Embedding API 可用):
        capture: 生成 embedding → 写入 SQLite
        recall:  查询 embedding → 向量相似度检索 → 衰减加权排序

      Level 1 — 本地降级 (远程 API 不可用，但本地可运行轻量模型):
        优先自动切换到本地 embedding 模型:
          - sentence-transformers/all-MiniLM-L6-v2 (80MB, CPU 可跑)
          - 或用户指定的 Ollama embedding model
        行为与 Level 0 完全一致，仅 embedding 质量略有下降
        切换透明: 用户无感知，recall 结果可能略有差异

      Level 2 — 完全离线降级 (无任何 embedding 能力):
        capture:
          - 正常写入 content + 元数据
          - embedding 列留空 (NULL)
          - 标记 embedding_pending = 1
          - capture 不失败 — 宁可暂时无法被向量检索，也不丢数据

        recall:
          - 对有 embedding 的记忆: 正常向量检索
          - 对所有记忆 (含无 embedding 的): 回退到 FTS5 全文检索
            SQLite FTS5 是纯本地的，无外部依赖
            CREATE VIRTUAL TABLE engrams_fts USING fts5(content, tags);
          - 排序: normalize(FTS5 BM25 分数) × effective_strength (衰减加权)
          - 结果质量: 关键词匹配 < 语义检索，但远好于完全不可用

          ⚠️ 量纲归一化 (BM25 vs Cosine Similarity):
            向量检索的 similarity 值域为 [0, 1]（余弦相似度），
            但 FTS5 BM25 的得分是无界的（通常 5.0 ~ 40.0+）。
            如果混合排序时不做归一化，BM25 分数会碾压向量相似度，
            导致弱关键词匹配压过强语义匹配。

            归一化方案 (Sigmoid 映射):
              normalized_bm25 = 1.0 / (1.0 + exp(-BM25_SCALE * (raw_bm25 - BM25_MIDPOINT)))
              # BM25_SCALE = 0.3, BM25_MIDPOINT = 10.0 (可调参)
              # 效果: raw_bm25=10 → ~0.5, raw_bm25=20 → ~0.95, raw_bm25=2 → ~0.08
              # 映射到 [0, 1] 后与 effective_strength 相乘，量纲一致

            混合列表排序:
              向量检索结果:  score = effective_strength × cosine_similarity
              FTS5 检索结果: score = effective_strength × normalized_bm25
              两者合并后统一排序

        恢复:
          - Embedding API 恢复后，后台补填所有 embedding_pending = 1 的记忆
          - 补填完成后清除标记，后续 recall 自动使用向量检索

      降级检测:
        每次 capture/recall 时检测 embedding 可用性:
          try:
              embedding = get_embedding(text)  # Level 0
          except RemoteAPIError:
              embedding = get_local_embedding(text)  # Level 1
          except LocalModelError:
              embedding = None  # Level 2, 走 FTS5

      数据库初始化时同时创建 FTS5 索引 (成本极低，常驻可用):
        CREATE VIRTUAL TABLE IF NOT EXISTS engrams_fts
            USING fts5(content, tags, content=engrams, content_rowid=rowid);

**数据模型（一张表）**：

```sql
CREATE TABLE engrams (
  id            TEXT PRIMARY KEY,   -- UUID
  content       TEXT NOT NULL,
  type          TEXT DEFAULT 'fact', -- decision|insight|convention|debugging|preference|fact
  tags          TEXT,                -- JSON array: ["react","auth"]
  strength      REAL DEFAULT 0.7,   -- [0, 1]
  importance    TEXT DEFAULT 'normal', -- low|normal|high|critical
  source        TEXT,                -- imported_from:alice | null
  origin        TEXT DEFAULT 'human', -- human | agent (谁写入的)
  verified      INTEGER DEFAULT 0,  -- 0=未经人类验证, 1=已验证
                                    -- Agent 写入默认 origin='agent', verified=0
                                    -- 用户通过 CLI 写入默认 origin='human', verified=1
  created_at    TEXT NOT NULL,
  last_accessed TEXT NOT NULL,
  access_count  INTEGER DEFAULT 0,
  forgotten     INTEGER DEFAULT 0,  -- 0=active, 1=forgotten
  embedding_pending INTEGER DEFAULT 0, -- 1=embedding 待补填（离线降级时写入）
  embedding     BLOB                -- sqlite-vec 向量列 (可为 NULL，离线降级时)
);
```

**衰减公式（recall 时惰性计算，不需要后台进程）**：

```python
def effective_strength(engram, now):
    """每次 recall 时实时计算，不存中间态"""
    hours_since_access = (now - engram.last_accessed).total_seconds() / 3600

    # 基于间隔重复原理的简化衰减
    # access_count 越高，衰减越慢（越用越记得牢）
    half_life = BASE_HALF_LIFE * (1 + engram.access_count * 0.5)

    # importance 调节: critical 极慢衰减 + 周期性复验提醒
    # 设计哲学: "遗忘是特性不是缺陷" — 即使是 critical 记忆也不应永久免疫
    # 过时的配置、过期的法律条款、变更的 API 端点如果永不衰减，
    # 会固化为高权重假记忆，比遗忘更危险
    importance_factor = {"low": 0.5, "normal": 1.0, "high": 2.0, "critical": 10.0}
    half_life *= importance_factor[engram.importance]
    # critical 的半衰期 = BASE × (1 + access_count × 0.5) × 10
    # 以 BASE=168h(一周) 为例: 从未 recall 的 critical 记忆约 10 周后降至 50%
    # 频繁 recall 的 critical 记忆几乎不衰减 (半衰期可达数年)

    decay = 0.5 ** (hours_since_access / half_life)
    effective = engram.strength * decay

    # 周期性复验: critical 记忆 effective strength 跌破阈值时
    # 在 recall 返回结果中附带 review_hint（不持久化，不写数据库）
    # 调用方根据 review_hint 决定是否提醒用户复验
    # review_hint 仅是返回值中的临时字段，不是 Engram 的持久化状态

    return effective

def recall(query, max_results=5):
    """向量相似度 × 衰减权重，一条 SQL 搞不定的部分在 Python 里算"""
    candidates = vector_search(query, limit=max_results * 3)  # 多取一些候选
    now = datetime.now()

    # Agent 未验证记忆的固定上限 (见 20.3 节)
    agent_cap = 0.5  # 固定常量，不随 verified_ratio 动态调整

    scored = []
    for engram in candidates:
        eff = effective_strength(engram, now)
        score = eff * engram.similarity  # 衰减后强度 × 向量相似度
        scored.append((engram, score))

    results = sorted(scored, key=lambda x: -x[1])[:max_results]

    # 再巩固: 命中的记忆变强
    # 🔴 并发安全: 使用原子 SQL 而非 Python 侧 read-modify-write
    #    多个 CLI 进程可能同时 recall 同一条记忆（多终端 / 多 Agent），
    #    Python 侧 read → compute → write 会丢失更新。
    #    所有 strength 更新必须在单条 UPDATE 语句中完成。
    for engram, _ in results:
        hours_since = (now - datetime.fromisoformat(engram.last_accessed)).total_seconds() / 3600
        boost = min(0.1, 0.05 * (1 + log(1 + hours_since)))  # 间隔越长，增益越大

        # 原子 UPDATE — strength 计算在 SQL 内完成，无竞态窗口
        # Agent 未验证记忆的 strength 固定上限 0.5，已验证/人类记忆上限 1.0
        db.execute("""
            UPDATE engrams SET
                strength = MIN(
                    CASE WHEN origin = 'agent' AND verified = 0 THEN ? ELSE 1.0 END,
                    strength + ?
                ),
                access_count = access_count + 1,
                last_accessed = ?
            WHERE id = ?
        """, (agent_cap, boost, now.isoformat(), engram.id))

    # 附带 review_hint (不持久化，仅在返回值中临时附加)
    REVIEW_THRESHOLD = 0.5
    for engram, score in results:
        if engram.importance == 'critical':
            eff = effective_strength(engram, now)
            if eff < REVIEW_THRESHOLD:
                h = (now - datetime.fromisoformat(engram.last_accessed)).total_seconds() / 3600
                engram.review_hint = f"此关键记忆已 {int(h)}h 未访问，建议复验是否仍然准确"

    return results
```

**CLI 接口**：

```bash
# 核心命令
memento capture <content> [--type TYPE] [--importance IMPORTANCE] [--tags "a,b"] [--origin human|agent]
memento recall <query> [--max 5] [--mode A|B] [--format json|text]
memento seed-experiment [--db file.db] [--queries-output file.json] [--format json|text]
memento setup-experiment [--db-a file.db] [--db-b file.db] [--queries-output file.json] [--manifest-output file.json] [--force] [--format json|text]
memento eval --queries <file.json> [--mode A|B] [--compare-db other.db] [--compare-mode A|B] [--report-output file.json] [--format json|text]
memento verify <id>               # 人类确认某条 Agent 记忆为可信 → verified=1, 解除 strength 上限
memento status
memento forget <id>
memento export [--filter-type TYPE] [--filter-tags "a,b"] [--output file.json]
memento import <file.json> [--source "作者名"]

# 初始化
memento init                        # 创建 ~/.memento/default.db

# 示例
$ memento capture "该项目用 RS256 签名 JWT，密钥在 /config/keys/" --type fact --importance high

$ memento recall "认证" --format json
[
  { "id": "a1b2", "content": "该项目用 RS256 签名 JWT，密钥在 /config/keys/",
    "type": "fact", "strength": 0.85, "score": 0.78 }
]
```

**Export / Import（穷人版 Fork，与前版设计一致）**：

```bash
# 导出
memento export --output my-knowledge.json
memento export --filter-tags "react" --output react.json

# 导入（strength 上限 0.5，标记来源）
memento import alice-knowledge.json --source "alice"
```

**指令文件模板（与前版一致）**：

```markdown
# ═══ 加入 CLAUDE.md / AGENTS.md / GEMINI.md ═══

## Engram 长期记忆

本项目使用 memento 管理跨会话记忆。

### 会话开始时
运行 `memento recall "项目概况" --format json` 获取背景知识。

### 工作期间
- 遇到不确定的项目约定 → `memento recall "相关问题" --format json`
- 用户说"记住/总是/不要再/每次" → `memento capture "内容" --type preference --importance critical`
  （用户明确指示的内容不加 --origin agent，默认为 human，可信度最高）
- 解决了复杂 bug → `memento capture "过程" --type debugging --origin agent`
- 做了架构决策 → `memento capture "决策及原因" --type decision --origin agent`
- 发现项目约定 → `memento capture "约定" --type convention --origin agent`

### 重要：Agent 写入的记忆带有 strength 上限（0.5）
Agent 通过 --origin agent 写入的记忆在被人类验证（memento verify）前 strength 不超过 0.5。
这防止 Agent 幻觉通过反复 recall 自我强化成"坚不可摧的假记忆"。

### 判断原则
删掉这条记忆，下次会犯同样的错误吗？是→capture，否→不capture。
```

**MVP 涉及的设计文档章节**：

| 章节            | v0.1 的关系                                           |
| ------------- | -------------------------------------------------- |
| Ch3 数据模型      | **极简化**: 一张 SQLite 表，不需要 Revision/Nexus/PulseEvent |
| Ch4 生命周期      | **跳过大部分**: capture 直接入库可检索，无 BUFFERED 中间态          |
| Ch12 三轨节律     | **v0.1 不实现**: 单进程同步处理                              |
| Ch13 CQRS     | **v0.1 不实现**: 单库读写                                 |
| Ch14 状态机      | **极简化**: active / forgotten 两态                     |
| Ch17 工程约束     | **部分保留**: rigidity 简化为 importance 参数               |
| Ch20 Agent 接入 | **保留**: CLI + 指令文件                                 |

**交付物**：`pip install memento`（原名 engram，已更名） → 一个 SQLite 文件的 AI Agent 长期记忆。1-2 周交付。

### 23.2.1 v0.2 "Session Lifecycle + 自动采集框架"

> **v0.2 的核心目标**：补齐 agent-runtime 集成层。
> v0.1 验证了记忆模型（衰减+强化），v0.2 要让 Agent 从"手动记忆员"变成"自动记忆系统的用户"。
> 主要短板不在记忆模型，而在 session 层、event 层、engram 层三层没有分开。

**设计原则**：

1. **三层严格分离**：session 层（会话生命周期）、event 层（标准化事件流）、engram 层（长期记忆）各自独立
2. **session_summary 不是 engram**：摘要存 `sessions.summary`，不落 `engrams` 表
3. **observation 不是 capture 变体**：有独立的 ingestion pipeline（`ingest_observation`）
4. **默认只读**：所有浏览/探索接口不触发 Mode A 强化，只有显式 `reinforce=True` 才写入
5. **协议无关**：统一 API 层（`api.py`），CLI / MCP / Function Schema 都走同一接口

**与 v0.1 的关系**：
v0.2 在 v0.1 基础上增量演进：复用 engrams 表数据和衰减模型代码，新增 session / event / observation 层。
架构重写推迟到 v0.5（三轨/CQRS），届时延续的是数据，不是代码（见 23.2 说明）。

#### 23.2.1.1 数据模型扩展

**新增表 1: sessions（会话一等对象）**

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,       -- UUID
    project         TEXT,                   -- 项目路径或标识
    task            TEXT,                   -- 任务描述
    status          TEXT DEFAULT 'active',  -- active | completed | abandoned | error
    started_at      TEXT NOT NULL,          -- ISO datetime
    ended_at        TEXT,                   -- ISO datetime
    summary         TEXT,                   -- 会话摘要（一等字段，不是 engram）
    metadata        TEXT                    -- JSON，扩展字段（git branch, agent type 等）
);
CREATE INDEX idx_sessions_project ON sessions(project);
CREATE INDEX idx_sessions_status ON sessions(status);
```

设计要点：
- `summary` 是 sessions 表的一等字段，**不是 engram**
- 适合 `session/{id}` 直接取，不参与 recall 排序
- 如果后续需要挂多种会话产物（代码 diff、测试报告等），再加 `session_artifacts` 表

**新增表 2: session_events（标准化事件流）**

Append-only 事件日志，**只存标准化事件，不存原始工具输出**。

```sql
CREATE TABLE session_events (
    id              TEXT PRIMARY KEY,       -- UUID
    session_id      TEXT NOT NULL,          -- FK → sessions.id
    event_type      TEXT NOT NULL,          -- start | capture | recall | observation | tool_summary | end
    payload         TEXT,                   -- JSON，标准化格式（见下表）
    fingerprint     TEXT,                   -- 内容指纹，用于事件级去重
    created_at      TEXT NOT NULL,          -- ISO datetime
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_session_events_session ON session_events(session_id);
CREATE INDEX idx_session_events_type ON session_events(event_type);
```

payload 标准化规则（不存原始 tool output）：

    event_type      payload 内容
    ────────────    ─────────────────────────────────────────────────
    start           {"project": "...", "task": "...", "priming_count": N}
    capture         {"engram_id": "...", "type": "...", "content_preview": "前50字"}
    recall          {"query": "...", "result_count": N, "top_score": 0.85}
    observation     {"tool": "...", "files": [...], "summary": "...", "promoted": bool}
    tool_summary    {"tool": "...", "files": [...], "summary": "摘要"}
    end             {"outcome": "...", "captures_count": N, "observations_count": N}

⚠️ 原始工具输出如确实需要保留，单独做 artifact/blob 引用，不放主事件流。

**扩展 engrams 表**

```sql
ALTER TABLE engrams ADD COLUMN source_session_id TEXT;   -- 产生该记忆的会话
ALTER TABLE engrams ADD COLUMN source_event_id TEXT;     -- 产生该记忆的具体事件
```

来源追踪精确到事件级。长期记忆可能来自：
- 会话中的某个 observation 被晋升
- session_end 时的 learnings 被调用方显式 capture
- 人工手动修订
- 跨会话 import/merge

单纯一个 `session_id` 语义太弱，`source_event_id` 才能精确追溯。

#### 23.2.1.2 统一 Memory API（api.py）

协议无关层，定义标准输入输出。CLI / MCP / Function Schema 都走这层。

    7 个一级 API:

    session_start(project?, task?, metadata?)
      → { session_id, priming_memories[] }
      行为: 创建 session 记录 + 自动 recall 相关记忆作为 priming context

    session_end(session_id, outcome?, summary?, learnings[]?)
      → { session_id, status, captures_count, observations_count }
      行为: summary 存入 sessions.summary（不落 engrams）
             learnings 中值得跨会话复用的条目由调用方决定是否 capture

    recall(query, max_results?, reinforce?)
      → [RecallResult]
      行为: 默认只读（reinforce=False）
             只有 reinforce=True 时才触发 Mode A 强化
             browse/explore 场景不改写 strength/access_count

    capture(content, type?, importance?, tags?, origin?, session_id?, event_id?)
      → engram_id
      行为: 写入长期记忆（engrams 表）
             session_id / event_id 记录来源

    ingest_observation(content, tool?, files?, tags?, session_id?)
      → { event_id, promoted, merged_with? }
      行为: 独立的 observation pipeline（见 23.2.1.3）
             经去重/晋升后决定是否落 engrams

    status()
      → { engram_count, session_count, pending_observations, ... }

    forget(engram_id)
      → bool
      行为: 软删除（forgotten=1）

边界规则：
- `recall` 默认只读，显式 `reinforce=True` 才允许强化
- `capture` 只写长期记忆（engrams 表）
- `ingest_observation` 只写 observation pipeline，经过去重/晋升后再决定是否落 engrams
- `session_end` 负责生成和持久化 session summary，不直接污染长期记忆层

#### 23.2.1.3 Observation Ingestion Pipeline

observation 不是 capture 变体。如果自动 observation 大量写入，没有去重、合并、晋升规则，
检索面会很快被低信任碎片占满。所以 pipeline 是**独立的一级系统**。

**两段式去重 + 晋升策略**：

    observation 进入
        │
        ├─ Stage 1: Exact / Near-Exact Fingerprint Dedup
        │   计算 fingerprint = hash(normalize(content))
        │   查 session_events 最近 N 条同 fingerprint → 跳过
        │   ⚠️ 单纯 embedding 阈值很脆，所以先做精确去重
        │
        ├─ Stage 2: Semantic Candidate Merge
        │   生成 embedding，查 engrams 相似度 > 0.85 的候选
        │   附加检查：
        │     - type + tags 是否一致
        │     - files/path 是否重叠
        │     - 时间窗口（同一 session 内 or 最近 1h）
        │   三项至少匹配两项 → 合并到已有 engram
        │   否则 → 视为新 observation
        │   ⚠️ 避免把相近但不等价的 observation 合并掉
        │
        └─ Stage 3: Promotion Decision
            新 observation 是否晋升为 engram？
            规则：
            - 同一 observation 在 ≥2 个不同 session 出现 → 晋升
            - 用户显式 verify → 晋升
            - importance = high / critical → 直接晋升
            - 其他 → 仅存 session_events，不落 engrams

晋升后的 engram 属性：
- `origin = "agent"`, `verified = 0`
- `strength = 0.5`（agent 未验证上限）
- `source_session_id` + `source_event_id` 记录来源

#### 23.2.1.4 recall 默认只读改造

v0.1 的 recall 在 Mode A 下默认触发再巩固（写 strength + access_count）。
这导致"只是浏览一下上下文"也会改写记忆状态，不合理。

v0.2 的改造：
- API 层 `recall()` 默认 `reinforce=False`（只读）
- 只有显式传 `reinforce=True` 才触发 Mode A 强化
- CLI `memento recall` 默认行为改为只读，新增 `--reinforce` 标志
- 保持 Mode B 的 read-only 语义不变（评估用）

#### 23.2.1.5 CLI 适配

新增 `session` 子命令组：

```bash
memento session start [--project PATH] [--task "描述"] [--format json|text]
  # 输出 session_id + priming memories

memento session end <session_id> [--outcome completed|abandoned|error] [--summary "摘要"]
  # 结束会话，存储摘要到 sessions.summary

memento session status [session_id]
  # 查看当前活跃会话 / 指定会话详情

memento session list [--project PATH] [--limit 10]
  # 列出最近会话
```

现有命令扩展：

```bash
memento recall <query> [--reinforce]
  # 新增 --reinforce 标志，默认只读

memento observe <content> [--tool TOOL] [--files "a.py,b.py"] [--tags "a,b"]
  # ingest_observation 的 CLI 入口
```

#### 23.2.1.6 Agent Hook 升级

`scripts/memento-agent.sh` 从"固定调用点"升级为"基于 session lifecycle"：

```bash
memento_session_start() {
  memento_project_env
  local task="${1:-}"
  local result
  result=$(memento session start --project "$(pwd)" ${task:+--task "$task"} --format json 2>/dev/null)
  if [ $? -eq 0 ] && [ -n "$result" ]; then
    # 用 Python 提取 session_id，不依赖 jq
    export MEMENTO_SESSION_ID=$(python3 -c \
      "import json,sys; print(json.loads(sys.stdin.read()).get('session_id',''))" \
      <<< "$result" 2>/dev/null)
    if [ -z "$MEMENTO_SESSION_ID" ]; then
      unset MEMENTO_SESSION_ID
    fi
  else
    # 降级：直接 recall
    memento recall "项目概况" --format json 2>/dev/null || true
  fi
}

memento_session_end() {
  if [ -n "$MEMENTO_SESSION_ID" ]; then
    memento session end "$MEMENTO_SESSION_ID" \
      --outcome "${1:-completed}" \
      ${2:+--summary "$2"} 2>/dev/null || true
    unset MEMENTO_SESSION_ID
  fi
}

memento_observe() {
  memento observe "$1" ${2:+--tool "$2"} ${3:+--tags "$3"} 2>/dev/null || true
}

# Agent wrapper 根据子进程退出码决定 outcome
claude_memento() {
  memento_session_start
  claude "$@"
  local exit_code=$?
  if [ $exit_code -eq 0 ]; then
    memento_session_end "completed"
  else
    memento_session_end "error"
  fi
  return $exit_code
}
```

未来接入事件驱动（hooks）时，这些函数就是 Claude Code / Gemini CLI 的适配器入口。
当前阶段不上常驻进程，CLI 直接调用即可。但异步 ingestion/queue 层大概率在 v0.3 需要。

#### 23.2.1.7 v0.2 砍掉的一切

- ~~常驻进程 / Worker Service~~ → v0.3（见 23.2.2）
- ~~MCP Server~~ → v0.3（见 23.2.2）
- ~~hooks.json 自动注册~~ → v0.3（见 23.2.2）
- ~~OpenAI Function Schema~~ → v0.5
- ~~session_artifacts 表~~ → sessions.summary 够用，需要时再加
- ~~LLM 自动汇总~~ → v0.5（summary 由调用方提供）
- ~~三轨节律 / CQRS~~ → v0.5

**交付物**：`pip install memento` v0.2 → Session Lifecycle + Observation Pipeline + 统一 API。

### 23.2.2 v0.3 "Runtime 集成闭环"

> **v0.3 的核心目标**：闭合 agent-runtime 集成环路。
> Agent 安装 plugin 后，记忆采集和会话管理自动运行，用户无感知。
> v0.2 建立了 session/event/engram 三层分离，v0.3 在其上接入 Claude Code 的 hooks 和 MCP 协议。

**架构**：双进程模型

    Claude Code
      ├── MCP (stdio) → MCP Server 进程 → SQLite (直接访问，同进程)
      │                  直接 import api.py，不走 Worker
      │
      ├── Hooks (shell) → Worker Service (Unix Domain Socket)
      │     SessionStart → POST /session/start {claude_session_id from stdin, project}
      │     PostToolUse  → POST /observe {claude_session_id, content, tool, files}
      │     Stop         → POST /flush (仅清空队列，不结束会话)
      │     SessionEnd   → POST /session/end；仅当 active_session_ids 为空时再 POST /shutdown
      │
      └── Worker Service → SQLite (单 DB 线程独占 Connection)
            Socket: /tmp/memento-worker-{hash(db_path)[:12]}.sock

**关键设计决策**：

1. **MCP Server 和 Worker 独立进程**：MCP 走 stdio 直接调 api.py；Worker 走 Unix Socket 接收 hook 事件。两者通过 SQLite WAL 共享数据
2. **Hook 上下文从 stdin 读取**：Claude Code 通过 stdin JSON 传递 `session_id`、`tool_name`、`tool_input`、`tool_response`，不是环境变量
3. **单 DB 线程模型**：Worker 的 HTTP 线程只投命令不碰 DB，DB 线程独占 Connection 消费双队列（obs_queue + cmd_queue）
4. **Unix Socket 天然隔离**：socket 路径包含 DB 哈希，不同项目不会串库
5. **Stop ≠ SessionEnd**：Stop 只 flush 队列（Agent 暂停但会话继续），SessionEnd 才真正结束会话

**v0.5 架构演进**（在 v0.3 基础上新增）：

6. **三轨分离**：Worker 内部分为 Awake 轨道（DB 线程，独占连接 A）+ Subconscious 轨道（后台线程，独占连接 B），通过 PulseEvent 内存队列通信
7. **Worker fail-fast**：DBThread 使用 `init_event` + `init_error` 机制，初始化失败时 WorkerServer 立即抛出异常，不带伤启动（v0.5.1a）
8. **WorkerClientAPI**：统一 Unix Socket HTTP 客户端，CLI/MCP/外部调用方可通过 `WorkerClientAPI(socket_path)` 访问 Worker，返回类型与 `LocalAPI` 一致（StatusResult 等 dataclass 通过 `from_dict` 反序列化）（v0.5.1a）
9. **Epoch 独立子进程**：`memento epoch run` 作为独立进程连接同一 SQLite（WAL 并发），不走 Worker HTTP

**MCP Server 能力**：

- 7 Tools：session_start/end, recall, capture, observe, status, forget
- 2 Resources：vault/stats, vault/recent
- 1 Prompt：memento_prime（生成 priming context）

**v0.3 明确不做**：

- ~~OpenAI Function Schema~~ → v0.5
- ~~LLM 自动汇总~~ → v0.5
- ~~三轨节律 / CQRS~~ → v0.5
- ~~持久化队列~~ → 进程内 Queue 足够
- ~~Plugin 市场发布~~ → 先本地安装验证

**交付物**：Claude Code Plugin（hooks + MCP + Worker）→ 用户无感知的自动记忆采集。

### 23.3 各版本新增能力矩阵（更新于 2026-04-03）

| 能力 | v0.1–0.3 | v0.5 | v0.6.0 | v0.6.1 | v0.7 | v0.8 | v0.9 | v0.9.2 | v1.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| capture / recall (CLI) | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| 惰性衰减 + 再巩固 | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| Session Lifecycle + Observation Pipeline | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| MCP Server (14 Tools + 4 Resources + Prompt) | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| Plugin Hooks + `memento plugin install claude` | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| Worker Service（双队列 + Unix Socket） | ✅ | Y | Y | Y | Y | Y | Y | Y | Y |
| 三轨节律 + CQRS + 五态状态机 | - | ✅ | Y | Y | Y | Y | Y | Y | Y |
| Delta Ledger + Rigidity 衰减 | - | ✅ | Y | Y | Y | Y | Y | Y | Y |
| Nexus 关联网络 + Hebbian 学习 | - | ✅ | Y | Y | Y | Y | Y | Y | Y |
| Subconscious 硬化（delta 去重、recon 清理、结构化日志） | - | ✅ | Y | Y | Y | Y | Y | Y | Y |
| awake_recall 向量/FTS5 检索（修复 LIKE 降级） | - | - | ✅ | Y | Y | Y | Y | Y | Y |
| capture exclusion rules（tool description） | - | - | ✅ | Y | Y | Y | Y | Y | Y |
| staleness_level 字段（fresh/stale/very_stale） | - | - | ✅ | Y | Y | Y | Y | Y | Y |
| recall 返回 tags / origin | - | - | ✅ | Y | Y | Y | Y | Y | Y |
| memento_prime 增强（staleness 提示） | - | - | ✅ | Y | Y | Y | Y | Y | Y |
| session-end 自动摘要兜底（非 LLM，复用 summary 字符串） | - | - | - | ✅ | Y | Y | Y | Y | Y |
| auto_captures_count 响应字段 | - | - | - | ✅ | Y | Y | Y | Y | Y |
| memento://daily/today 资源 | - | - | - | ✅ | Y | Y | Y | Y | Y |
| LLM 调用基建（配置、计量、回退） | - | - | - | - | ✅ | Y | Y | Y | Y |
| Phase 2: L2→L3 LLM 结构化 | - | - | - | - | ✅ | Y | Y | Y | Y |
| Phase 5: 再巩固（受 rigidity 门控） | - | - | - | - | ✅ | Y | Y | Y | Y |
| Epoch light 自动触发（session_end） | - | - | - | - | ✅ | Y | Y | Y | Y |
| Nexus 边衰减 | - | - | - | - | ✅ | Y | Y | Y | Y |
| T5 抽象化（低频 engram 聚类） | - | - | - | - | ✅ | Y | Y | Y | Y |
| Web Dashboard（FastAPI + Vue 3 SPA） | - | - | - | - | - | ✅ | Y | Y | Y |
| Dashboard 记忆浏览/搜索/过滤 | - | - | - | - | - | ✅ | Y | Y | Y |
| Dashboard verify/delete/pin 操作 | - | - | - | - | - | ✅ | Y | Y | Y |
| Dashboard 会话/系统视图 + Epoch 触发 | - | - | - | - | - | ✅ | Y | Y | Y |
| 离线可用（本地 vendor 文件） | - | - | - | - | - | ✅ | Y | Y | Y |
| Stop hook transcript extraction | - | - | - | - | - | - | ✅ | Y | Y |
| transcript 增量解析 + 净化 | - | - | - | - | - | - | ✅ | Y | Y |
| LLM 对话记忆提取（强制 JSON 输出） | - | - | - | - | - | - | ✅ | Y | Y |
| 已有记忆去重（content_hash + prompt 注入） | - | - | - | - | - | - | ✅ | Y | Y |
| Worker `/transcript/extract` 路由 + DBThread 边界 | - | - | - | - | - | - | ✅ | Y | Y |
| per-session 并发锁 + durable cooldown | - | - | - | - | - | - | ✅ | Y | Y |
| hook 投递可观测性（stderr 日志） | - | - | - | - | - | - | ✅ | Y | Y |
| L0/L1/L2 分层 priming | - | - | - | - | - | - | - | P | Y |
| 本地嵌入默认 provider | - | - | - | - | - | - | - | P | Y |
| 跨项目记忆隔离（project boundary） | - | - | - | - | - | - | - | P | Y |
| Nexus invalidated_at + active-only 查询 | - | - | - | - | - | - | - | P | Y |
| Nexus 自动失效 / 手动失效 / 复活 | - | - | - | - | - | - | - | P | Y |
| Fork / PR / Merge | - | - | - | - | - | - | - | - | Y |
| 联邦协议 EFP + 跨实例身份 | - | - | - | - | - | - | - | - | Y |
| 隐私系统 + 加密粉碎 | - | - | - | - | - | - | - | - | Y |
| ~~归属自动判定~~ | **已移除** | - | - | - | - | - | - | - | - |
| ~~集体智能涌现~~ | **已移除** | - | - | - | - | - | - | - | - |

> **v0.5 交付记录**：
> - **v0.5.0**（核心架构）：五态状态机、Delta Ledger、LLM 抽象化、rigidity、Nexus、三轨节律、CQRS。
> - **v0.5.1a**（基础设施补强）：Worker fail-fast、WorkerClientAPI、from_dict 方法。
> - **v0.5.1b**（E2E 集成 + 打包）：Worker use_awake 修复、集成测试、hook-handler.sh 安全修复、entry points、`memento plugin install claude`。
> - **v0.5.1c**（Subconscious 硬化）：rigidity 影响衰减速率、delta_ledger 去重、recon_buffer 清理、结构化日志。
>
> **v0.7 已完成**：LLM 管线、Phase 2 L2→L3 结构化、Phase 5 再巩固、Epoch 自动触发、T5 抽象化。
> **v0.8 已完成**：本地 Web Dashboard（FastAPI + Vue 3 SPA）。
> **v0.9 已完成**：Conversation Memory Extraction（Stop hook + transcript 增量提炼 + LLM 自动提取）。
> **v0.9.2 设计已完成，待实现**：分层上下文注入（L0/L1/L2 三层 priming）、本地嵌入优先（`provider="local"` 默认）、时序 Nexus 生命周期（`invalidated_at` + 自动失效 + 复活）。详见 `docs/superpowers/specs/2026-04-10-v092-mempalace-inspired-enhancements-design.md` 与 `docs/superpowers/plans/2026-04-10-v092-mempalace-enhancements.md`。
> **推后到 v1.0**：Fork/PR/Merge、OperationLog 合并、隐私系统、Diplomat Agent、Project Vault、生态层、LongMemEval。

### 23.3.1 v0.6.0 "检索修复 + Agent 感知增强"（已完成）

**核心问题**：v0.5 的 `awake_recall()` 使用 `LIKE '%query%'` 匹配，未接入向量检索和 FTS5，导致通过 MCP/Worker 调用的 recall 是严重降级版本。中文和语义检索几乎无法命中。

**P0: awake_recall 接入向量/FTS5**

将 `core.py` 的完整检索管线（向量余弦 → FTS5 BM25 → effective_strength 打分）接入 `awake_recall()`，同时保持 L2 capture_log 的双源查询能力。

**P1: capture exclusion rules**

在 MCP `memento_capture` tool description 和 `memento_prime` prompt 中加入排除指导：
- 不记：代码结构/文件路径（可从 codebase 推导）、Git 历史、临时调试方案、CLAUDE.md 已有内容、当前 session 临时状态
- 只记：删掉后下次会犯同样错误的知识

借鉴自 Claude Code 的 `memoryTypes.ts` exclusion rules。

**P2: staleness_level 字段**

recall 返回值增加 `staleness_level` 分级信号：
- `fresh`：effective_strength > 0.6
- `stale`：0.3 < effective_strength ≤ 0.6
- `very_stale`：effective_strength ≤ 0.3

借鉴自 Claude Code 的 `memoryAge.ts` staleness warning。

**P3-P4**：recall 返回 tags/origin、memento_prime 增强。

> 实现说明：
> - `staleness_level` 已在 `awake_recall()` 中落地，阈值为 `>0.6=fresh`、`>0.3=stale`、`<=0.3=very_stale`。
> - `memento_prime` 当前使用中性提示文案：`⚠️较旧` / `⏳可能过时`，而不是更强烈的失效判断。
> - `capture exclusion rules` 已进入 MCP `memento_capture` tool description，并同步进入 priming 指导。

### 23.3.2 v0.6.1 "摄取安全网 + 自动摘要兜底"（已完成）

**前置条件**：v0.6.0 完成，awake_recall 检索质量已修复。

**核心目标**：在不引入 LLM 依赖的前提下，为 session 结束阶段补上保守的摄取安全网，避免高价值 summary 仅停留在 `sessions.summary` 而不进入后续 L2/L3 流转通道。

**P0: session_end 自动摘要兜底（非 LLM）**

`LocalAPI.session_end()` 在以下条件同时满足时，将调用方提供的 `summary` 作为低信任 fallback capture 写入 `capture_log`：
- `summary` 非空
- 本 session 的显式摄取总量不足 2（`capture_log WHERE source_session_id = ?` 的 capture 数 + `session_events` 中 observation 数）
- 同 session 内不存在相同 `content_hash` 的 capture

写入规则：
- 通过 `awake_capture(origin='agent')` 写入，保持低信任边界
- 仅做 `content_hash` 级去重（保守策略，不做语义去重）
- 返回 `auto_captures_count` 供 API / MCP / Worker 上报

**P1: SessionEndResult / MCP 响应扩展**

`SessionEndResult` 新增：
- `auto_captures_count`

`memento_session_end` MCP 返回：
- `status`
- `captures_count`
- `observations_count`
- `auto_captures_count`

**P2: `memento://daily/today` 资源**

新增 MCP Resource：`memento://daily/today`
- 合并当日 `capture_log` 与 `session_events`
- `capture_log` 仅返回 `epoch_id IS NULL` 的未消费 buffer 项
- 输出按 `created_at` 排序的 append-only timeline

> 已知限制：当前 `today` 判定基于本地日期前缀比较，尚未统一到严格 UTC 时间窗。

**关键架构说明：awake capture 与 session_events 脱钩**

默认 awake 模式下：
- `capture()` → 写入 `capture_log`
- **不会**追加 `session_events.capture`

因此，session_end 自动摘要的抑制逻辑不能依赖 `SessionEndResult.captures_count`，而必须直接查询 `capture_log WHERE source_session_id = ?`。这与 legacy 非 awake 路径不同，属于 v0.6.1 实现中明确确认的架构差异。

### 23.3.3 v0.7.0 "LLM 管线 + Epoch 智能化"

**前置条件**：v0.6.1 的摄取安全网已稳定，capture_log 输入覆盖率提升。

**P0: LLM 调用基建**

`llm.py` 已有 OpenAI-compatible 客户端框架，补充：token 消耗计量、请求级重试、无 LLM 时的优雅降级（defer_to_debt）。

**P1: Phase 2 L2→L3 LLM 结构化**

Epoch full mode 中，capture_log 条目经 LLM 结构化后写入 engrams：
- 自动补全 type、tags、关联 engram
- 合并语义重复条目
- 当前 auto-promote 逻辑作为 LLM 不可用时的回退

**P2: Phase 5 再巩固**

高频 recall 的 engram（recon_buffer 中有记录）经 LLM 精炼内容，受 rigidity 门控（rigidity ≥ 0.5 → 跳过内容修改）。

**P3: Epoch light 自动触发**

session_end 时自动运行 light epoch（已有 hook-handler.sh 中的 flush-and-epoch 逻辑，需要优化触发条件）。

**P4: Nexus 边衰减**

长期未激活的 Nexus 边 association_strength 按时间衰减，与 engram strength 衰减机制对称。

> 后续实现已在 v0.9.2 中收敛为更完整的 Nexus 生命周期语义：通过 `invalidated_at` 支持 soft invalidation，默认查询仅返回 active 边，并允许在再次 coactivation 时复活原边。这一实现替代了早期仅以“边衰减”概括的笼统表述。

**P5: session-end 自动摘要（LLM transcript 分析版）**

会话结束时，分析 `session_events` transcript，自动提炼 1–3 个候选 capture/observation。该能力建立在 v0.6.1 的非 LLM fallback 之上，新增：
- transcript 级候选提炼
- 更细粒度的互斥/抑制逻辑（不再是简单布尔判断）
- 与 observation / capture 的去重协同

**P6: T5 抽象化**

低频 engram 聚类 → 生成抽象语义节点（abstracted 态）。需要 LLM + embedding 聚类。

**P7: WorkerClientAPI 完善**

MCP Server 通过 Worker Unix Socket 访问 DB（进程隔离），而非当前的直连 DB。

### 23.3.4 v0.8.0 "Web Dashboard"（已完成）

**核心目标**：为 Memento 提供本地 Web Dashboard，作为运维观察面板，替代 CLI 的 `recall --format json` 工作流。

**技术栈**：FastAPI + Vue 3（CDN-free 本地 vendor，无构建步骤）+ `LocalAPI` 直连数据层。

**交付内容**：

- `memento dashboard` CLI 命令（端口 8230，自动打开浏览器）
- 12 个 REST API 端点（engrams/sessions/epoch/captures CRUD）
- 三个前端视图：
  - **记忆视图**：浏览、实时搜索、类型/来源/重要性过滤、强度可视化、verify/delete/pin 操作
  - **会话视图**：会话列表、项目过滤、展开查看摘要和事件统计
  - **系统视图**：系统状态、Epoch 历史、认知债务、L2 缓冲区、触发 Epoch
- 离线可用（Vue 3 + Vue Router vendor 文件内嵌仓库）
- `pip install memento[dashboard]` optional dependency
- 20 个 API 测试

**架构约束**：
- Dashboard 是 UI on top of existing API/domain，不是第二套核心逻辑
- 所有读写通过 `LocalAPI`，route 不直接访问 SQLite
- 仅监听 `127.0.0.1`，不暴露到网络
- 详见 `docs/superpowers/specs/2026-04-02-dashboard-design.md`

### 23.3.5 v0.9.0 "Conversation Memory Extraction"（已完成）

**前置条件**：v0.7 LLM 管线已稳定，v0.8 Dashboard 提供记忆可视化。

**核心问题**：当前自动采集对象是工具事件（PostToolUse → observe），记录的是"读了什么文件"、"执行了什么命令"。这些对追踪 Agent 行为有用，但对跨会话知识积累来说太低级。用户需要的是对话中的高价值结论——偏好、决策、约定、事实。

**核心变革**：从 event ingestion 升级到 conversation memory extraction。

**实现架构**：

```
Stop hook (flush-and-epoch)
    │
    ├─ flush（不变）
    │
    ├─ POST /transcript/extract → Worker（异步投递）
    │       │
    │       ├─ session_registry: claude_session_id → memento_session_id
    │       ├─ should_extract(): 内存快路径节流（5 分钟）
    │       ├─ transcript_get_context (DBThread):
    │       │     ├─ runtime_cursors → last_offset
    │       │     ├─ updated_at → durable cooldown
    │       │     └─ view_engrams top 30 → existing_memories_summary
    │       │
    │       └─ 后台线程 run_extraction():
    │             ├─ per-session lock（trylock，并发直接 skip）
    │             ├─ read_transcript_delta（增量，容错 malformed）
    │             ├─ clean_transcript（去代码块/工具输出/长行，窗口 10 轮）
    │             ├─ LLM 提取（强制 JSON，4 类型过滤，已有记忆注入）
    │             ├─ parse_llm_response（markdown 剥离，类型/重要性校验）
    │             └─ persist_callback → DBThread transcript_persist:
    │                   ├─ content_hash 去重（capture_log + engrams）
    │                   ├─ awake_capture（origin='agent', tags=['transcript-extracted']）
    │                   └─ runtime_cursors cursor 更新（成功后才推进）
    │
    └─ epoch 节流判断（不变）
```

**交付内容**：

| 文件 | 职责 |
|------|------|
| `src/memento/transcript.py` | 纯函数：transcript 解析、净化、LLM 响应解析、content hash、节流、per-session 锁、编排器 |
| `src/memento/prompts.py` | 新增 `build_transcript_extraction_prompt()` |
| `src/memento/worker.py` | 新增 HTTP 路由 `/transcript/extract` + DBThread actions `transcript_get_context` / `transcript_persist` |
| `plugin/scripts/hook-handler.sh` | `flush-and-epoch` 分支新增 transcript extraction 投递 + 可观测性日志 |
| `tests/test_transcript.py` | 18 个测试（解析、净化、JSON 剥离、节流、E2E mock LLM、失败不推进 cursor） |

**关键设计决策**：

1. **DBThread 边界严格守住**：`transcript.py` 不导入 sqlite3，不调用 awake_capture。所有 DB 操作通过 `DBThread.execute()` 回到主线程执行。后台线程只做文件 I/O 和 LLM 调用。

2. **游标持久化 + durable cooldown**：offset 存储在 `runtime_cursors` 表，Worker 重启后恢复。cooldown 基于 `runtime_cursors.updated_at` 而非纯内存，重启不会绕过冷却。

3. **并发安全**：per-session `threading.Lock` + 非阻塞 trylock。同 session 的第二个 extraction 直接 skip，不排队。加上 DBThread 在 `transcript_get_context` 时立即更新 `updated_at`（durable lock），防止并发窗口。

4. **cursor 只在成功后推进**：LLM 调用失败 → callback 不被调用 → cursor 不推进 → 下次 Stop hook 自动重试。

5. **过滤策略**：只提取 preference / convention / decision / fact 四种类型，强 suppress 工具过程、调试碎片、代码实现。**原则：宁可漏，不可脏。**

6. **信任模型不变**：提取结果固定 `origin='agent'`，强度上限 0.5，需用户 `memento verify` 解除。

7. **observe 管线保持不变**：P1 不调整现有 observation 语义，两套管线并行互不干扰。

8. **可观测性**：hook 投递失败（Worker 不可达、响应异常、非 JSON）全部输出到 stderr，不再静默吞掉。

**已知限制（不影响当前使用，后续迭代可改进）**：
- per-session 锁是进程级别，多 Worker 进程场景需 DB 级 lease
- `updated_at` 同时承担 cursor 更新时间和 cooldown 起点双重语义
- 语义去重（向量相似度）在 P1 未实现，当前仅做 content_hash 精确去重 + prompt 注入已有记忆
- 不新建 `memory_candidates` 表，候选生命周期不可独立审计（如需要可在 P2 引入）

详见 `docs/superpowers/specs/2026-04-03-conversation-memory-extraction-design.md`

### 23.4 v0.1 验证实验设计

v0.1 的目标不是功能完整，是**验证一个假设**：

> **衰减 + 再巩固是否比纯向量搜索 + 时间排序更好？**

**A/B 实验设计**：

    实验方法: 快照隔离对照 (消除副作用串扰)

      Mode A (实验组): effective_strength × similarity (衰减 + 强化加权)
      Mode B (基线组): similarity × recency_bonus     (纯向量相似度 + 时间衰减)
        recency_bonus = 1.0 / (1 + hours_since_created * 0.01)  # 简单时间排序

      隔离策略 — 解决副作用串扰:
        v0.1 的 recall() 会更新 strength/access_count/last_accessed（读即写）。
        如果 A/B 共享同一数据库，A 的强化副作用会污染 B 的后续查询，
        测到的是"混合系统"而非严格对照。

        方案: 快照分叉 + 只读评估
        1. 实验开始前，复制数据库为两份:
           ~/.engram/eval_mode_a.db  (实验组)
           ~/.engram/eval_mode_b.db  (基线组)
        2. 日常使用照常跑 Mode A (主库)，正常产生副作用
        3. 评估时: memento eval --mode B --db eval_mode_b.db --queries eval_queries.json
           对 Mode B 副本执行相同查询集，但不写入副作用 (只读评估)
        4. 对比两组返回结果的排序质量

        这样 Mode A 是"真实使用两周后的活系统"，
        Mode B 是"同一起点、无强化副作用的冻结系统"，
        差异 = 衰减+强化机制的净效果。

      切换方式: memento recall --mode A|B (日常使用)
            memento eval --queries file.json (实验评估，只读)

    标注集构建 (实验开始前准备):
      1. 预置 50~100 条覆盖多类型的记忆 (fact/decision/convention/debugging)
      2. 手工编写 30 条查询 + 每条查询的"期望 top-3 结果" (人工标注)
      3. 标注"已过时"记忆: 故意插入 5~10 条过时信息
         (旧 API 端点、旧配置、已修复的 bug 记录)
      4. 初始状态设定 (两个库共享同一起点):
         - 部分记忆: 一周前创建，从未 recall (冷记忆, access_count=0)
         - 部分记忆: 三天前创建，被 recall 5 次 (温记忆, access_count=5)
         - 部分记忆: 一月前创建，被 recall 20 次 (高频记忆, access_count=20)
         - 部分记忆: 一月前创建，但昨天刚 recall (间隔强化, access_count=3)
         注意: access_count 的差异必须足够大（0/5/20 而非 0/1/3），
         否则强化增益在短期实验中不可观测

    量化指标:

      | 指标 | 计算方法 | 优于阈值 |
      |------|---------|---------|
      | Precision@3 | top-3 中命中标注集期望结果的比例 | A > B + 15% |
      | MRR (Mean Reciprocal Rank) | 第一个正确结果的排名倒数的均值 | A > B + 0.1 |
      | 过时记忆抑制率 | "已过时"标注的记忆出现在 top-5 的频率 | A 比 B 降低 50%+ |
      | 冷记忆自然下沉 | 一周未触碰的记忆的平均排名变化 | A 中排名明显下降 |

      性能指标 (不区分 A/B):
      | 指标 | 目标 |
      |------|------|
      | recall 延迟 | < 50ms (p99) |
      | capture 延迟 | < 200ms (含 embedding) |

    实验流程:
      Day 0:  构建标注集 + 复制快照 (eval_mode_b.db)
      Week 1: 用 Mode A 正常工作，积累真实的 recall/capture 行为
      Day 7:  中期评估 — 运行 memento eval，主要观测:
              · 过时记忆抑制率 (衰减效果，7 天内应已显现)
              · 冷记忆自然下沉 (同上)
              · 强化增益可能尚不明显 — 仅记录，不做最终判定
      Week 2: 继续用 Mode A 正常工作，强化增益的复利效应开始显现
      Day 14: 最终评估 — 运行 memento eval，完整对比所有指标
      Day 15: 对 eval 结果做人工评分 (1-5 分，"这个结果有用吗")
              汇总 Precision@3 / MRR / 过时抑制率，做决定

      ⚠️ 为什么需要 2 周而非 1 周:
      access_count 的积累是缓慢的复利过程。7 天内大部分记忆
      access_count 仅 0-2，强化增益 boost = min(0.1, 0.05*(1+log(1+h)))
      几乎看不出差异。2 周后高频记忆的 access_count 达到 5-10，
      强化的"越用越记得牢"效应才开始与衰减形成有意义的对比。
      但过时记忆抑制（衰减主导）在 7 天时已可观测 — 中期评估
      的作用是提前发现衰减是否有效，避免等 2 周才发现基本假设不成立。

      日志格式 (自动记录):
        { query, mode, db, results: [{id, rank, score}], timestamp }

**v0.1 → v0.2 的升级判定**：

*   Precision\@3 提升 > 15% **且** 过时记忆抑制率降低 > 50% → 衰减+强化模型验证通过，进入 v0.2（agent-runtime 集成层：Session Lifecycle + 统一 API + Observation Pipeline）
*   提升 < 15% 但方向正确 → 调参后重测一轮
*   无提升或反而更差 → 重新审视整个设计哲学

***

### 3.13 ClaimRecord（结构化事实断言）

系统中涉及事实冲突检测、断言矛盾判定、merge survival 等场景时，纯文本 + embedding 不足以支撑机器校验。对于"可冲突"的记忆，引入结构化 claim 层作为事实仲裁的基础。

    ClaimRecord {
      id:                   UUID
      engram_id:            Engram.id           # 所属 Engram

      # === 结构化断言 ===
      subject:              string              # 主语（实体）: "水"
      predicate:            string              # 谓语（关系）: "沸点为"
      object:               string              # 宾语（值）  : "100°C"

      # === 时空限定 ===
      valid_from:           timestamp | null    # 断言生效时间
      valid_until:          timestamp | null    # 断言失效时间（null = 持续有效）
      context_scope:        string | null       # 适用范围: "标准大气压下"

      # === 来源与置信 ===
      source_type:          observed | measured | reported | inferred | claimed
      source_ref:           string | null       # 具体来源引用
      confidence:           float [0, 1]        # 置信度
      evidence_refs:        [Engram.id]         # 支撑证据的 Engram 引用

      # === 冲突检测 ===
      claim_key:            string              # hash(subject + predicate + context_scope)
                                                # 相同 claim_key 的记录构成"主题组"（非直接冲突组）
      contradiction_of:     ClaimRecord.id | null  # 如果是对某断言的显式反驳
    }

**设计要点**：

*   并非所有 Engram 都需要 ClaimRecord——仅当 Engram 包含可被验证/反驳的事实性断言时才生成
*   Epoch 期间由 LLM 从 Engram content 中提取 ClaimRecord（类似 NER + 关系抽取）
*   `claim_key` 实现同主题断言的自动分组（注意：相同 claim\_key 不等于冲突，还需时间区间重叠判定，见下方冲突检测流程）

**实体对齐层 (Entity Resolution) — 防止本体论爆炸**：

> 开放域的 LLM 提取极不稳定。同一事实可能被提取为 "React RSC / 渲染于 / 服务端" 和 "React Server Components / 执行在 / Node 环境"。两者 claim\_key 完全不同，冲突检测被架空，系统堆积海量孤立 ClaimRecord。

    提取流程 (带实体对齐):

      1. LLM 提取原始三元组: (subject_raw, predicate_raw, object_raw)

      2. 实体对齐 — 在已有实体库中 Fuzzy Match:
         local_entities = SELECT DISTINCT subject FROM claim_records
         local_predicates = SELECT DISTINCT predicate FROM claim_records

         matched_subject = fuzzy_match(subject_raw, local_entities, threshold=0.85)
         matched_predicate = fuzzy_match(predicate_raw, local_predicates, threshold=0.85)

         if matched_subject found:
           subject = matched_subject    # 复用已有实体，不创建新的
         else:
           subject = subject_raw        # 真正的新实体，入库
           # 可选: LLM 二次确认 "React RSC 和 React Server Components 是同一实体吗？"

         predicate 同理

      3. 生成 ClaimRecord 使用对齐后的 subject/predicate
         → claim_key = hash(aligned_subject + aligned_predicate + context_scope)
         → 同一事实的不同表述现在会产生相同的 claim_key

      实体库维护:
        - 实体库随 Epoch 自然增长，初始为空
        - 每次新实体入库时，LLM 检查是否与已有实体为同义词
        - 实体合并: 发现同义词 → 更新所有引用该实体的 ClaimRecord 的 claim_key

*   Merge 冲突解决中（6.5 节），"事实性冲突"的判定不再依赖 LLM 自由文本判断，而是基于 ClaimRecord 的结构化比对
*   漂移统计的 `assertion_alignment`（19.2 节，已降格为研究备忘）可参考 ClaimRecord 进行观测，但不触发自动断裂

**冲突检测流程（两层判定）**：

    Epoch 期间:
      1. LLM 从新入库的 Engram 提取 ClaimRecord
      2. 按 claim_key 检索已有 ClaimRecord（主题归组）
      3. 同一 claim_key 下，先做时间区间判定:

         时间区间判定:
           A.valid_period = [valid_from, valid_until]  (null 视为 -∞ 或 +∞)
           B.valid_period = [valid_from, valid_until]

           case 1: 区间不重叠
             → 时序更新 (Temporal Succession)，非冲突
             → 两条 ClaimRecord 都保留，按时间排序
             → 示例: "CEO 是 A (2020-2024)" 和 "CEO 是 B (2025-)" → 正常演替

           case 2: 区间重叠 且 object 一致
             → 互相增强 confidence

           case 3: 区间重叠 且 object 矛盾
             → 标记为 FactConflict，保留双方版本

           case 4: 区间重叠 且 object 部分重叠
             → 标记为 pending_review

           case 5: 双方都没有时间信息 (valid_from = null, valid_until = null)
             → 视为"默认全时段有效"，区间重叠，走 case 2/3/4

      4. FactConflict 的解决:
         - 有明确 evidence_refs 且 source_type 更可靠 → 自动采纳
         - 无法自动判定 → 升级为人工审查
         - 绝不静默合并为虚假共识

### 3.14 OperationLog（操作日志）

MemoryPR 的核心载荷。替代旧的快照式 `proposed_engrams` + `proposed_links`，承载 Bob 在 Fork 后执行的所有变更操作。Alice 在 canonical 图上逐条重放这些操作，而非对比两张子图的快照 diff。

    OperationLog {
      log_id:                 UUID
      vault_did:              DID                 # 提交方的稳定身份
      base_projection_hash:   string              # 基于哪个 Projection 版本
      base_source_commit_id:  MemoryCommit.id     # Projection 对应的源 commit（溯源用）

      operations:             [Operation]         # 有序操作列表（按发生时间排序）
      created_at:             timestamp
      signature:              Ed25519             # 提交方签名（防篡改）
    }

**幂等性保证**：`log_id` 是唯一键。接收方收到重复 `log_id` 的 PR 时返回上次的 ReplayReport，不重复执行。

### 3.15 Operation（单条操作）

    Operation {
      op_id:                  UUID
      op_type:                create_engram | modify_engram_content |
                              modify_engram_meta | delete_engram |
                              create_nexus | delete_nexus |
                              create_claim | modify_claim | contradict_claim
      timestamp:              timestamp           # 操作发生时间

      # === 操作目标 ===
      target_id:              UUID | null         # 操作的目标实体 ID
                                                  # create_engram 时为 null（由接收方分配）
                                                  # 以 "local:" 前缀的 ID 是提交方分配的
                                                  # 临时 ID，用于同一 PR 内的前向引用

      # === 操作载荷（按 op_type 不同而不同）===
      payload: {
        # create_engram:
        content:              Text
        type:                 episodic | semantic | procedural
        tags:                 [string]
        claims:               [ClaimRecord]       # 如果包含可验证断言
        suggested_nexus:      [{                  # 提交方认为应建立的关联
          target_id:          UUID                # 指向 Projection 中可见的 Engram
          nexus_type:         string
          reasoning:          string
        }]

        # modify_engram_content:
        content_patch:        TextDiff            # 文本 diff（非全量替换）
        base_content_hash:    string              # 修改前的内容 hash（用于基准校验）
        new_claims:           [ClaimRecord]
        removed_claim_ids:    [UUID]

        # modify_engram_meta:
        field:                string              # tags | type | importance
        old_value:            any                 # 用于乐观锁冲突检测
        new_value:            any

        # delete_engram / delete_nexus:
        reason:               string              # 删除原因（必填，接收方审查用）

        # create_nexus:
        source_id:            UUID
        target_id:            UUID
        nexus_type:           string
        direction:            directed | bidirectional
        reasoning:            string | null

        # contradict_claim:
        target_claim_id:      UUID                # 被反驳的 ClaimRecord ID
        counter_claim:        ClaimRecord         # 反驳断言
        evidence_engram_ids:  [UUID]              # 支撑反驳的 Engram
      }

      # === 溯源 ===
      reasoning:              string | null       # 操作原因（可选，辅助接收方审查）
    }

**前向引用规则**：同一 OperationLog 中，后续操作可引用前序 `create_engram` 分配的 `local:` 前缀临时 ID。重放引擎维护 `local_id → canonical_id` 映射表。引用未定义的 `local:` ID 视为日志损坏，该操作被标记为 dangling。

**操作依赖规则**：如果某条操作依赖的前序操作被标记为 conflict（需人工审查），该操作自动降级为 blocked，等待依赖项解决后重新评估。

### 3.16 ReplayReport（重放报告）

    ReplayReport {
      pr_id:                  MemoryPR.id
      generated_at:           timestamp

      # === 操作分类统计 ===
      total_operations:       int
      applied:                int                 # 成功应用
      skipped_dangling:       int                 # 因引用悬空跳过（不区分噪声/隐私/已删除）
      skipped_conflict:       int                 # 因事实冲突需人工审查
      skipped_unauthorized:   int                 # 因操作越权跳过
      blocked:                int                 # 因依赖项未完成而阻塞

      # === 逐条结果 ===
      results: [{
        op_id:                UUID
        status:               applied | skipped | conflict | unauthorized | blocked
        reason:               string | null       # 跳过/冲突的原因（隐私安全过滤后）
        canonical_id:         UUID | null         # 如果是 create_engram，分配的 canonical ID
      }]

      # === 需人工审查的操作 ===
      pending_review:         [Operation]         # 从 results 中筛出 status=conflict 的
    }

**隐私安全约束**：ReplayReport 返回给提交方时，`skipped` 的原因统一显示为"目标在接收方视图中不可达"。不区分"噪声边"、"隐私过滤"、"已删除"三种子原因——区分会泄露接收方的隐私结构。

***

## 附录：参考的脑科学机制

| 脑科学概念                                   | 系统映射                                     |
| --------------------------------------- | ---------------------------------------- |
| 海马体 (Hippocampus)                       | STM 索引层                                  |
| 新皮层 (Neocortex)                         | LTM 存储层                                  |
| 突触可塑性 (Synaptic Plasticity / LTP / LTD) | Nexus 强度的动态调整                            |
| 记忆再巩固 (Reconsolidation)                 | recall 时的内容修改 + Revision 记录              |
| Ebbinghaus 遗忘曲线                         | Decay Engine 的衰减公式                       |
| 间隔重复 (Spaced Repetition / FSRS)         | 强化效果与间隔时间的关系                             |
| 赫布学习 ("一起激活，一起连接")                      | 同时 recall 的 Engram 之间 Nexus 增强           |
| 睡眠整合 (Sleep Consolidation)              | Epoch 批处理：整合 + 抽象化 + 关联发现                |
| 情绪标记 (Amygdala Tagging)                 | emotional\_valence / intensity 影响优先级和衰减率 |
| 镜像神经元 (Mirror Neurons)                  | Fork 机制：模拟/学习他人经验                        |
| 集体记忆 (Collective Memory)                | Org Vault + 涌现分析                         |

***

## 附录：开放性设计问题

### 已解决

1.  **~~再巩固的"污染"程度~~** → 通过 `rigidity` 参数实现连续光谱控制（见 17.3 节）

2.  **~~抽象化的触发时机和方法~~** → KNN 聚类 + LLM 摘要的两阶段混合架构（见 17.6 节）

3.  **~~性能：读放大~~** → 异步再巩固缓冲池，recall 保持纯读（见 17.2 节）

4.  **~~Snapshot 衰减 vs Hash 链完整性~~** → 墓碑机制，底层不可变、表现层可衰减（见 17.1 节）

5.  **~~隐私图推断攻击~~** → Nexus 级联脱敏 + 拓扑噪声注入（见 17.4 节）

6.  **~~合并冲突地狱~~** → 认知外交官代理，自动分流 95% 冲突（见 17.5 节）

7.  **~~冷启动~~** → 前世记忆摄入管道，旁路 LLM 批处理 + 元数据逆向推断（见第十八章）

8.  **~~记忆版权/忒修斯之船~~** → drift 统计保留为观测指标；自动断裂 (Genesis) 已从主路线移除——归属判定需人类治理（第十九章降格为研究备忘）

9.  **~~多 Agent 共享记忆~~** → Agent 为一等公民，弹性 Epoch 触发策略（见第二十章）


11. **~~联邦协议细节~~** → EFP 协议栈，基于 AT Protocol 风格扩展（见第二十一章）

11. **~~MVP 范围界定~~** → 四阶段演进路线：缸中之脑→社交→联邦（见第二十三章）

13. **~~LLM 依赖度/离线降级~~** → 认知债务池 + Light Sleep / Deep Sleep 降级机制（见 12.7 节）

14. **~~跨模态记忆~~** → 模态统一化网关，入口处强制转文本，系统内部不感知模态（见 12.3.1 节）

15. **~~GDPR 合规~~** → 加密粉碎 (Crypto-shredding)，删密钥=删数据，Hash 链不受影响（见 7.4 节）

16. **~~基准测试~~** → MVP 验证指标已定义（见 22.4 节）

17. **~~被遗忘权派生物覆盖~~** → 扩展 Erasure Manifest 覆盖 content + embedding + summaries + abstractions + logs + caches + replicas；Layer 0/1 预防性隔离（见 7.4 节）

18. **~~联邦同步哈希与隐私投影冲突~~** → 双层对象模型：Canonical Commit DAG (本地校验) + Export Projection Manifest (跨实例校验)（见 5.2 节）

19. **~~缺少结构化事实模型~~** → ClaimRecord 结构化断言层：subject/predicate/object/confidence/evidence\_ref，claim\_key 主题归组 + 时间区间重叠判定真冲突（见 3.13 节）

20. **~~多存储原子提交~~** → StagingManifest + 两阶段提交 + active\_view\_pointer 原子切换 + 崩溃恢复（见 12.5 Phase 4）

21. **~~三轨 strength 归属不清~~** → Delta Ledger 模式：潜意识只写 delta，睡眠轨道折叠为最终值，L3 Truth Store 是唯一权威源（见 12.4 节）

22. **~~capture 后不可 recall~~** → L2 Hot Buffer View：BUFFERED 态可查询但降权 + 显式标记 provisional（见 12.3 节）

23. **~~Epoch 命令排队语义不安全~~** → CommandEnvelope 绑定 intent\_timestamp + base\_commit\_id，语义锚定到用户操作时的逻辑状态（见 12.8 节）

24. **~~ARCHIVED 无搜索路径~~** → Archive Tombstone Index：极小型墓碑索引 (topic\_summary + entity\_tags + 低维 embedding)，支持唤醒候选发现（见 14.4 节）

25. **~~DID 身份模型混淆~~** → 双层标识：稳定 DID did\:engram:\<key-fingerprint> + 可变 Handle user\@instance，Fork/upstream 绑定 DID（见 21.3 节）

26. **~~冷启动旁路风险~~** → Cold Start Safety Rails：导入默认低 strength/confidence/rigidity + cold\_start\_unverified 标签 + 验证提升机制（见 18.5 节）


28. **~~ABSTRACTED 完全冻结过头~~** → Counter-Evidence Layer：内容冻结但允许追加反证 Nexus + confidence 自动衰减 + 触发重新抽象（见 14.4 节）

29. **~~程序性记忆文本化损失~~** → executable\_ref 保留 + procedural 专用抽象策略（提取 pattern 而非压缩内容）（见 12.3.1 节）

30. **~~Agent 接入层设计~~** → 三协议接入: MCP Server (Claude Code) + OpenAI Function Schema (Codex) + CLI Wrapper (通用)；统一 7 工具 API（v0.2 新增 ingest_observation 为一级入口，见 23.2.1.2）；会话三阶段生命周期；项目级 Vault 多 Agent 协作；Context Window = L1 映射（见 20.5-20.8 节）

31. **~~Agent 幻觉强化循环~~** → origin + verified 字段 + strength 固定上限 0.5（未验证 Agent 记忆）+ `memento verify` 命令（见 22.2 节）

32. **~~DAG 存储膨胀~~** → 高频标量（strength, last\_accessed）不进 Merkle DAG，物理分离到 SQLite 标量表（见 5.2 节存储分离约束）

33. **~~ClaimRecord 本体论爆炸~~** → 实体对齐层（Entity Resolution），LLM 提取前在已有实体库中 Fuzzy Match，防止同义词产生不同 claim\_key（见 3.13 节）

34. **~~Agent 幻觉强化循环（全版本）~~** → origin + verified 字段 + strength 固定上限 0.5 + 验证提升/降级规则（见 20.3 节 + 22.2 节）

35. **~~Hot Buffer 幽灵数据~~** → provisional 结果附带警告 + Agent 指令文件声明禁止作为决策核心依据 + 重要操作独立 capture（见 12.3 节）

36. **~~认知债务雪崩~~** → Micro-batching 流式微批处理为默认模式，CPU 闲置时逐条消化，Deep Sleep 降为手动兜底（见 12.7 节）

37. **~~Diplomat 审计疲劳~~** → 置信度三级门控（>0.98 静默 / 0.8-0.98 聚合摘要确认 / <0.8 逐条审查），涉及数值/ID/URL 自动降低 confidence（见 6.6.1 节）

38. **~~v0.1 recall() 并发竞态~~** → SQLite WAL 模式 + 原子 SQL UPDATE（strength 计算在 SQL 内完成，不在 Python 侧 read-modify-write）+ busy\_timeout 自动重试（见 22.2 节）

39. **~~v0.1 Embedding API 单点依赖~~** → 三级离线降级：Level 0 远程 API → Level 1 本地轻量模型 → Level 2 FTS5 全文检索回退 + embedding\_pending 补填机制（见 22.2 节）

40. **~~ClaimRecord 未集成到主模型~~** → Engram 新增 claims 字段引用 ClaimRecord；MemoryCommit.stats 新增 claims\_extracted/claim\_conflicts；6.5 节 Merge 冲突判定改为基于 ClaimRecord 结构化比对（见 3.1/3.3/6.5 节）

41. **~~Engram.links 与 Nexus 双重真相源~~** → 删除 Engram.links 内嵌字段，Nexus (3.8) 为唯一权威关联数据源（见 3.1 节）

42. **~~潜意识轨道资源边界矛盾~~** → 模态转换（Whisper/多模态模型）从潜意识轨道移至睡眠轨道 Phase 0；潜意识轨道恢复"纯数学、无推理模型"约束（见 12.3.1/12.5 节）

43. **~~联邦投影噪声不确定性~~** → noise\_seed = HMAC(sender\_noise\_key, commit+recipient+mask\_version)，保证确定性（可重试/可缓存/可审计复现）+ 不可预测 + 不可跨接收方关联（见 5.2 节）

44. **~~MVP 验证无基线实验~~** → A/B 对照实验设计：Mode A (衰减+强化) vs Mode B (纯向量+时间)，预置标注集 + Precision\@3/MRR/过时记忆抑制率量化指标 + 明确优于阈值（见 22.4 节）

45. **~~critical 永不衰减与设计哲学矛盾~~** → critical 改为极慢衰减（半衰期 ×10）+ recall 返回时附带非持久化的 review\_hint（不写数据库），不再零衰减（见 22.2 节）

46. **~~Engram.content 字段类型歧义~~** → content 类型从 "Text / Embedding / Structured" 修正为 "Text"，与"content 始终为文本描述"的设计一致（见 3.1 节）

47. **~~"读即写"心智模型违反~~** → 区分两层副作用：Layer A 元数据更新（用户无感，类似搜索 click-through）vs Layer B 内容修改（仅 rigidity<0.5 的记忆，仅 Epoch 期间）。recall() 返回的内容在当次调用中保证稳定（见 4.4 节）

48. **~~目标用户不清晰~~** → 第一章新增"系统定位与边界"：首要用户 = AI Agent 开发者，明确非目标（不是通用知识库/社交网络/共识系统/激励系统），核心赌注风险声明（见 1 章）

49. **~~Git 名不副实~~** → 全文"Git commit"改为"DAG commit"，明确实现为自研 Merkle DAG 而非 Git 二进制工具（见 5.2 节）

50. **~~v0.1→v0.2 断层未声明~~** → v0.1→v0.2 为增量演进（复用 engrams 表和衰减模型代码），v0.2→v0.5 才是架构重写（三轨/CQRS），届时仅数据迁移（见 23.2、23.2.1 节）

51. **~~drift\_from\_origin 无可操作建议~~** → 按 drift 阈值附带操作建议：sync（拉取上游）/ detach（切断上游）/ diff --origin（查看差异），用户主动执行而非系统自动断裂（见 3.5 节）

52. **~~Agent strength 硬上限 0.4 过于简单~~** → 改为固定上限 0.5。曾考虑动态公式 lerp(0.4, 0.7, 1-verified\_ratio)，但存在"倒挂悖论"（用户越勤奋验证 → cap 越低 → 惩罚勤奋用户），改回固定常量。未验证记忆之间通过 access\_count 和衰减自然产生区分度（见 20.3 节 + 22.2 节）

### 仍待探索（非阻塞性）

1.  **梦境模拟**：Epoch 期间是否可以引入"随机联想"机制？让系统在整合时随机组合不相关的记忆，模拟梦境中的创造性联想，可能产生意想不到的 Nexus 连接
2.  **认知风格迁移**：Fork 别人的 Vault 时，除了内容，是否可以 Fork 对方的"思维方式"——比如对方的 rigidity 分布、衰减曲线偏好、抽象化倾向？
3.  **~~记忆考古学~~** → 已部分解决：Archive Tombstone Index 提供了基础的考古能力（见 14.4 节）。更深度的考古工具（如通过断开的 Nexus 痕迹重建记忆轮廓）仍待探索



### 参考项目

https://github.com/CaviraOSS/OpenMemory
