"""MCP Server — stdio 协议，暴露 Memento 能力给 Claude Code。

直接 import api.py，同进程调用，不走 Worker。
"""

import json
from pathlib import Path

from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, Prompt, PromptMessage

from memento.api import MementoAPI


# ── Deprecated tools migration messages ──
_DEPRECATED_TOOLS = {
    "memento_set_session": "Removed in v0.5. Use memento_session_start/end instead.",
    "memento_get_session": "Removed in v0.5. Use memento_session_start/end instead.",
    "memento_evaluate": "Removed in v0.5. A/B framework retired.",
    "memento_backfill_embeddings": "Removed in v0.5. Handled by Epoch.",
}


# ── Priming prompt layer formatting ──
_LAYER_LABELS = {
    "L0": "[L0-Identity]",
    "L1": "[L1-Core]",
    "L2": "[L2-Context]",
}


def format_priming_prompt(memories: list[dict]) -> str:
    """Format priming memories into a layer-grouped prompt string."""
    if not memories:
        return ""

    lines = []
    for m in memories:
        layer = m.get("layer", "L2")
        label = _LAYER_LABELS.get(layer, "[L2-Context]")
        content = m.get("content", "")
        lines.append(f"{label} {content}")

    return "\n".join(lines)


def create_mcp_app(db_path: Path | None = None) -> tuple[Server, MementoAPI]:
    """创建 MCP Server 实例和 API 实例。"""
    app = Server("memento")
    api = MementoAPI(db_path=db_path)  # use_awake=True by default (v0.5)

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="memento_session_start",
                description="创建新的记忆会话，返回 session_id 和 priming 记忆。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "项目路径或标识"},
                        "task": {"type": "string", "description": "任务描述"},
                    },
                },
            ),
            Tool(
                name="memento_session_end",
                description="结束记忆会话。summary 默认存入会话记录；在显式摄取不足时，可能作为低信任 fallback capture 进入暂存层（origin='agent'，strength 上限 0.5）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "outcome": {
                            "type": "string",
                            "enum": ["completed", "abandoned", "error"],
                        },
                        "summary": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
            ),
            Tool(
                name="memento_recall",
                description="从长期记忆中检索相关知识。只读操作。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="memento_capture",
                description=(
                    "将重要发现、决策、用户偏好存入长期记忆。\n\n"
                    "适合记录的内容：\n"
                    "- 用户偏好和工作习惯（\"记住/总是/不要再\"）\n"
                    "- 架构决策及其原因\n"
                    "- 复杂 bug 的根因和解法\n"
                    "- 项目约定和模式\n\n"
                    "不要记录的内容：\n"
                    "- 代码结构、文件路径（可从 codebase 推导）\n"
                    "- Git 历史（用 git log 即可）\n"
                    "- CLAUDE.md 已有的内容\n"
                    "- 临时调试步骤（修复已在代码中体现）\n"
                    "- 当前会话的临时状态\n\n"
                    "判断原则：删掉这条记忆，下次会犯同样错误吗？是→记录。否→不记录。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": [
                                "decision",
                                "insight",
                                "convention",
                                "debugging",
                                "preference",
                                "fact",
                            ],
                        },
                        "importance": {
                            "type": "string",
                            "enum": ["low", "normal", "high", "critical"],
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "origin": {
                            "type": "string",
                            "enum": ["human", "agent"],
                        },
                        "session_id": {"type": "string"},
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="memento_observe",
                description="写入 observation（经去重/晋升 pipeline 处理）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "tool": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "session_id": {"type": "string"},
                        "importance": {
                            "type": "string",
                            "enum": ["low", "normal", "high", "critical"],
                        },
                    },
                    "required": ["content"],
                },
            ),
            Tool(
                name="memento_status",
                description="返回记忆数据库统计信息（含 v0.5 状态）。",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="memento_forget",
                description="软删除一条记忆（awake 模式下进入 pending 队列）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engram_id": {"type": "string"},
                    },
                    "required": ["engram_id"],
                },
            ),
            # ── v0.5 新增 Tools ──
            Tool(
                name="memento_epoch_run",
                description="触发一次 Epoch 运行（记忆整理周期）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["full", "light"],
                            "default": "full",
                            "description": "full 含 LLM 语义整理，light 仅数值操作",
                        },
                        "trigger": {
                            "type": "string",
                            "enum": ["manual", "scheduled", "auto"],
                            "default": "manual",
                        },
                    },
                },
            ),
            Tool(
                name="memento_epoch_status",
                description="查看最近 Epoch 运行记录。",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="memento_epoch_debt",
                description="查看未解决的 cognitive debt 统计。",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="memento_inspect",
                description="检查单条 engram 的详细信息，含 nexus 连接和 pending 状态。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engram_id": {"type": "string"},
                    },
                    "required": ["engram_id"],
                },
            ),
            Tool(
                name="memento_nexus",
                description="查看 engram 的关联图谱（nexus 连接）。默认只返回活跃连接。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engram_id": {"type": "string"},
                        "depth": {
                            "type": "integer",
                            "enum": [1, 2],
                            "default": 1,
                            "description": "遍历深度：1=直接连接，2=二级连接",
                        },
                        "include_invalidated": {
                            "type": "boolean",
                            "default": False,
                            "description": "是否包含已失效的连接",
                        },
                        "since": {
                            "type": "string",
                            "description": "ISO 时间戳，仅返回此时间后创建的连接",
                        },
                        "until": {
                            "type": "string",
                            "description": "ISO 时间戳，仅返回此时间前创建的连接",
                        },
                    },
                    "required": ["engram_id"],
                },
            ),
            Tool(
                name="memento_nexus_invalidate",
                description="标记 nexus 连接为失效。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "nexus_id": {"type": "string", "description": "nexus 连接 ID"},
                    },
                    "required": ["nexus_id"],
                },
            ),
            Tool(
                name="memento_pin",
                description="钉住一条 engram，设置 rigidity 值（防止衰减）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engram_id": {"type": "string"},
                        "rigidity": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "刚性值，0.0=不固定，1.0=完全固定",
                        },
                    },
                    "required": ["engram_id", "rigidity"],
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = _dispatch_tool(api, name, arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    @app.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(
                uri="memento://vault/stats",
                name="Vault 统计",
                description="记忆数据库统计概要",
            ),
            Resource(
                uri="memento://vault/recent",
                name="最近记忆",
                description="最近 10 条活跃记忆",
            ),
            Resource(
                uri="memento://epochs",
                name="Epoch 历史",
                description="最近 Epoch 运行记录",
            ),
            Resource(
                uri="memento://debt",
                name="Cognitive Debt",
                description="未解决的 cognitive debt 列表",
            ),
            Resource(
                uri="memento://daily/today",
                name="今日时间线",
                description="今天的 capture 和 session 事件，按时间排序",
            ),
        ]

    @app.read_resource()
    async def read_resource(uri) -> str:
        uri_str = str(uri)
        if uri_str == "memento://vault/stats":
            s = api.status()
            return json.dumps(
                {
                    "total": s.total,
                    "active": s.active,
                    "forgotten": s.forgotten,
                    "total_sessions": s.total_sessions,
                    "total_observations": s.total_observations,
                    "by_state": s.by_state,
                    "pending_capture": s.pending_capture,
                    "pending_delta": s.pending_delta,
                    "cognitive_debt_count": s.cognitive_debt_count,
                    "last_epoch_committed_at": s.last_epoch_committed_at,
                },
                ensure_ascii=False,
            )
        elif uri_str == "memento://vault/recent":
            rows = api.core.conn.execute(
                """SELECT id, content, type, strength, last_accessed
                   FROM engrams WHERE forgotten = 0
                   ORDER BY last_accessed DESC LIMIT 10"""
            ).fetchall()
            return json.dumps(
                [
                    {
                        "id": row["id"],
                        "content": row["content"],
                        "type": row["type"],
                        "strength": row["strength"],
                    }
                    for row in rows
                ],
                ensure_ascii=False,
            )
        elif uri_str == "memento://epochs":
            epochs = api.epoch_status()
            return json.dumps(epochs, ensure_ascii=False)
        elif uri_str == "memento://debt":
            debt = api.epoch_debt()
            return json.dumps(debt, ensure_ascii=False)
        elif uri_str == "memento://daily/today":
            from datetime import datetime as _dt
            today = _dt.now().strftime("%Y-%m-%d")
            captures = api.core.conn.execute(
                """SELECT id, content, type, tags, importance, origin, created_at
                   FROM capture_log
                   WHERE created_at >= ? AND epoch_id IS NULL
                   ORDER BY created_at""",
                (today,),
            ).fetchall()
            events = api.core.conn.execute(
                """SELECT id, session_id, event_type, payload, created_at
                   FROM session_events
                   WHERE created_at >= ?
                   ORDER BY created_at""",
                (today,),
            ).fetchall()
            timeline = []
            for row in captures:
                d = dict(row)
                d["source"] = "capture"
                timeline.append(d)
            for row in events:
                d = dict(row)
                d["source"] = "session_event"
                timeline.append(d)
            timeline.sort(key=lambda x: x.get("created_at", ""))
            return json.dumps(timeline, ensure_ascii=False)
        return json.dumps({"error": "resource not found"})

    @app.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="memento_prime",
                description="基于项目和任务生成 priming prompt，包含相关记忆和用户偏好。",
            ),
        ]

    @app.get_prompt()
    async def get_prompt(
        name: str, arguments: dict | None = None
    ) -> list[PromptMessage]:
        if name != "memento_prime":
            return []
        args = arguments or {}
        query = args.get("task") or args.get("project") or "项目概况"
        priming = api.recall(query, max_results=5, reinforce=False)
        lines = ["# Memento 项目记忆上下文\n"]
        if priming:
            lines.append(
                f"以下是与当前任务相关的 {len(priming)} 条记忆：\n"
            )
            for m in priming:
                if isinstance(m, dict):
                    staleness = ""
                    sl = m.get("staleness_level", "")
                    if sl == "stale":
                        staleness = " ⚠️较旧"
                    elif sl == "very_stale":
                        staleness = " ⏳可能过时"
                    lines.append(f"- [{m.get('type', '?')}] {m.get('content', '')}{staleness}")
                else:
                    lines.append(f"- [{m.type}] {m.content}")
        else:
            lines.append("暂无相关记忆。")
        return [
            PromptMessage(
                role="user",
                content=TextContent(type="text", text="\n".join(lines)),
            )
        ]

    return app, api


