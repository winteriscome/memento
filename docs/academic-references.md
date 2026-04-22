# Engram/Memento 学术研究参考图谱

本文档梳理了与 Memento 系统设计高度关联的前沿学术研究，按与核心设计的映射关系组织为六个维度。

---

## 一、记忆衰减与强化 — 核心机制

Memento 的 `effective_strength = strength × 0.5^(hours / half_life)` 和间隔强化机制直接对应以下研究：

### 1. FSRS (Free Spaced Repetition Scheduler)

- **作者**: Jarrett Ye et al.
- **发表**: KDD 2022
- **核心贡献**: 提出 DSR (Difficulty-Stability-Retrievability) 模型，将间隔重复建模为随机最短路径问题（马尔可夫决策过程）
- **与 Memento 的映射**: `reinforcement_boost` 间隔效应与 FSRS 的 stability 增长函数本质相同。FSRS v6 已集成到 Anki，有大规模用户验证数据，比 SM-2 减少 20-30% 复习次数
- **可行动方向**: 当前的半衰期衰减公式可以用 FSRS 的参数化模型替代，获得更精确的个体化衰减率

### 2. MemoryBank

- **作者**: Zhong et al.
- **发表**: AAAI 2024
- **核心贡献**: 第一个将 Ebbinghaus 遗忘曲线显式应用于 LLM 记忆的工作。记忆按时间衰减 + 按相对重要性强化
- **与 Memento 的映射**: 与 Memento 的设计几乎同构，`importance_factor` 对应其 relative significance 权重

### 3. ARM: Adaptive RAG Memory

- **发表**: arXiv 2025
- **核心贡献**: 用动态记忆基底替代 RAG 的静态向量索引，高频检索项被巩固保护、低频项衰减
- **与 Memento 的映射**: 明确引用 Ebbinghaus 遗忘曲线和 Atkinson-Shiffrin 双存储理论，与 `recall` 读即写再巩固设计高度一致

### 4. Human-like Forgetting Curves in Deep Neural Networks

- **发表**: arXiv 2025
- **核心贡献**: 证明 MLP 展现出类人遗忘曲线，知识通过定期复习变得越来越稳固
- **与 Memento 的映射**: 为"衰减 + 强化优于纯向量搜索"的核心假设提供了神经网络层面的理论支撑

### 5. CVPR 2025 "Respacing"

- **发表**: CVPR 2025
- **核心贡献**: 将 Ebbinghaus 理论应用于持续学习，发现适度遗忘反而保护长期记忆
- **与 Memento 的映射**: 与"遗忘是特性不是缺陷"的设计哲学完全吻合

---

## 二、Agent 记忆架构 — 首要用户场景

### 6. Generative Agents

- **作者**: Park et al.
- **发表**: UIST 2023
- **核心贡献**: 记忆流架构——按 recency × importance × relevance 三因子检索
- **与 Memento 的映射**: `effective_strength × similarity` 排序是这个思路的衰减增强版

### 7. MemGPT → Letta

- **作者**: Packer et al.
- **发表**: NeurIPS 2023
- **核心贡献**: 虚拟上下文管理，灵感来自 OS 内存层级（RAM vs disk）。Letta V1 引入"context compilation"——Agent 自主编辑记忆块
- **与 Memento 的映射**: STM/LTM 双层 + Epoch 整合与 MemGPT 的 paging 机制异曲同工，context compilation 类似再巩固

### 8. A-Mem

- **作者**: Xu et al.
- **发表**: NeurIPS 2025
- **核心贡献**: Agent 自主组织记忆，用 Zettelkasten 方法动态索引和链接，比 MemGPT 提升 192%
- **与 Memento 的映射**: Nexus 关联网络与其互联知识节点思路一致

### 9. Mem0

- **作者**: Chhikara et al.
- **发表**: ECAI 2025
- **核心贡献**: 生产级 Agent 记忆架构——动态提取、整合、检索 + 图记忆变体。比 OpenAI 记忆系统提升 26%，延迟降低 91%
- **与 Memento 的映射**: 系统定位与 Mem0 最接近，但 Memento 加入了衰减机制这个关键差异化

### 10. EM-LLM

- **作者**: Fountas et al.
- **发表**: ICLR 2025
- **核心贡献**: 将人类情景记忆和事件认知集成到 LLM，用贝叶斯惊奇度分割记忆事件，成功跨 1000 万 token 检索
- **与 Memento 的映射**: 与 episodic → semantic 抽象化路径相关

### 11. Focus: Active Context Compression

- **作者**: Verma
- **发表**: arXiv 2026
- **核心贡献**: Agent 自主决定何时将学习成果压缩到持久"知识块"并裁剪原始交互历史，token 减少 22.7% 而准确率不变
- **与 Memento 的映射**: 与 Epoch 抽象化目标一致

---

## 三、认知架构 — 理论基础

### 12. CoALA: Cognitive Architectures for Language Agents

- **作者**: Sumers et al.
- **发表**: TMLR 2024
- **核心贡献**: 最重要的理论框架——从 ACT-R/Soar 认知科学出发，提出模块化 Agent 架构，定义了 working memory、episodic memory、semantic memory、procedural memory 四模块。LLM 替代了经典架构中的手写产生式规则
- **与 Memento 的映射**: Engram 类型系统（episodic/semantic/procedural）直接对应 CoALA 分类

