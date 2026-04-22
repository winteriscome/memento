# Memento Web Dashboard 设计文档

## 概述

为 Memento 提供本地 Web Dashboard，作为**本地运维/观察面板**，方便用户以可视化方式浏览、搜索、管理记忆，替代 CLI 的 `recall --format json` 工作流。

参考项目：Mem0 OpenMemory Dashboard。

**定位**：Dashboard 不是新的核心 API 契约来源。实现应以 `src/memento/api.py` 和现有 canonical docs 为准。Dashboard 是 UI on top of existing API/domain，不是第二套核心逻辑。

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 部署形式 | 轻量内嵌（`memento dashboard` 命令启动） | 无额外依赖，pip install 即用 |
| 前端方案 | FastAPI + Vue 3（本地 vendor 优先，无构建步骤） | 响应式绑定 + 组件化，保持纯静态文件 |
| 数据访问 | 通过 `LocalAPI`（`src/memento/api.py`）访问数据 | 复用现有业务逻辑，不直接访问 SQLite 或自建业务逻辑层 |
| 图谱可视化 | MVP 不做 | 优先浏览和管理，图谱留后续迭代 |
| 多项目/多数据库切换 | MVP 不做 | 保持单数据库模型；UI 层保留按 project/path 过滤的兼容空间 |

## 架构

```
memento dashboard [--port PORT]
        │
        ▼
┌─────────────────────────────────┐
│  FastAPI Server (127.0.0.1)     │
│                                  │
│  /api/*        REST 端点         │
│  /static/*     Vue 3 前端        │
│                                  │
│  数据层: LocalAPI 实例           │
│  数据库: ~/.memento/default.db   │
└─────────────────────────────────┘
```

### 数据访问层约定

- MVP 阶段 dashboard server 使用 `LocalAPI`（进程内本地 API 实现）
- 所有读写操作只通过 `src/memento/api.py` 暴露的稳定接口完成
- dashboard route **不直接访问 SQLite，不自行拼 SQL**
- 后续如引入远程/worker 模式，再抽象 transport 层

### 目录结构

```
src/memento/dashboard/
├── __init__.py
├── server.py          # FastAPI 应用 + 启动逻辑
├── routes.py          # API 路由
└── static/
    ├── index.html     # SPA 入口
    ├── app.js         # Vue 应用主逻辑
    ├── style.css      # 样式
    └── vendor/
        └── vue.global.prod.js  # Vue 3 生产版（离线可用）
```

### CLI 入口

在 `cli.py` 新增 `dashboard` 子命令：

```python
@main.command()
@click.option("--port", default=8230, help="服务端口")
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
def dashboard(port, no_open):
    """启动 Web Dashboard"""
```

端口默认 8230，启动后自动打开浏览器。浏览器打开失败不影响服务启动。

## API 设计

### 通用约定

- 所有时间字段使用 ISO 8601 格式（如 `2026-04-02T10:01:02.917576+00:00`）
- strength/rigidity 为 0.0–1.0 浮点数
- 列表端点返回数组，详情端点返回对象
- 写操作（DELETE/POST）返回更新后的对象或操作结果

### 统一错误响应

```json
{
  "error": {
    "code": "ENGRAM_NOT_FOUND",
    "message": "Engram not found"
  }
}
```

HTTP 状态码：400（参数错误）、404（资源不存在）、500（内部错误）。

### 记忆相关

#### `GET /api/engrams` — 列表 + 搜索 + 过滤

参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `q` | string | `""` | 搜索词，优先复用现有 `recall` 检索能力；列表过滤/排序/分页由 dashboard API 在现有数据模型之上做适配层实现，不改变核心 recall 契约 |
| `type` | string | `""` | 类型过滤，支持多选逗号分隔（`fact,decision`） |
| `origin` | string | `""` | 来源过滤：`human` / `agent` |
| `importance` | string | `""` | 重要性过滤：`low` / `normal` / `high` / `critical` |
| `verified` | string | `""` | 验证状态：`true` / `false` |
| `provisional` | string | `""` | 临时状态：`true` / `false` |
| `sort` | string | `created_at` | 排序字段：`strength` / `created_at` / `access_count` |
| `order` | string | `desc` | 排序方向：`asc` / `desc` |
| `limit` | int | `50` | 每页数量，上限 200 |
| `offset` | int | `0` | 偏移量 |

`GET /api/engrams` 为 dashboard 专用列表查询接口。搜索语义可复用 recall 的检索能力，但接口层需要补充专用 list/filter/pagination 适配，不直接等同于现有 `LocalAPI.recall()` 返回。空查询（`q` 为空）默认按 `created_at desc` 返回。

以下 schema 为 dashboard API 对现有数据模型的整形结果；部分字段来自 `inspect()` / session 关联查询 / nexus 查询的组合，而非现有单一 API 直接原样返回。