def _dispatch_tool(api: MementoAPI, name: str, arguments: dict) -> dict:
    """分发工具调用到 api.py。"""

    # ── Deprecated tools ──
    if name in _DEPRECATED_TOOLS:
        return {"error": _DEPRECATED_TOOLS[name], "deprecated": True}

    if name == "memento_session_start":
        r = api.session_start(
            project=arguments.get("project"), task=arguments.get("task")
        )
        priming_list = []
        for m in r.priming_memories:
            if isinstance(m, dict):
                priming_list.append({
                    "id": m.get("id"),
                    "content": m.get("content"),
                    "type": m.get("type"),
                    "score": m.get("score", 0),
                    "layer": m.get("layer", "L2"),
                })
            else:
                # Legacy RecallResult object
                priming_list.append({
                    "id": m.id,
                    "content": m.content,
                    "type": m.type,
                    "score": m.score,
                    "layer": getattr(m, "layer", "L2"),
                })
        return {
            "session_id": r.session_id,
            "priming_count": len(r.priming_memories),
            "priming_memories": priming_list,
        }
    elif name == "memento_session_end":
        r = api.session_end(
            arguments["session_id"],
            outcome=arguments.get("outcome", "completed"),
            summary=arguments.get("summary"),
        )
        if r:
            return {
                "status": r.status,
                "captures_count": r.captures_count,
                "observations_count": r.observations_count,
                "auto_captures_count": r.auto_captures_count,
            }
        return {"error": "session not found"}
    elif name == "memento_recall":
        results = api.recall(
            arguments["query"],
            max_results=arguments.get("max_results", 5),
        )
        out = []
        for r in results:
            if isinstance(r, dict):
                out.append({
                    "id": r.get("id"),
                    "content": r.get("content"),
                    "type": r.get("type"),
                    "tags": r.get("tags"),
                    "origin": r.get("origin"),
                    "score": r.get("score", 0),
                    "staleness_level": r.get("staleness_level", "fresh"),
                    "provisional": r.get("provisional", False),
                })
            else:
                # Legacy RecallResult from core.py path
                out.append({
                    "id": r.id,
                    "content": r.content,
                    "type": r.type,
                    "tags": r.tags if isinstance(r.tags, str) else json.dumps(r.tags) if r.tags else None,
                    "origin": getattr(r, "origin", None),
                    "score": r.score,
                    "staleness_level": "fresh",
                    "provisional": getattr(r, "provisional", False),
                })
        return out
    elif name == "memento_capture":
        result = api.capture(
            content=arguments["content"],
            type=arguments.get("type", "fact"),
            importance=arguments.get("importance", "normal"),
            tags=arguments.get("tags"),
            origin=arguments.get("origin", "human"),
            session_id=arguments.get("session_id"),
        )
        # awake mode returns dict, legacy returns engram_id string
        if isinstance(result, dict):
            result["state"] = "buffered"
            return result
        return {"engram_id": result, "state": "committed"}
    elif name == "memento_observe":
        r = api.ingest_observation(
            content=arguments["content"],
            tool=arguments.get("tool"),
            files=arguments.get("files"),
            tags=arguments.get("tags"),
            session_id=arguments.get("session_id"),
            importance=arguments.get("importance", "normal"),
        )
        return {
            "event_id": r.event_id,
            "promoted": r.promoted,
            "engram_id": r.engram_id,
            "skipped": r.skipped,
        }
    elif name == "memento_status":
        s = api.status()
        return {
            "total": s.total,
            "active": s.active,
            "forgotten": s.forgotten,
            "total_sessions": s.total_sessions,
            "active_sessions": s.active_sessions,
            "total_observations": s.total_observations,
            # v0.5 fields
            "by_state": s.by_state,
            "pending_capture": s.pending_capture,
            "pending_delta": s.pending_delta,
            "pending_recon": s.pending_recon,
            "cognitive_debt_count": s.cognitive_debt_count,
            "last_epoch_committed_at": s.last_epoch_committed_at,
            "decay_watermark": s.decay_watermark,
        }
    elif name == "memento_forget":
        result = api.forget(arguments["engram_id"])
        # awake mode returns dict with pending status
        if isinstance(result, dict):
            return result
        if result:
            return {"status": "pending", "message": "Forget request queued for next epoch."}
        return {"success": False}
    # ── v0.5 新增 Tools ──
    elif name == "memento_epoch_run":
        return api.epoch_run(
            mode=arguments.get("mode", "full"),
            trigger=arguments.get("trigger", "manual"),
        )
    elif name == "memento_epoch_status":
        return {"epochs": api.epoch_status()}
    elif name == "memento_epoch_debt":
        return {"debt": api.epoch_debt()}
    elif name == "memento_inspect":
        result = api.inspect(arguments["engram_id"])
        if result is None:
            return {"error": "engram not found"}
        return result
    elif name == "memento_nexus":
        engram_id = arguments["engram_id"]
        depth = arguments.get("depth", 1)
        include_invalidated = arguments.get("include_invalidated", False)
        since = arguments.get("since")
        until = arguments.get("until")
        return _get_nexus(api, engram_id, depth, include_invalidated, since, until)
    elif name == "memento_nexus_invalidate":
        from memento.repository import invalidate_nexus
        result = invalidate_nexus(api.core.conn, arguments["nexus_id"])
        if result:
            return {"status": "invalidated", "nexus_id": arguments["nexus_id"]}
        return {"status": "not_found", "message": "Nexus not found or already invalidated"}
    elif name == "memento_pin":
        return api.pin(
            arguments["engram_id"],
            arguments["rigidity"],
        )
    return {"error": f"unknown tool: {name}"}