### 13. Soar + LLM 系列

- **作者**: Wray, Kirk, Laird (Michigan)
- **发表**: AGI 2025 / Cognitive Systems Research 2025
- **核心贡献**: 将 Soar 认知设计模式迁移到通用 LLM Agent，提出"LLM-Modulo"系统——LLM 补充而非替代认知架构机制

### 14. Brain-Inspired Agentic Architecture

- **发表**: Nature Communications 2025
- **核心贡献**: 明确从认知架构传统出发，用预训练语言模型替代符号程序组件

---

## 四、记忆再巩固的计算模型 — Layer A/B 机制

### 15. Complementary Learning Systems (CLS)

- **作者**: Sun et al.
- **发表**: Nature Neuroscience 2023
- **核心贡献**: 海马体作为 Hebbian 学习的笔记本（快速编码），皮层作为学生网络（慢速整合）。整合过程优化的是未来泛化能力，而非简单记忆保留
- **与 Memento 的映射**: STM(海马) → Epoch 整合 → LTM(皮层) 流程是这个理论的工程实现

### 16. Engram Neural Network (ENN)

- **作者**: Szelogowski
- **发表**: arXiv 2025
- **核心贡献**: 直接以 Engram 命名，用可微分记忆矩阵 + Hebbian 可塑性 + 稀疏注意力检索，将神经科学的 engram 形成和重激活操作化为可训练的深度学习系统
- **与 Memento 的映射**: Nexus 赫布学习（共同激活的记忆相互增强）与 ENN 的 Hebbian trace 直接对应

### 17. Memory Consolidation from RL Perspective

- **作者**: Lee & Jung
- **发表**: Frontiers 2025
- **核心贡献**: 将海马体重放建模为 Dyna-style 离线学习，基于价值的选择决定哪些记忆被重放整合
- **与 Memento 的映射**: Epoch 批处理整合本质上就是一个离线重放过程

### 18. Synaptic Scaling as Destabilization

- **作者**: Amorim et al.
- **发表**: Learning & Memory 2021
- **核心贡献**: 计算模型证明再巩固过程中突触缩放是去稳定化机制——短暂再暴露 → 记忆更新（Layer B）；长期暴露 → 消退
- **与 Memento 的映射**: `rigidity` 参数控制再巩固深度，与该模型的蛋白质合成阻断实验类比

---

## 五、联邦知识共享 — v0.5/v1.0 路线

### 19. FedR

- **作者**: Zhang et al.
- **发表**: arXiv 2022-2023
- **核心贡献**: 仅聚合关系嵌入（非实体），用 Private Set Union + Secure Aggregation。隐私泄露指标降为零，通信成本降低两个数量级
- **与 Memento 的映射**: Export Projection + 拓扑噪声思路比 FedR 更激进但方向一致

### 20. DP-Flames

- **作者**: Hu et al.
- **发表**: 2023
- **核心贡献**: 梯度级差分隐私 + 自适应隐私预算，攻击成功率从 83.1% 降至 59.4%
- **与 Memento 的映射**: 可参考的防御基准

### 21. FPKS

- **发表**: ACM Transactions 2025
- **核心贡献**: 专为 IoT 环境设计的隐私保护个人知识共享
- **与 Memento 的映射**: 与"个人 Vault 有限共享"场景高度匹配

---

## 六、协议与标准 — Agent 基础设施栈

### 22. MCP (Model Context Protocol)

- **发布者**: Anthropic
- **发表**: 2024
- **核心贡献**: Agent-to-Tool 的开放标准，已被 OpenAI/Google/Microsoft 采纳
- **与 Memento 的映射**: v0.5 计划支持 MCP Server，可以直接复用这个生态

### 23. A2A (Agent2Agent Protocol)

- **发布者**: Google
- **发表**: 2025
- **核心贡献**: Agent-to-Agent 通信协议，基于 JSON-RPC 2.0 + HTTP(S)。Agent 彼此不透明（不共享内部记忆/逻辑），支持长任务、流式传输
- **与 Memento 的映射**: EFP 联邦协议可以参考 A2A 的设计哲学，但 A2A 不处理记忆语义

### 24. MCP + A2A + Engram 互补格局

三者构成完整的 Agent 基础设施栈：

| 协议层 | 解决的问题 | 标准 |
|--------|-----------|------|
| **工具调用** | Agent 如何访问工具和数据 | MCP |
| **Agent 通信** | Agent 之间如何协作 | A2A |
| **记忆持久化** | Agent 如何管理和共享持久记忆 | **Engram (本项目)** |

---

## 关键洞察：Memento 的差异化定位

从研究全景来看，Memento 在三个交叉点上具有独特性：

1. **衰减作为一等公民** — Mem0、MemGPT、A-Mem 都没有衰减机制，MemoryBank 有但没有联邦共享
2. **记忆协议层** — MCP 解决工具调用，A2A 解决 Agent 通信，没有人在做记忆共享的标准协议
3. **认知科学严肃性** — 大多数 Agent 记忆系统是工程驱动的，Memento 的设计明确对标了 CLS 理论、Hebbian 学习、再巩固双层模型

---

*最后更新: 2026-03-27*