响应 schema — `EngramSummary[]`：

```json
[
  {
    "id": "faf79a83-a1e7-4e53-a72e-ba8d2beefb7a",
    "content": "在 memento 项目中，只要代码推送到 main 分支...",
    "type": "preference",
    "origin": "human",
    "importance": "critical",
    "strength": 0.70,
    "rigidity": 0.0,
    "verified": false,
    "provisional": false,
    "tags": ["git", "workflow", "tagging"],
    "access_count": 3,
    "created_at": "2026-04-02T09:30:00+00:00",
    "last_accessed": "2026-04-02T10:00:00+00:00"
  }
]
```

#### `GET /api/engrams/{id}` — 单条详情

优先基于 `LocalAPI.inspect()` 适配，不重复发明详情查询逻辑。

响应 schema — `EngramDetail`：

```json
{
  "id": "faf79a83-...",
  "content": "...",
  "type": "preference",
  "origin": "human",
  "importance": "critical",
  "strength": 0.70,
  "rigidity": 0.0,
  "verified": false,
  "provisional": false,
  "tags": ["git", "workflow"],
  "access_count": 3,
  "created_at": "2026-04-02T09:30:00+00:00",
  "last_accessed": "2026-04-02T10:00:00+00:00",
  "source_session_id": "sess-abc123",
  "source_event_id": null,
  "pending_forget": false,
  "nexus": [
    {
      "source_id": "faf79a83-...",
      "target_id": "b2c3d4e5-...",
      "type": "semantic",
      "association_strength": 0.45,
      "last_coactivated_at": "2026-04-01T08:00:00+00:00"
    }
  ]
}
```

#### `DELETE /api/engrams/{id}` — 标记遗忘

调用 `LocalAPI.forget()`。返回：

```json
{"ok": true, "id": "faf79a83-...", "action": "marked_for_forget"}
```

#### `POST /api/engrams/{id}/verify` — 验证 agent 记忆

调用 `LocalAPI.verify()`。返回更新后的 `EngramSummary`。

#### `POST /api/engrams/{id}/pin` — 设置 rigidity

请求体：`{"rigidity": 0.8}`（float 0.0–1.0）

调用 `LocalAPI.pin()`。返回更新后的 `EngramSummary`。

### 会话相关

#### `GET /api/sessions` — 会话列表

参数：`project`（按项目路径过滤）、`status`、`limit`（默认 20）

响应 schema — `SessionSummary[]`：

```json
[
  {
    "id": "sess-abc123",
    "project": "/Users/maizi/data/work/memento",
    "task": null,
    "status": "completed",
    "started_at": "2026-04-02T08:00:00+00:00",
    "ended_at": "2026-04-02T09:30:00+00:00",
    "summary": "完成了 dashboard 设计文档",
    "event_count": 5
  }
]
```

#### `GET /api/sessions/{id}` — 会话详情 + events

响应在 `SessionSummary` 基础上增加 `events` 数组。events 明细需在 `SessionService` / `LocalAPI` 中新增只读查询方法支持。

**注意**：dashboard 的 session 视图以当前 session lifecycle 设计和现有实现为准。若某字段当前实现不可用，则降级展示（显示 `—`），不为 dashboard 反向修改 session 核心模型。

### 系统相关

| 端点 | 方法 | 功能 |
|------|------|------|
| `GET /api/status` | GET | 系统状态（调用 `LocalAPI.status()`） |
| `POST /api/epoch/run` | POST | 触发 epoch 整合（调用 `LocalAPI.epoch_run()`） |
| `GET /api/epoch/history` | GET | epoch 运行历史（调用 `LocalAPI.epoch_status()`） |
| `GET /api/epoch/debt` | GET | 认知债务列表（调用 `LocalAPI.epoch_debt()`） |
| `GET /api/captures/pending` | GET | L2 缓冲区待处理 captures（需先在 `LocalAPI` 中补充 `list_pending_captures()` 只读接口） |

## 前端设计

### 三个视图

#### 1. 记忆视图（主页，优先级最高）

- **统计栏**：活跃记忆数、待验证数、会话数、认知债务数
- **搜索栏**：实时搜索（防抖 300ms），调 `GET /api/engrams?q=`
- **过滤器**：类型、来源、重要性、验证状态、排序方式
- **记忆卡片列表**：
  - 左侧：记忆内容 + 标签（类型标签 + 自定义标签 + 来源标签）
  - 右侧：强度进度条（颜色区分高/中/低）、重要性、访问次数
  - 操作按钮：验证（仅 agent 未验证记忆显示）、删除（需二次确认）
  - 低强度记忆降低透明度，视觉上体现"淡忘"效果

#### 2. 会话视图