def _get_nexus(api: MementoAPI, engram_id: str, depth: int = 1,
               include_invalidated: bool = False, since: str = None,
               until: str = None) -> dict:
    """获取 engram 的 nexus 连接图谱。"""
    conn = api.core.conn

    # Build WHERE clause
    where_parts = ["(source_id=? OR target_id=?)"]
    params = [engram_id, engram_id]

    if not include_invalidated:
        where_parts.append("invalidated_at IS NULL")

    if since:
        where_parts.append("created_at >= ?")
        params.append(since)

    if until:
        where_parts.append("created_at <= ?")
        params.append(until)

    where_clause = " AND ".join(where_parts)

    # depth 1: direct connections
    rows = conn.execute(
        f"SELECT * FROM nexus WHERE {where_clause}",
        tuple(params),
    ).fetchall()

    connections = [dict(r) for r in rows]

    if depth >= 2:
        # Collect neighbor IDs
        neighbor_ids = set()
        for r in rows:
            neighbor_ids.add(r["source_id"])
            neighbor_ids.add(r["target_id"])
        neighbor_ids.discard(engram_id)

        # depth 2: neighbors' connections
        for nid in neighbor_ids:
            where_parts2 = ["(source_id=? OR target_id=?)"]
            params2 = [nid, nid]

            if not include_invalidated:
                where_parts2.append("invalidated_at IS NULL")

            if since:
                where_parts2.append("created_at >= ?")
                params2.append(since)

            if until:
                where_parts2.append("created_at <= ?")
                params2.append(until)

            where_clause2 = " AND ".join(where_parts2)

            rows2 = conn.execute(
                f"SELECT * FROM nexus WHERE {where_clause2}",
                tuple(params2),
            ).fetchall()
            for r in rows2:
                d = dict(r)
                if d not in connections:
                    connections.append(d)

    return {"engram_id": engram_id, "depth": depth, "connections": connections}


def main():
    """Entry point for `memento-mcp-server` console script."""
    import asyncio
    from mcp.server.stdio import stdio_server

    async def _run():
        app, api = create_mcp_app()
        try:
            async with stdio_server() as (read_stream, write_stream):
                await app.run(read_stream, write_stream, app.create_initialization_options())
        finally:
            api.close()

    asyncio.run(_run())
