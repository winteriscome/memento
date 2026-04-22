"""Repository — Persistence Layer (Layer 2, Task 7).

数据库写入的唯一入口。所有 apply_* 函数接受 conn + Plan 对象，
由 Engine 层（state_machine / delta_fold / hebbian）生成的纯数据计划在这里落库。

本模块不做任何业务决策，只做 SQL 操作。
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from memento.state_machine import TransitionPlan, DropDecision
from memento.delta_fold import StrengthUpdatePlan
from memento.hebbian import NexusUpdatePlan
from memento.rigidity import RIGIDITY_DEFAULTS


# ═══════════════════════════════════════════════════════════════════════════
# T1: Capture Log → Engram (L2 → L3)
# ═══════════════════════════════════════════════════════════════════════════


def apply_l2_to_l3(conn: sqlite3.Connection, plan: TransitionPlan,
                    capture_item: dict) -> str:
    """将 capture_log 记录提升为 engram。

    Args:
        conn: 数据库连接
        plan: TransitionPlan（T1，engram_id 为 None）
        capture_item: capture_log 行数据（dict）

    Returns:
        新生成的 engram_id
    """
    engram_id = f"eng-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    origin = capture_item.get("origin", "human")
    strength = 0.5 if origin == "agent" else 0.7

    engram_type = capture_item.get("type", "fact")
    rigidity = RIGIDITY_DEFAULTS.get(engram_type, 0.5)

    conn.execute(
        "INSERT INTO engrams "
        "(id, content, type, tags, strength, importance, origin, verified, "
        "created_at, last_accessed, access_count, forgotten, "
        "state, rigidity, content_hash, last_state_changed_epoch_id, "
        "embedding, embedding_dim, embedding_pending, "
        "source_session_id, source_event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            engram_id,
            capture_item["content"],
            engram_type,
            capture_item.get("tags"),
            strength,
            capture_item.get("importance", "normal"),
            origin,
            0,  # verified
            capture_item.get("created_at", now),
            now,  # last_accessed
            0,  # access_count
            0,  # forgotten
            "consolidated",
            rigidity,
            capture_item.get("content_hash"),
            plan.epoch_id,
            capture_item.get("embedding"),
            capture_item.get("embedding_dim"),
            capture_item.get("embedding_pending", 0),
            capture_item.get("source_session_id"),
            capture_item.get("source_event_id"),
        ),
    )

    # Mark capture_log as promoted
    conn.execute(
        "UPDATE capture_log SET epoch_id=?, disposition='promoted' WHERE id=?",
        (plan.epoch_id, plan.capture_log_id),
    )

    conn.commit()
    return engram_id


# ═══════════════════════════════════════════════════════════════════════════
# Drop Decisions
# ═══════════════════════════════════════════════════════════════════════════


def apply_drop_decisions(conn: sqlite3.Connection,
                         drops: list) -> None:
    """标记 capture_log 记录为丢弃。

    Args:
        conn: 数据库连接
        drops: list[DropDecision]
    """
    for drop in drops:
        conn.execute(
            "UPDATE capture_log SET epoch_id=?, disposition='dropped', "
            "drop_reason=? WHERE id=?",
            (drop.epoch_id, drop.reason, drop.capture_log_id),
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# State Transitions (T5-T10)
# ═══════════════════════════════════════════════════════════════════════════


def apply_transition_plan(conn: sqlite3.Connection,
                          plan: TransitionPlan) -> None:
    """执行状态转换。

    Args:
        conn: 数据库连接
        plan: TransitionPlan（非 T1，engram_id 必须存在）
    """
    conn.execute(
        "UPDATE engrams SET state=?, last_state_changed_epoch_id=? WHERE id=?",
        (plan.to_state, plan.epoch_id, plan.engram_id),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Pending Forgets
# ═══════════════════════════════════════════════════════════════════════════


def apply_pending_forgets(conn: sqlite3.Connection,
                          epoch_id: str) -> tuple:
    """处理 pending_forget 队列。

    - target_table='engrams': state→forgotten + 清理 delta_ledger(unconsumed)
      + 清理 recon_buffer(ALL) + nexus 由 CASCADE 删除
    - target_table='capture_log': disposition='dropped', drop_reason='user_forget'

    Args:
        conn: 数据库连接
        epoch_id: 当前 epoch ID

    Returns:
        (count, forgotten_engram_ids)
    """
    pending = conn.execute(
        "SELECT * FROM pending_forget"
    ).fetchall()

    if not pending:
        return (0, [])

    count = 0
    forgotten_engram_ids = []

    for pf in pending:
        target_table = pf["target_table"]
        target_id = pf["target_id"]
        pf_id = pf["id"]

        if target_table == "engrams":
            # Set state to forgotten
            conn.execute(
                "UPDATE engrams SET state='forgotten', "
                "last_state_changed_epoch_id=? WHERE id=?",
                (epoch_id, target_id),
            )
            # Clean unconsumed delta_ledger
            conn.execute(
                "DELETE FROM delta_ledger WHERE engram_id=? AND epoch_id IS NULL",
                (target_id,),
            )
            # Clean ALL recon_buffer rows (regardless of consumption state)
            conn.execute(
                "DELETE FROM recon_buffer WHERE engram_id=?",
                (target_id,),
            )
            # Nexus cleaned by CASCADE (ON DELETE CASCADE on engrams)
            # But state='forgotten' doesn't delete the row, so we delete nexus explicitly
            conn.execute(
                "DELETE FROM nexus WHERE source_id=? OR target_id=?",
                (target_id, target_id),
            )
            forgotten_engram_ids.append(target_id)

        elif target_table == "capture_log":
            conn.execute(
                "UPDATE capture_log SET disposition='dropped', "
                "drop_reason='user_forget', epoch_id=? WHERE id=?",
                (epoch_id, target_id),
            )

        # Delete processed pending_forget entry
        conn.execute("DELETE FROM pending_forget WHERE id=?", (pf_id,))
        count += 1

    conn.commit()
    return (count, forgotten_engram_ids)


# ═══════════════════════════════════════════════════════════════════════════
# Strength Updates
# ═══════════════════════════════════════════════════════════════════════════


def apply_strength_plan(conn: sqlite3.Connection,
                        plans: list,
                        epoch_id: str) -> None:
    """批量更新 engram 强度。

    Args:
        conn: 数据库连接
        plans: list[StrengthUpdatePlan]
        epoch_id: 当前 epoch ID
    """
    now = datetime.now(timezone.utc).isoformat()

    for plan in plans:
        if plan.update_last_accessed:
            conn.execute(
                "UPDATE engrams SET strength=?, "
                "access_count=access_count+?, last_accessed=? WHERE id=?",
                (plan.new_strength, plan.access_count_delta, now,
                 plan.engram_id),
            )
        else:
            conn.execute(
                "UPDATE engrams SET strength=?, "
                "access_count=access_count+? WHERE id=?",
                (plan.new_strength, plan.access_count_delta, plan.engram_id),
            )

        # Mark delta_ledger rows as consumed
        for ledger_id in plan.source_ledger_ids:
            conn.execute(
                "UPDATE delta_ledger SET epoch_id=? WHERE id=?",
                (epoch_id, ledger_id),
            )

    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Nexus Updates
# ═══════════════════════════════════════════════════════════════════════════


def apply_nexus_plan(conn: sqlite3.Connection,
                     plans: list,
                     epoch_id: str) -> None:
    """创建或更新 nexus 关联。

    Args:
        conn: 数据库连接
        plans: list[NexusUpdatePlan]
        epoch_id: 当前 epoch ID
    """
    now = datetime.now(timezone.utc).isoformat()

    for plan in plans:
        # Check for invalidated edge that should be resurrected
        existing_inv = conn.execute(
            "SELECT id, invalidated_at FROM nexus "
            "WHERE source_id=? AND target_id=? AND type=? AND invalidated_at IS NOT NULL",
            (plan.source_id, plan.target_id, plan.type),
        ).fetchone()

        if existing_inv:
            # Resurrect: clear invalidated_at, update strength and coactivation
            conn.execute(
                """UPDATE nexus SET
                    invalidated_at = NULL,
                    last_coactivated_at = ?,
                    association_strength = MIN(association_strength + ?, 1.0)
                WHERE id = ?""",
                (plan.last_coactivated_at, plan.strength_delta, existing_inv["id"]),
            )
            # Mark recon_buffer entries as consumed
            for recon_id in plan.source_recon_ids:
                conn.execute(
                    "UPDATE recon_buffer SET nexus_consumed_epoch_id = ? WHERE id = ?",
                    (epoch_id, recon_id),
                )
        elif plan.is_new:
            nexus_id = f"nex-{uuid.uuid4().hex[:12]}"
            # Default association_strength is 0.5, add delta
            new_strength = min(0.5 + plan.strength_delta, 1.0)
            conn.execute(
                "INSERT INTO nexus "
                "(id, source_id, target_id, type, association_strength, "
                "created_at, last_coactivated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nexus_id, plan.source_id, plan.target_id, plan.type,
                 new_strength, now, plan.last_coactivated_at),
            )
            # Mark recon_buffer rows as consumed
            for recon_id in plan.source_recon_ids:
                conn.execute(
                    "UPDATE recon_buffer SET nexus_consumed_epoch_id=? WHERE id=?",
                    (epoch_id, recon_id),
                )
        else:
            # Update existing: strength += delta, capped at 1.0
            conn.execute(
                "UPDATE nexus SET "
                "association_strength=MIN(association_strength + ?, 1.0), "
                "last_coactivated_at=? "
                "WHERE source_id=? AND target_id=? AND type=?",
                (plan.strength_delta, plan.last_coactivated_at,
                 plan.source_id, plan.target_id, plan.type),
            )
            # Mark recon_buffer rows as consumed
            for recon_id in plan.source_recon_ids:
                conn.execute(
                    "UPDATE recon_buffer SET nexus_consumed_epoch_id=? WHERE id=?",
                    (epoch_id, recon_id),
                )

    conn.commit()


def invalidate_nexus(conn: sqlite3.Connection, nexus_id: str) -> bool:
    """Mark a nexus edge as invalidated. Returns True if found and updated."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE nexus SET invalidated_at = ? WHERE id = ? AND invalidated_at IS NULL",
        (now, nexus_id),
    )
    changed = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    return changed > 0


