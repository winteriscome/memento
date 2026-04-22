"""Epoch Runner — Heavy Batch Processing (Layer 3, Task 11).

独立子进程执行的批处理引擎。编排所有 Engine 模块（Layer 2）通过 Repository 完成
7 个阶段的处理：

Phase 1: pending_forget (T7)
Phase 2: L2 consolidation (capture_log → engram)
Phase 3: Delta fold + strength
Phase 4: Nexus updates
Phase 5: Reconsolidation
Phase 6: State transitions (T5/T6)
Phase 7: View Store rebuild

v0.5.0 中 LLM 依赖操作（structuring、reconsolidation、abstraction）为占位符：
- Full 模式：自动提升所有 capture_log 项
- Light 模式：延迟到 cognitive_debt
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from memento.delta_fold import fold_deltas, plan_strength_updates, ARCHIVE_THRESHOLD
from memento.hebbian import plan_nexus_updates
from memento.rigidity import plan_reconsolidation
from memento.state_machine import TransitionPlan
from memento.repository import (
    apply_pending_forgets, apply_l2_to_l3, apply_drop_decisions,
    apply_strength_plan, apply_nexus_plan, apply_transition_plan,
    rebuild_view_store, defer_to_debt, resolve_debt,
)

from memento.logging import get_logger

logger = get_logger("memento.epoch")

# Nexus auto-invalidation thresholds
NEXUS_ARCHIVE_THRESHOLD = 0.1
NEXUS_STALE_DAYS = 90


def _auto_invalidate_stale_edges(conn: sqlite3.Connection) -> int:
    """Auto-invalidate weak, stale nexus edges. Returns count."""
    now = datetime.now()
    cutoff = (now - timedelta(days=NEXUS_STALE_DAYS)).isoformat()
    stale_edges = conn.execute(
        """SELECT id FROM nexus
           WHERE invalidated_at IS NULL
             AND association_strength < ?
             AND last_coactivated_at < ?""",
        (NEXUS_ARCHIVE_THRESHOLD, cutoff),
    ).fetchall()
    now_iso = now.isoformat()
    for edge in stale_edges:
        conn.execute(
            "UPDATE nexus SET invalidated_at = ? WHERE id = ?",
            (now_iso, edge["id"]),
        )
    if stale_edges:
        conn.commit()
    return len(stale_edges)


# ═══════════════════════════════════════════════════════════════════════════
# Lease Management
# ═══════════════════════════════════════════════════════════════════════════


def acquire_lease(conn: sqlite3.Connection, vault_id: str,
                  mode: str, trigger: str) -> Optional[str]:
    """获取 Epoch 租约。

    1. 清理过期租约（status→failed）
    2. 插入新 epoch 行（status=leased）
    3. 成功返回 epoch_id，UNIQUE 冲突返回 None

    Args:
        conn: 数据库连接
        vault_id: 保险库 ID
        mode: 模式 ('full' | 'light')
        trigger: 触发方式 ('manual' | 'session_end' | 'timer')

    Returns:
        epoch_id 或 None（已有活跃 epoch）
    """
    now = datetime.now(timezone.utc).isoformat()
    lease_expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    # Step 1: Clean up expired leases
    conn.execute(
        "UPDATE epochs SET status='failed' "
        "WHERE vault_id=? AND status IN ('leased', 'running') "
        "AND lease_expires < ?",
        (vault_id, now),
    )
    conn.commit()

    # Step 2: Insert new epoch row
    epoch_id = f"epoch-{uuid.uuid4().hex[:12]}"
    try:
        conn.execute(
            "INSERT INTO epochs "
            "(id, vault_id, status, mode, trigger, seal_timestamp, "
            "lease_acquired, lease_expires) "
            "VALUES (?, ?, 'leased', ?, ?, ?, ?, ?)",
            (epoch_id, vault_id, mode, trigger, now, now, lease_expires),
        )
        conn.commit()
        return epoch_id
    except sqlite3.IntegrityError:
        # UNIQUE conflict — another epoch is active for this vault
        return None


def promote_lease(conn: sqlite3.Connection, epoch_id: str) -> None:
    """将 epoch 状态从 leased 提升为 running。"""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE epochs SET status='running', started_at=? WHERE id=?",
        (now, epoch_id),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Epoch Phases
# ═══════════════════════════════════════════════════════════════════════════


def _phase1_pending_forget(conn: sqlite3.Connection, epoch_id: str) -> None:
    """Phase 1: 处理 pending_forget 队列 (T7)。"""
    apply_pending_forgets(conn, epoch_id)


def _phase2_l2_consolidation(conn: sqlite3.Connection, epoch_id: str,
                              seal_timestamp: str, mode: str,
                              llm_client=None) -> None:
    """Phase 2: L2 → L3 整合。

    Full + LLM: LLM 推导 type/tags，检测重复，结构化后提升。
    Full 无 LLM: 自动提升（v0.5.0 兼容）。
    Light: 不消费 capture_log，延迟到 cognitive_debt。
    """
    # Fresh capture_log entries
    rows = conn.execute(
        "SELECT * FROM capture_log "
        "WHERE epoch_id IS NULL AND created_at < ?",
        (seal_timestamp,),
    ).fetchall()

    # Recover items from cognitive debt (previous LLM failures)
    debt_rows = conn.execute(
        """SELECT c.* FROM capture_log c
           JOIN cognitive_debt d
             ON json_extract(d.raw_ref, '$.capture_log_id') = c.id
           WHERE d.type = 'pending_consolidation'
             AND d.resolved_at IS NULL
             AND c.epoch_id IS NULL""",
    ).fetchall()

    # Deduplicate (a row may appear in both fresh and debt)
    all_dict = {r["id"]: dict(r) for r in list(rows) + list(debt_rows)}
    items = list(all_dict.values())

    if not items:
        return

    BATCH_SIZE = 20  # Prevent LLM context window overflow

    if mode == "full" and llm_client is not None:
        # LLM-driven structuring (batched)
        import hashlib as _hashlib
        import json as _json
        from memento.prompts import build_structuring_prompt

        for batch_start in range(0, len(items), BATCH_SIZE):
            batch = items[batch_start:batch_start + BATCH_SIZE]
            prompt = build_structuring_prompt(batch)

            llm_results = None
            if prompt:
                try:
                    llm_results = llm_client.generate_json(prompt)
                except Exception:
                    llm_results = None

            if llm_results and isinstance(llm_results, list):
                llm_by_id = {
                    r["id"]: r for r in llm_results
                    if isinstance(r, dict) and "id" in r
                }

                for item in batch:
                    llm_item = llm_by_id.get(item["id"])

                    if not llm_item:
                        defer_to_debt(conn, "pending_consolidation",
                                     {"capture_log_id": item["id"]}, epoch_id)
                        continue

                    processed = item.copy()
                    processed["type"] = llm_item.get("type", item.get("type", "fact"))

                    new_content = llm_item.get("content")
                    if new_content and new_content != item["content"]:
                        processed["content"] = new_content
                        processed["content_hash"] = _hashlib.sha256(
                            new_content.strip().lower().encode()
                        ).hexdigest()
                        processed["embedding"] = None
                        processed["embedding_dim"] = None
                        processed["embedding_pending"] = 1

                    if llm_item.get("tags"):
                        processed["tags"] = _json.dumps(llm_item["tags"])

                    plan = TransitionPlan(
                        engram_id=None,
                        capture_log_id=item["id"],
                        from_state="buffered",
                        to_state="consolidated",
                        transition="T1",
                        reason="llm-structured (v0.7.0)",
                        epoch_id=epoch_id,
                    )
                    apply_l2_to_l3(conn, plan, processed)
                    resolve_debt(conn, "pending_consolidation",
                                {"capture_log_id": item["id"]})
            else:
                # LLM failed on this batch — defer all to debt
                for item in batch:
                    defer_to_debt(conn, "pending_consolidation",
                                 {"capture_log_id": item["id"]}, epoch_id)
    elif mode == "full":
        # No LLM client — auto-promote (v0.5.0 behavior)
        for item in items:
            plan = TransitionPlan(
                engram_id=None,
                capture_log_id=item["id"],
                from_state="buffered",
                to_state="consolidated",
                transition="T1",
                reason="auto-promote (no llm)",
                epoch_id=epoch_id,
            )
            apply_l2_to_l3(conn, plan, item)
            resolve_debt(conn, "pending_consolidation",
                        {"capture_log_id": item["id"]})
    else:
        # Light mode: defer each item to cognitive debt
        for item in items:
            defer_to_debt(conn, "pending_consolidation",
                         {"capture_log_id": item["id"]}, epoch_id)


def _phase3_delta_fold(conn: sqlite3.Connection, epoch_id: str,
                        seal_timestamp: str) -> None:
    """Phase 3: Delta fold + strength 更新。"""
    rows = conn.execute(
        "SELECT * FROM delta_ledger "
        "WHERE epoch_id IS NULL AND created_at < ?",
        (seal_timestamp,),
    ).fetchall()

    if not rows:
        return

    deltas = [dict(r) for r in rows]
    folds = fold_deltas(deltas)

    if not folds:
        return

    # Build engrams lookup for plan_strength_updates
    engram_ids = list({f.engram_id for f in folds})
    placeholders = ",".join("?" * len(engram_ids))
    engrams_rows = conn.execute(
        f"SELECT id, strength, access_count, origin, verified "
        f"FROM engrams WHERE id IN ({placeholders})",
        engram_ids,
    ).fetchall()
    engrams_lookup = {
        r["id"]: dict(r) for r in engrams_rows
    }

    plans = plan_strength_updates(folds, engrams_lookup)
    apply_strength_plan(conn, plans, epoch_id)


def _phase4_nexus_updates(conn: sqlite3.Connection, epoch_id: str,
                           seal_timestamp: str) -> None:
    """Phase 4: Nexus 更新（基于 recon_buffer）。"""
    rows = conn.execute(
        "SELECT * FROM recon_buffer "
        "WHERE nexus_consumed_epoch_id IS NULL AND created_at < ?",
        (seal_timestamp,),
    ).fetchall()

    if not rows:
        return

    # Convert to the format expected by plan_nexus_updates
    recon_items = []
    for r in rows:
        recon_items.append({
            "id": r["id"],
            "engram_id": r["engram_id"],
            "coactivated_ids": r["coactivated_ids"],
            "query_context": r["query_context"],
            "occurred_at": r["created_at"],  # recon_buffer uses created_at
        })

    # Build existing nexus lookup
    existing_rows = conn.execute(
        "SELECT source_id, target_id, type, association_strength FROM nexus"
    ).fetchall()
    existing_nexus = {
        (r["source_id"], r["target_id"], r["type"]): r["association_strength"]
        for r in existing_rows
    }

    plans = plan_nexus_updates(recon_items, existing_nexus)
    apply_nexus_plan(conn, plans, epoch_id)

    # Auto-invalidate weak, stale edges
    _auto_invalidate_stale_edges(conn)


def _phase5_reconsolidation(conn: sqlite3.Connection, epoch_id: str,
                              seal_timestamp: str, mode: str,
                              llm_client=None) -> None:
    """Phase 5: 再巩固。

    Full + LLM: LLM 根据 recon_buffer 上下文精炼 engram 内容（受 rigidity 约束）。
    Full 无 LLM: 标记 content_consumed_epoch_id（v0.5.0 兼容）。
    Light: 允许内容更新的项延迟到 debt，不可修改的直接标记已消费。
    """
    rows = conn.execute(
        "SELECT * FROM recon_buffer "
        "WHERE content_consumed_epoch_id IS NULL AND created_at < ?",
        (seal_timestamp,),
    ).fetchall()

    if not rows:
        return

    # Group by engram_id
    grouped = {}
    for r in rows:
        eid = r["engram_id"]
        if eid not in grouped:
            grouped[eid] = []
        grouped[eid].append(r)

    for engram_id, recon_rows in grouped.items():
        engram_row = conn.execute(
            "SELECT id, content, type, rigidity FROM engrams WHERE id=?",
            (engram_id,),
        ).fetchone()

        if not engram_row:
            for r in recon_rows:
                conn.execute(
                    "UPDATE recon_buffer SET content_consumed_epoch_id=? WHERE id=?",
                    (epoch_id, r["id"]),
                )
            conn.commit()
            continue

        from memento.rigidity import can_modify_content

        if mode == "full" and llm_client is not None and can_modify_content(engram_row["rigidity"] or 0.0):
            # LLM-driven reconsolidation
            recon_contexts = [
                r["query_context"] for r in recon_rows
                if r["query_context"]
            ]

            if recon_contexts:
                from memento.prompts import build_reconsolidation_prompt
                prompt = build_reconsolidation_prompt(
                    engram_content=engram_row["content"],
                    engram_type=engram_row["type"] or "fact",
                    recon_contexts=recon_contexts,
                )

                if prompt:
                    try:
                        result = llm_client.generate_json(prompt)
                        if isinstance(result, dict) and result.get("changed"):
                            import hashlib as _hashlib
                            new_content = result.get("content", engram_row["content"])
                            new_hash = _hashlib.sha256(
                                new_content.strip().lower().encode()
                            ).hexdigest()
                            # Fix #2: update content + hash, clear stale embedding
                            conn.execute(
                                """UPDATE engrams
                                   SET content=?, content_hash=?,
                                       embedding=NULL, embedding_dim=NULL,
                                       embedding_pending=1
                                   WHERE id=?""",
                                (new_content, new_hash, engram_id),
                            )
                    except Exception:
                        pass  # LLM failure — leave content unchanged

            # Mark consumed regardless of LLM outcome
            for r in recon_rows:
                conn.execute(
                    "UPDATE recon_buffer SET content_consumed_epoch_id=? WHERE id=?",
                    (epoch_id, r["id"]),
                )
            resolve_debt(conn, "pending_reconsolidation", {"engram_id": engram_id})
            conn.commit()
        elif mode == "full":
            # No LLM or rigidity locked — just mark consumed (v0.5.0 behavior)
            for r in recon_rows:
                conn.execute(
                    "UPDATE recon_buffer SET content_consumed_epoch_id=? WHERE id=?",
                    (epoch_id, r["id"]),
                )
            resolve_debt(conn, "pending_reconsolidation", {"engram_id": engram_id})
            conn.commit()
        else:
            # Light mode
            allow_update = can_modify_content(engram_row["rigidity"] or 0.0)

            if allow_update:
                defer_to_debt(conn, "pending_reconsolidation",
                             {"engram_id": engram_id}, epoch_id)
            else:
                for r in recon_rows:
                    conn.execute(
                        "UPDATE recon_buffer SET content_consumed_epoch_id=? WHERE id=?",
                        (epoch_id, r["id"]),
                    )
            conn.commit()


def _phase6_state_transitions(conn: sqlite3.Connection, epoch_id: str, mode: str = "full") -> None:
    """Phase 6: 状态转换 (T5/T6)。

    T6: consolidated → archived (strength < ARCHIVE_THRESHOLD)
    T5: abstraction 延迟到 v0.5.1
    """
    # T6: Archive low-strength engrams
    low_strength = conn.execute(
        "SELECT id FROM engrams "
        "WHERE state='consolidated' AND strength < ?",
        (ARCHIVE_THRESHOLD,),
    ).fetchall()

    for row in low_strength:
        plan = TransitionPlan(
            engram_id=row["id"],
            capture_log_id=None,
            from_state="consolidated",
            to_state="archived",
            transition="T6",
            reason=f"strength below archive threshold ({ARCHIVE_THRESHOLD})",
            epoch_id=epoch_id,
        )
        apply_transition_plan(conn, plan)

    # T5: Abstraction deferred to v0.5.1
    # v0.5.0: T5 abstraction requires clustering infrastructure (not yet implemented).
    # No pending_abstraction debt is generated because there's no clustering to identify
    # candidates. When clustering is added in v0.5.1, light mode will defer_to_debt here.


def _phase7_view_store(conn: sqlite3.Connection, epoch_id: str) -> None:
    """Phase 7: 重建 View Store。"""
    rebuild_view_store(conn, epoch_id)


# ═══════════════════════════════════════════════════════════════════════════
# Main Runner
# ═══════════════════════════════════════════════════════════════════════════


def run_epoch_phases(conn: sqlite3.Connection, epoch_id: str,
                      mode: str, llm_client=None) -> None:
    """执行 Epoch 的所有阶段。

    1. promote_lease
    2. 读取 seal_timestamp
    3. 依次执行 Phase 1-7
    4. 成功：status='committed'(full) 或 'degraded'(light)
    5. 失败：status='failed', error=str(e)

    Args:
        conn: 数据库连接
        epoch_id: Epoch ID
        mode: 模式 ('full' | 'light')
        llm_client: LLM 客户端（Phase 2 structuring + Phase 5 reconsolidation）
    """
    try:
        promote_lease(conn, epoch_id)

        # Read seal_timestamp
        row = conn.execute(
            "SELECT seal_timestamp FROM epochs WHERE id=?",
            (epoch_id,),
        ).fetchone()
        seal_timestamp = row["seal_timestamp"]

        # Execute phases 1-7
        _phase1_pending_forget(conn, epoch_id)
        _phase2_l2_consolidation(conn, epoch_id, seal_timestamp, mode, llm_client)
        _phase3_delta_fold(conn, epoch_id, seal_timestamp)
        _phase4_nexus_updates(conn, epoch_id, seal_timestamp)
        _phase5_reconsolidation(conn, epoch_id, seal_timestamp, mode, llm_client)
        _phase6_state_transitions(conn, epoch_id, mode)
        _phase7_view_store(conn, epoch_id)

        # Success
        now = datetime.now(timezone.utc).isoformat()
        final_status = "committed" if mode == "full" else "degraded"
        conn.execute(
            "UPDATE epochs SET status=?, committed_at=? WHERE id=?",
            (final_status, now, epoch_id),
        )
        conn.commit()

    except Exception as e:
        logger.error(f"Error executing epoch phases: {e}", exc_info=True)
        conn.rollback()  # CRITICAL: discard any partial writes from failed phases
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE epochs SET status='failed', error=? WHERE id=?",
            (str(e), epoch_id),
        )
        conn.commit()
        raise
