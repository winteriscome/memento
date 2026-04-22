"""Conversation Memory Extraction — transcript parsing, cleaning, and LLM extraction.

v0.9: Reads Claude Code transcript JSONL, cleans content, calls LLM to extract
high-value memories. All DB operations go through Worker's DBThread.execute().

This module contains ONLY pure functions (file I/O, text processing, LLM calls).
It does NOT import sqlite3 or call awake_capture directly.
"""

import hashlib
import json
import re
import threading
import time
from typing import Optional

from memento.logging import get_logger

logger = get_logger("memento.transcript")

# ── Throttling + Concurrency Control ──

_last_extract_time: dict[str, float] = {}  # in-memory cache (accelerator)
EXTRACT_COOLDOWN = 300  # 5 minutes

CURSOR_KEY_PREFIX = "transcript_extract:"

# Per-session lock: prevents concurrent extraction on same session.
# If a Stop hook fires while a previous extraction is still running,
# the second one will skip (trylock) instead of queuing up.
_session_locks: dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()


def _get_session_lock(session_id: str) -> threading.Lock:
    """Get or create a per-session lock."""
    with _session_locks_guard:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def should_extract(session_id: str) -> bool:
    """Check cooldown — return True if enough time has passed.

    Uses in-memory cache for fast path. DBThread also checks
    runtime_cursors.updated_at as durable cooldown (see transcript_get_context).
    """
    last = _last_extract_time.get(session_id, 0)
    now = time.time()
    if now - last < EXTRACT_COOLDOWN:
        return False
    _last_extract_time[session_id] = now
    return True


# ── Transcript reading (file I/O only, no DB) ──

def read_transcript_delta(
    transcript_path: str,
    last_offset: int = 0,
) -> tuple[list[dict], int]:
    """Read new messages from transcript JSONL after last_offset.

    Returns (messages, new_offset). Each message has 'role' and 'content' (string).
    Tolerates format drift: malformed lines are skipped silently.
    """
    messages = []
    current_line = 0

    with open(transcript_path, encoding="utf-8") as f:
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
                    # Normalize: extract text from block arrays
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block["text"])
                            elif isinstance(block, str):
                                text_parts.append(block)
                        content = "\n".join(text_parts)
                    if isinstance(content, str) and content.strip():
                        messages.append({"role": role, "content": content})
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    return messages, current_line


# ── Transcript cleaning (pure text processing) ──

def clean_transcript(messages: list[dict], max_messages: int = 10) -> str:
    """Clean transcript for LLM: remove code blocks, tool output, truncate.

    Limits to last max_messages entries. Returns formatted string.
    """
    if len(messages) > max_messages:
        messages = messages[-max_messages:]

    cleaned = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if not isinstance(content, str) or not content.strip():
            continue

        # Strip code blocks
        content = re.sub(r'```[\s\S]*?```', '[代码块已省略]', content)
        # Strip long lines (tool output/logs)
        lines = content.split('\n')
        lines = [l for l in lines if len(l) < 500]
        content = '\n'.join(lines)
        # Truncate single message
        if len(content) > 800:
            content = content[:800] + '...'

        if content.strip():
            cleaned.append(f"[{role}]: {content}")

    return "\n\n".join(cleaned)


# ── LLM response parsing ──

ALLOWED_TYPES = {"preference", "convention", "decision", "fact"}
ALLOWED_IMPORTANCE = {"low", "normal", "high", "critical"}


def parse_llm_response(raw: str) -> list[dict]:
    """Parse LLM response, stripping markdown fences, filtering invalid items."""
    raw = raw.strip()

    # Strip markdown code fences
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON")
        return []

    if not isinstance(data, list):
        return []

    valid = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("content"):
            continue
        if item.get("type") not in ALLOWED_TYPES:
            continue
        if item.get("importance") not in ALLOWED_IMPORTANCE:
            item["importance"] = "normal"
        item["content"] = item["content"][:100]
        valid.append(item)

    return valid


# ── Content hash (for dedup, same algorithm as awake_capture) ──

def compute_content_hash(content: str) -> str:
    """SHA256 of normalized content, matching awake_capture's algorithm."""
    normalized = content.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


# ── Main orchestrator (file I/O + LLM, DB ops via callback) ──

def run_extraction(
    transcript_path: str,
    memento_session_id: str,
    last_offset: int,
    existing_memories_summary: str,
    db_persist_callback,
):
    """Run transcript extraction: read file -> clean -> LLM -> callback to persist.

    This function does NOT access SQLite directly. All DB operations happen
    through db_persist_callback(candidates, new_offset).

    Uses a per-session lock to prevent concurrent extraction on the same session.
    If another extraction is already running for this session, this call is skipped.

    Args:
        transcript_path: Path to Claude Code transcript JSONL
        memento_session_id: Memento session ID (for logging)
        last_offset: Line offset to start reading from
        existing_memories_summary: Pre-fetched summary of existing memories
        db_persist_callback: callable(candidates: list[dict], new_offset: int)
            Called on success. Each candidate has: content, type, importance, content_hash.
            If LLM fails, this is NOT called (cursor stays unchanged for retry).
    """
    lock = _get_session_lock(memento_session_id)

    # Non-blocking trylock: if another extraction is running for this session, skip
    if not lock.acquire(blocking=False):
        logger.info(f"Transcript extraction skipped: concurrent run for session={memento_session_id}")
        return

    try:
        _run_extraction_inner(
            transcript_path, memento_session_id, last_offset,
            existing_memories_summary, db_persist_callback,
        )
    finally:
        lock.release()


def _run_extraction_inner(
    transcript_path: str,
    memento_session_id: str,
    last_offset: int,
    existing_memories_summary: str,
    db_persist_callback,
):
    """Inner extraction logic (called under per-session lock)."""
    from memento.llm import LLMClient
    from memento.prompts import build_transcript_extraction_prompt

    try:
        # 1. Read incremental transcript (file I/O only)
        messages, new_offset = read_transcript_delta(transcript_path, last_offset)

        if not messages:
            db_persist_callback([], new_offset)
            return

        # 2. Clean transcript (pure text processing)
        cleaned = clean_transcript(messages, max_messages=10)
        if not cleaned.strip():
            db_persist_callback([], new_offset)
            return

        # 3. Build prompt and call LLM
        llm = LLMClient.from_config()
        if llm is None:
            logger.info("No LLM configured, skipping transcript extraction")
            db_persist_callback([], new_offset)
            return

        prompt = build_transcript_extraction_prompt(cleaned, existing_memories_summary)
        if prompt is None:
            db_persist_callback([], new_offset)
            return

        raw_response = llm.generate(prompt)
        candidates = parse_llm_response(raw_response)

        # 4. Add content_hash to each candidate for dedup
        for c in candidates:
            c["content_hash"] = compute_content_hash(c["content"])

        # 5. Submit to DB via callback (cursor advances only on success)
        db_persist_callback(candidates, new_offset)

        logger.info(
            f"Transcript extraction complete: session={memento_session_id}, "
            f"messages={len(messages)}, candidates={len(candidates)}"
        )

    except Exception as e:
        # LLM or file I/O failure: log and swallow.
        # Cursor is NOT advanced — next Stop hook will retry.
        logger.error(f"Transcript extraction failed: {e}", exc_info=True)