# ═══════════════════════════════════════════════════════════════════════════
# Decay Watermark
# ═══════════════════════════════════════════════════════════════════════════


def update_decay_watermark(conn: sqlite3.Connection,
                           new_watermark: str) -> None:
    """更新衰减水位线。

    Args:
        conn: 数据库连接
        new_watermark: 新水位线（ISO 时间戳）
    """
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE runtime_cursors SET value=?, updated_at=? "
        "WHERE key='decay_watermark'",
        (new_watermark, now),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Cognitive Debt
# ═══════════════════════════════════════════════════════════════════════════


def defer_to_debt(conn: sqlite3.Connection, debt_type: str,
                  raw_ref: dict, epoch_id: str) -> None:
    """记录或累加认知债务。

    如果同类型同 raw_ref 的债务已存在，则 accumulated_epochs += 1。
    否则创建新记录。

    Args:
        conn: 数据库连接
        debt_type: 债务类型
        raw_ref: 原始引用（dict）
        epoch_id: 当前 epoch ID
    """
    now = datetime.now(timezone.utc).isoformat()
    raw_ref_json = json.dumps(raw_ref, sort_keys=True)

    # Check for existing unresolved debt with same type and raw_ref
    existing = conn.execute(
        "SELECT id FROM cognitive_debt "
        "WHERE type=? AND raw_ref=? AND resolved_at IS NULL",
        (debt_type, raw_ref_json),
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE cognitive_debt SET accumulated_epochs=accumulated_epochs+1 "
            "WHERE id=?",
            (existing["id"],),
        )
    else:
        debt_id = f"debt-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO cognitive_debt "
            "(id, type, raw_ref, priority, accumulated_epochs, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (debt_id, debt_type, raw_ref_json, 0.5, 0, now),
        )

    conn.commit()


