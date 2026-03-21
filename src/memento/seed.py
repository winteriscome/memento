"""v0.1 实验的种子数据与查询集生成。"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from memento.core import MementoCore


EXPERIMENT_MEMORY_SPECS = [
    {
        "key": "auth_current",
        "content": "认证使用 JWT RS256，密钥位于 /config/keys。",
        "type": "fact",
        "importance": "high",
        "tags": ["auth", "jwt"],
        "created_days_ago": 3,
        "last_accessed_days_ago": 3,
        "access_count": 5,
    },
    {
        "key": "auth_stale",
        "content": "旧认证端点是 /v1/auth，现已废弃。",
        "type": "fact",
        "importance": "normal",
        "tags": ["auth", "stale"],
        "created_days_ago": 10,
        "last_accessed_days_ago": 10,
        "access_count": 0,
    },
    {
        "key": "deploy_current",
        "content": "当前部署方式是 Docker Compose。",
        "type": "decision",
        "importance": "high",
        "tags": ["deploy", "docker"],
        "created_days_ago": 3,
        "last_accessed_days_ago": 1,
        "access_count": 5,
    },
    {
        "key": "deploy_stale",
        "content": "旧部署方式使用 PM2 直接运行 Node 进程。",
        "type": "fact",
        "importance": "normal",
        "tags": ["deploy", "stale"],
        "created_days_ago": 21,
        "last_accessed_days_ago": 21,
        "access_count": 0,
    },
    {
        "key": "style_preference",
        "content": "用户偏好 snake_case 命名风格。",
        "type": "preference",
        "importance": "critical",
        "tags": ["style", "preference"],
        "created_days_ago": 30,
        "last_accessed_days_ago": 2,
        "access_count": 20,
    },
    {
        "key": "token_rotation",
        "content": "token rotation 每 24 小时执行一次。",
        "type": "convention",
        "importance": "high",
        "tags": ["auth", "token"],
        "created_days_ago": 30,
        "last_accessed_days_ago": 1,
        "access_count": 3,
    },
    {
        "key": "db_choice",
        "content": "数据库选型为 PostgreSQL。",
        "type": "decision",
        "importance": "high",
        "tags": ["database", "postgresql"],
        "created_days_ago": 14,
        "last_accessed_days_ago": 5,
        "access_count": 5,
    },
    {
        "key": "redis_bugfix",
        "content": "修复 Redis 连接泄漏时，需要在 finally 中关闭连接池。",
        "type": "debugging",
        "importance": "high",
        "tags": ["redis", "debugging"],
        "created_days_ago": 7,
        "last_accessed_days_ago": 2,
        "access_count": 5,
    },
]


def _build_query_set(ids: dict[str, str]) -> list[dict]:
    return [
        {
            "query": "认证方案",
            "expected_ids": [ids["auth_current"]],
            "stale_ids": [ids["auth_stale"]],
        },
        {
            "query": "部署方式",
            "expected_ids": [ids["deploy_current"]],
            "stale_ids": [ids["deploy_stale"]],
        },
        {
            "query": "代码风格偏好",
            "expected_ids": [ids["style_preference"]],
        },
        {
            "query": "token rotation",
            "expected_ids": [ids["token_rotation"]],
        },
        {
            "query": "数据库选型",
            "expected_ids": [ids["db_choice"]],
        },
    ]


def seed_experiment_dataset(
    core: MementoCore,
    queries_output: Path | None = None,
) -> dict:
    """写入一组适合 v0.1 A/B 实验的种子记忆。"""
    now = datetime.now()
    ids: dict[str, str] = {}

    for spec in EXPERIMENT_MEMORY_SPECS:
        engram_id = core.capture(
            spec["content"],
            type=spec["type"],
            importance=spec["importance"],
            tags=spec["tags"],
        )
        ids[spec["key"]] = engram_id

        created_at = (now - timedelta(days=spec["created_days_ago"]))
        last_accessed = now - timedelta(days=spec["last_accessed_days_ago"])
        core.conn.execute(
            """
            UPDATE engrams
            SET created_at = ?, last_accessed = ?, access_count = ?
            WHERE id = ?
            """,
            (
                created_at.isoformat(),
                last_accessed.isoformat(),
                spec["access_count"],
                engram_id,
            ),
        )

    core.conn.commit()

    query_set = _build_query_set(ids)
    if queries_output:
        queries_output.parent.mkdir(parents=True, exist_ok=True)
        queries_output.write_text(
            json.dumps(query_set, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "inserted": len(ids),
        "ids": ids,
        "queries": query_set,
        "queries_output": str(queries_output) if queries_output else None,
    }