- 会话列表（时间倒序）
- 每条显示：项目名、状态标签、时间范围
- 点击展开：会话摘要、关联 observations 列表
- 按项目路径筛选

#### 3. 系统视图

- `memento status` 可视化：记忆状态分布、embedding 覆盖率
- Epoch 历史表格：ID、模式、状态、处理统计、完成时间
- 认知债务列表
- 「触发 Epoch」按钮（需二次确认）
- L2 缓冲区待处理 captures

### 统计指标口径

| 指标 | 定义 |
|------|------|
| 活跃记忆数 | `StatusResult.active` — 未遗忘、state 为 consolidated/provisional 的 engrams 数 |
| 待验证数 | `StatusResult.unverified_agent` — origin=agent 且 verified=false 的 engrams 数 |
| 会话数 | `StatusResult.total_sessions` |
| 认知债务数 | `StatusResult.cognitive_debt_count` — cognitive_debt 表中 resolved_at IS NULL 的记录数 |
| Embedding 覆盖率 | `StatusResult.with_embedding / StatusResult.total`（百分比显示） |
| 待处理 Captures | `StatusResult.pending_capture` — capture_log 中 epoch_id IS NULL 的记录数 |

## 静态资源与离线策略

- Vue 3 生产版文件（`vue.global.prod.js`）内嵌在 `static/vendor/` 目录，**提交到仓库**
- Vue Router 同样内嵌到 `static/vendor/`，使用 `createWebHashHistory()` 模式（no-build 场景更稳，不依赖服务端 SPA fallback）
- `index.html` 默认引用本地 vendor 文件，**不依赖 CDN**
- Dashboard 在完全无网络环境下可正常使用
- vendor 文件更新通过手动下载新版本替换

## 安全边界

- 默认只监听 `127.0.0.1`，不暴露到 `0.0.0.0`
- 破坏性操作（forget / epoch run / pin / verify）通过 POST/DELETE 方法区分，前端需二次确认
- POST body 做基本校验（rigidity 范围 0–1，id 格式等）
- 所有异常返回统一 JSON 错误结构（见上文）
- 浏览器打开失败不影响服务启动

## 依赖变更

- 新增 `fastapi` 和 `uvicorn[standard]` 作为可选依赖（`pip install memento[dashboard]`）
- 不影响核心包的依赖体积

## 打包注意事项

当前 `pyproject.toml` 的 `package-data` 只包含 `scripts/*.sh`。实现时必须更新打包配置，确保 `dashboard/static/**` 和 `vendor/**` 被安装包带上：

```toml
[tool.setuptools.package-data]
memento = ["scripts/*.sh", "dashboard/static/**"]
```

否则本地源码运行能用，安装包运行会丢静态文件。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/memento/dashboard/__init__.py` | 新增 | 包初始化 |
| `src/memento/dashboard/server.py` | 新增 | FastAPI 应用 + uvicorn 启动 |
| `src/memento/dashboard/routes.py` | 新增 | API 路由定义 |
| `src/memento/dashboard/static/index.html` | 新增 | SPA 入口 |
| `src/memento/dashboard/static/app.js` | 新增 | Vue 应用主逻辑 |
| `src/memento/dashboard/static/style.css` | 新增 | 样式 |
| `src/memento/dashboard/static/vendor/vue.global.prod.js` | 新增 | Vue 3 本地 vendor |
| `src/memento/cli.py` | 修改 | 新增 `dashboard` 子命令 |
| `pyproject.toml` | 修改 | 新增 `[dashboard]` optional dependency |
| `tests/test_dashboard.py` | 新增 | API 路由测试 |

## 落地顺序

1. CLI 子命令 + FastAPI server 启动骨架（`memento dashboard` 可启动、可打开空页面）
2. `GET /api/status` + `GET /api/engrams` 只读 API
3. 前端记忆视图（统计栏 + 搜索 + 过滤 + 卡片列表）
4. verify / delete / pin 写操作 API + 前端交互
5. sessions / system 视图 + 对应 API
6. 测试和文档收尾

## 验收标准

- [ ] `memento dashboard` 能启动并自动打开页面
- [ ] 无网络环境可正常访问 Dashboard 基础 UI
- [ ] 能查看记忆列表、实时搜索、按类型/来源/验证状态过滤
- [ ] verify / delete / pin 操作可用，有二次确认
- [ ] 会话视图可加载、按项目过滤
- [ ] 系统视图可加载、触发 Epoch 可用
- [ ] dashboard optional dependency 不影响核心 `pip install memento`
- [ ] API 路由测试覆盖核心读写操作

## 不在 MVP 范围内

- Nexus 图谱可视化（后续迭代）
- 记忆内容编辑（只读 + 删除/验证/pin）
- 实时推送（WebSocket），用手动刷新代替
- 暗色主题
- 移动端适配
- 多数据库切换