def resolve_debt(conn: sqlite3.Connection, debt_type: str,
                 raw_ref: dict) -> None:
    """解决认知债务。

    Args:
        conn: 数据库连接
        debt_type: 债务类型
        raw_ref: 原始引用（dict）
    """
    now = datetime.now(timezone.utc).isoformat()
    raw_ref_json = json.dumps(raw_ref, sort_keys=True)

    conn.execute(
        "UPDATE cognitive_debt SET resolved_at=? "
        "WHERE type=? AND raw_ref=? AND resolved_at IS NULL",
        (now, debt_type, raw_ref_json),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# View Store Rebuild
# ═══════════════════════════════════════════════════════════════════════════


def rebuild_view_store(conn: sqlite3.Connection, epoch_id: str) -> None:
    """重建 view_engrams 和 view_nexus。

    仅包含 state='consolidated' 的 engram。

    Args:
        conn: 数据库连接
        epoch_id: 当前 epoch ID
    """
    now = datetime.now(timezone.utc).isoformat()

    # Rebuild view_engrams
    conn.execute("DELETE FROM view_engrams")
    conn.execute("""
        INSERT INTO view_engrams
            (id, content, type, tags, state, strength, importance, origin,
             verified, rigidity, access_count, created_at, last_accessed,
             content_hash, embedding, embedding_dim)
        SELECT
            id, content, type, tags, state, strength, importance, origin,
            verified, rigidity, access_count, created_at, last_accessed,
            content_hash, embedding, embedding_dim
        FROM engrams WHERE state = 'consolidated'
    """)

    # Rebuild view_nexus: only nexus between consolidated engrams
    conn.execute("DELETE FROM view_nexus")
    conn.execute("""
        INSERT INTO view_nexus
            (id, source_id, target_id, direction, type,
             association_strength, invalidated_at)
        SELECT
            n.id, n.source_id, n.target_id, n.direction, n.type,
            n.association_strength, n.invalidated_at
        FROM nexus n
        JOIN engrams e1 ON n.source_id = e1.id AND e1.state = 'consolidated'
        JOIN engrams e2 ON n.target_id = e2.id AND e2.state = 'consolidated'
    """)

    # Update view_pointer
    conn.execute(
        "INSERT OR REPLACE INTO view_pointer (id, epoch_id, refreshed_at) "
        "VALUES ('current', ?, ?)",
        (epoch_id, now),
    )

    conn.commit()
