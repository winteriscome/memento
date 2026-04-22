# 记忆合并与冲突解决的数学框架

本文档整理了记忆系统在合并和冲突解决场景下的数学化方法，从基础定义到统一框架逐层展开。

> **⚠️ 设计审查说明**（2026-03-27）
>
> 本文档中的数学工具经过严格的设计审查，部分工具被标记为 **不适用于 Engram 架构**。
> 每种工具的适用性判定见各节末尾的"设计审查"标注。核心结论：
>
> - Engram 的合并机制应基于 **OperationLog 重放**（操作级），而非 CRDT/AGM 等状态级方案
> - 最有工程价值的数学化方向是 **FSRS 幂律衰减**替换当前指数衰减
> - 详见末尾 [设计审查总结](#设计审查总结)

---

## 一、记忆的数学表示

在 Engram 系统中，一条记忆形式化为多维元组：

```
m = (e, s, r, d, o, t)
```

| 分量 | 含义 | 数学空间 |
|------|------|---------|
| `e ∈ ℝᴰ` | embedding 向量 | D 维欧几里得空间 |
| `s ∈ [0,1]` | strength | 单位区间 |
| `r ∈ [0,1]` | rigidity | 单位区间 |
| `d ∈ ℝ⁺` | decay_rate | 正实数 |
| `o ∈ {human, agent}` | origin | 离散集 |
| `t ∈ ℝ⁺` | timestamp | 时间轴 |

关联关系通过 Nexus 表示：

```
n = (mᵢ, mⱼ, w, type)    w ∈ [0,1]  (association_strength)
```

整个 Vault 是一个加权有向图 `G = (M, N)`，节点是记忆，边是关联。

---

## 二、合并操作

合并的本质问题：Alice 的 Vault `Gₐ` 和 Bob 的 Vault `G_b` 如何生成合并后的 `G_merged`？

### 2.1 CRDT 半格合并（无冲突，保证收敛）

核心数学结构是**连接半格** (join-semilattice)：

```
定义偏序: m₁ ⊑ m₂ 当且仅当 m₂ 是 m₁ 的"更完整"版本
合并操作: m₁ ⊔ m₂ = 最小上界 (least upper bound)
```

三条公理保证最终一致：

```
交换律: m₁ ⊔ m₂ = m₂ ⊔ m₁
结合律: (m₁ ⊔ m₂) ⊔ m₃ = m₁ ⊔ (m₂ ⊔ m₃)
幂等律: m ⊔ m = m
```

对 Engram 各分量的具体合并规则：

```
标量分量（取 max，天然满足半格公理）：
  strength:      s_merged = max(s_a, s_b)         ← G-Counter 式
  access_count:  n_merged = max(n_a, n_b)
  last_accessed: t_merged = max(t_a, t_b)

集合分量（取并集，天然满足半格公理）：
  tags_merged = tags_a ∪ tags_b                    ← G-Set 式

元组合并（逐分量应用）：
  m_merged = (e_merged, max(s_a, s_b), ..., tags_a ∪ tags_b)
```

**优点**：数学上保证无冲突、最终一致，适合元数据合并。

**局限**：不能处理内容语义冲突（两条记忆说的事实相反）。

> **⚠️ 设计审查：CRDT 在 Engram 中的适用范围严格受限**
>
> `max()` 操作与衰减语义存在根本性矛盾：
> - Alice 的记忆 strength 从 0.8 衰减到 0.3（有意义的信号），Bob 的同源记忆仍在 0.8 → `max(0.3, 0.8) = 0.8` → 抹杀了 Alice 侧的衰减信号
> - 更严重：Alice 调用 `forget()` 将 strength 设为 0（FORGOTTEN 是吸收态，见设计文档 14.1），Bob 的 fork 仍在 0.6 → `max(0, 0.6) = 0.6` → **主动遗忘的记忆复活**，直接违反不变量
>
> **结论**：CRDT 仅可用于**单调增长**的元数据（`access_count`、`tags`），不可用于 `strength`、`forgotten` 等可降/可删字段。这些字段的合并必须走 **OperationLog 重放**路径。

### 2.2 向量空间插值（语义层合并）

对 embedding 向量，有三种数学合并方式：

**加权平均（线性插值）**：

```
e_merged = λ · eₐ + (1-λ) · e_b
λ = sₐ / (sₐ + s_b)
```

适合"两个观点都有道理"的视角性差异。

**球面线性插值 (SLERP)**——保持向量长度：

```
SLERP(eₐ, e_b; t) = sin((1-t)Ω)/sin(Ω) · eₐ + sin(tΩ)/sin(Ω) · e_b
其中 Ω = arccos(eₐ · e_b / (‖eₐ‖ · ‖e_b‖))
```

适合两条记忆是"同一主题的不同表述"。

**Wasserstein 重心**——如果记忆被建模为分布：

```
e* = arg min_e Σᵢ λᵢ · W₂²(e, eᵢ)
```

适合多方记忆的最优折中，尊重嵌入空间的几何结构。

> **⚠️ 设计审查：向量空间合并在 Engram 中无应用场景**
>
> v0.1 ~ v0.5 不存在"合并两条记忆的 embedding 为一个新 embedding"的场景。设计文档 6.5 节明确："保留双方视角，创建 perspective 类型 Nexus"——两条矛盾记忆共存，不是合并为一条。
>
> - 重复记忆 → 去重（保留一条）
> - 视角差异 → 保留双方 + Nexus
> - 事实冲突 → ClaimRecord 仲裁
>
> 没有场景需要"生成一个混合 embedding"。此节作为数学参考保留，但**不纳入实现路线图**。

---

## 三、冲突检测

冲突检测是合并的前提——需要先知道两条记忆是否矛盾。

### 3.1 向量空间距离（快速筛选）

```
cosine_conflict(mₐ, m_b) = 1 - cos(eₐ, e_b)
                          = 1 - (eₐ · e_b) / (‖eₐ‖ · ‖e_b‖)
```

| 值域 | 含义 | 操作 |
|------|------|------|
| [0, 0.3] | 语义相似 | 可能是重复，考虑去重 |
| [0.3, 0.7] | 语义相关但不同 | 视角性差异，保留双方 |
| [0.7, 1.0] | 语义对立 | 可能是事实冲突，需深度检测 |

> **⚠️ 设计审查：cosine distance 阈值不可靠**
>
> 在实际 embedding 空间中（Gemini text-embedding-004 / OpenAI text-embedding-3），语义完全相反的句子 cosine distance 很少超过 0.5。例如"水在 100°C 沸腾"和"水在 0°C 沸腾"的 cosine similarity 通常在 0.85~0.95——仅一个数值不同。
>
> 这意味着 `cosine_conflict > 0.7 → 事实冲突` 几乎永远不会触发。真正的事实冲突（关键值不同但大部分文字相同）在向量空间中距离极小。设计文档 3.13 引入 **ClaimRecord SPO 三元组比对**正是为了解决这个问题。cosine distance **不应作为冲突检测的依据**。

### 3.2 Dempster-Shafer 证据冲突度（精确判定）

将每条记忆视为一个证据源：

```
记忆 mₐ 对命题 A 的支持度:
  m_a(A) = sₐ · confidence_a        (支持 A)
  m_a(Θ) = 1 - m_a(A)              (不确定部分)

记忆 m_b 对命题 ¬A 的支持度（矛盾记忆）:
  m_b(¬A) = s_b · confidence_b      (支持 ¬A)
  m_b(Θ) = 1 - m_b(¬A)
```

冲突因子：

```
K = Σ_{B∩C=∅} m_a(B) · m_b(C)
  = m_a(A) · m_b(¬A)
  = sₐ · confidence_a · s_b · confidence_b
```

> **⚠️ 设计审查：D-S 的 mass function 不能用 strength**
>
> `strength` 是"记忆活跃度"（被频繁访问），不是"对命题的支持度"。正确的 D-S 输入应为 ClaimRecord 的 `confidence` 字段（内容可信度，设计文档 3.13）。
>
> 误用 strength 的后果：两条 strength=0.1 的矛盾记忆 → K=0.01（几乎无冲突）→ 自动合并 → 实际上是两条弱但矛盾的事实被静默合并。
>
> **修正**：`K = confidence_a · confidence_b`，与 strength 无关。

| K 值 | 含义 | 处理方式 |
|------|------|---------|
| K < 0.1 | 几乎无冲突 | 自动合并 |
| 0.1 ≤ K < 0.5 | 中等冲突 | Diplomat 聚合确认 |
| K ≥ 0.5 | 严重冲突 | 必须人工审查 |

### 3.3 ClaimRecord 的逻辑冲突

基于描述逻辑的不一致性检测：

```
如果 TBox 包含: 认证方式(系统X) 是函数属性（只能有一个值）
ABox_a: (系统X, 认证方式, JWT)
ABox_b: (系统X, 认证方式, OAuth)
→ ABox_a ∪ ABox_b ⊢ ⊥ （不一致）
```

这是 `claim_key` 归组 + 时间区间重叠 + object 矛盾三重条件的逻辑基础。

---

## 四、冲突解决策略

### 4.1 AGM 信念修正（逻辑层）

核心操作——修正 `K * A`（在知识库 K 中加入新信念 A，保持一致性）：

```
K * A = (K ÷ ¬A) + A     ← Levi 恒等式
```

先收缩掉与 A 矛盾的旧信念 `(K ÷ ¬A)`，再扩展加入 A。

收缩时保留什么？由**认知固着度** (epistemic entrenchment) 排序决定：

```
entrenchment(m) = rigidity · strength · (verified ? 1.5 : 1.0)
```

冲突解决：保留 `entrenchment` 更高的那条，放弃更低的。

> **⚠️ 设计审查：entrenchment 公式需修正**
>
> `rigidity` 的语义是"可塑性"（是否允许再巩固修改），不是"冲突中的保留优先级"。
> - rigidity ≥ 0.5 的记忆（如"用户对花生过敏"）应**直接标记为不可通过合并覆盖**（对应设计文档 17.3 RIGIDITY_CONTENT_LOCK_THRESHOLD = 0.5），不参与 entrenchment 比较
> - entrenchment 计算仅对 rigidity < 0.5 的记忆有意义
>
> **修正后**：
> ```
> if rigidity ≥ 0.5 → 不可覆盖（跳过 entrenchment 比较）
> else → entrenchment(m) = importance · strength · (verified ? 1.5 : 1.0)
> ```

### 4.2 Fisher 加权合并（参数层）

对冲突记忆的各个分量，用 Fisher 信息加权：

```
m_merged = (Σᵢ Fᵢ)⁻¹ · (Σᵢ Fᵢ · mᵢ)
```

Fisher 信息的类比：

```
Fᵢ = reinforcement_count · importance_weight · (verified ? 2 : 1)
```

与 TIES-Merging 一致：

1. **Trim**: 忽略 strength 低于阈值的记忆
2. **Elect**: 对冲突属性，按 F 加权投票决定方向
3. **Merge**: 只合并方向一致的部分

### 4.3 贝叶斯信念融合（概率层）

将每条记忆视为一个概率分布，用**对数意见池**融合：

```
p_merged(θ) ∝ Πᵢ pᵢ(θ)^{wᵢ}
其中 wᵢ = strength_i / Σ strength
```

关键性质：对数池是**外部贝叶斯的**——如果每个源独立地做贝叶斯更新，融合结果等于把所有证据汇总后的贝叶斯更新。适合独立来源的知识合并。

**线性池** `p_merged = Σᵢ wᵢ · pᵢ` 适合依赖来源——相当于"有 wᵢ 概率相信来源 i"。

### 4.4 DeGroot 共识模型（联邦多方迭代收敛）

适合 v1.0 联邦场景，多个 Vault 之间的迭代同步：

```
y(t+1) = W · y(t)
```

`W` 是信任矩阵（行随机），`y` 是各 Vault 对某个事实的信念。

加入固执度 (`stubbornness = rigidity`) 后变成 **Friedkin-Johnsen** 模型：

```
y(t+1) = Λ · W · y(t) + (I - Λ) · y(0)
Λ = diag(1 - rigidity₁, ..., 1 - rigidityₙ)
```

高 rigidity 的 Vault 不容易被别人改变。

稳态解：

```
y* = (I - Λ·W)⁻¹ · (I - Λ) · y(0)
```

---

## 五、统一合并流程

```
OperationLog 中的每条 Operation
        │
        ▼
┌─────────────────────────────────────────────┐
│  Phase 1: 冲突检测                            │
│                                              │
│  1.1 向量距离快筛:                             │
│      conflict = 1 - cos(e_op, e_local)        │
│      if conflict < 0.3 → 跳过(重复)            │
│                                              │
│  1.2 ClaimRecord 逻辑检测:                     │
│      if claim_key 匹配 ∧ 时间重叠 ∧ object 矛盾  │
│      → 标记为事实冲突                           │
│                                              │
│  1.3 Dempster-Shafer 冲突度:                   │
│      K = s_local · s_incoming · cos_conflict   │
│      → 量化冲突严重程度                         │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
   K < 0.1          K ≥ 0.1
   无冲突            有冲突
       │               │
       ▼               ▼
┌──────────┐   ┌──────────────────────────┐
│ Phase 2a │   │ Phase 2b: 冲突解决         │
│ CRDT合并  │   │                          │
│          │   │ 计算 entrenchment:         │
│ s = max  │   │   E = rigidity × strength │
│ n = max  │   │       × (verified?1.5:1)  │
│ t = max  │   │                          │
│ tags = ∪ │   │ if E_local >> E_incoming  │
│          │   │   → 保留本地 (AGM 收缩)    │
│          │   │                          │
│          │   │ if E_local ≈ E_incoming   │
│          │   │   → 保留双方 + Nexus       │
│          │   │     (perspective 类型)     │
│          │   │                          │
│          │   │ if E_local << E_incoming  │
│          │   │   → 修正本地 (AGM K*A)     │
│          │   │                          │
│          │   │ if K > 0.5               │
│          │   │   → 升级人工审查           │
└──────────┘   └──────────────────────────┘
```

### 统一合并操作符

```
merge(mₐ, m_b) =
  let K = conflict(mₐ, m_b)                           -- Dempster-Shafer
  let Eₐ = entrenchment(mₐ), E_b = entrenchment(m_b)  -- AGM
  in
    | K < ε           → crdt_join(mₐ, m_b)      -- 无冲突: 半格合并
    | |Eₐ - E_b| > δ  → revise(weaker, stronger) -- 强弱分明: 信念修正
    | otherwise       → perspective(mₐ, m_b)     -- 旗鼓相当: 保留双方
```

### 框架优势

- **每一步都有数学保证** — CRDT 保证收敛，AGM 保证理性，Dempster-Shafer 量化冲突
- **与现有设计兼容** — `strength`、`rigidity`、`verified`、`ClaimRecord` 直接映射到数学分量
- **可渐进实现**：
  - v0.1：CRDT 元数据合并
  - v0.5：冲突检测 + AGM 修正
  - v1.0：DeGroot 联邦共识

---

*最后更新: 2026-03-27*
