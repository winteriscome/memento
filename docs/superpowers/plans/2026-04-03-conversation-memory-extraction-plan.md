# Conversation Memory Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Stop hook-driven pipeline that reads Claude Code transcript, uses LLM to extract high-value memories from conversation, and writes them to capture_log for epoch consolidation.

**Architecture:** Stop hook (`flush-and-epoch`) dispatches transcript extraction to Worker via `POST /transcript/extract`. Worker spawns a background thread for file I/O and LLM calls (no DB access in background thread). All SQLite operations (cursor read/write, dedup check, awake_capture) go through `DBThread.execute()` to respect the Worker's single-connection-owner model. Existing `capture_log → epoch → engram` pipeline handles final consolidation.

**Tech Stack:** Python 3.10+, `LLMClient` from `src/memento/llm.py` (`LLMClient.from_env()`), SQLite `runtime_cursors`, `awake_capture`.

**Spec:** `docs/superpowers/specs/2026-04-03-conversation-memory-extraction-design.md`

---

## Key Architecture Constraint: DBThread Boundary

Current Worker architecture (`src/memento/worker.py`):
- `DBThread` owns the sole SQLite connection
- All DB operations go through `DBThread.execute(action, **kwargs)` → `_handle_command()`
- Background threads must NOT directly use `conn.execute()` or call `awake_capture()`

For transcript extraction, the split is:
- **Background thread** (no DB): read transcript file, clean content, call LLM, parse JSON
- **DBThread** (via `.execute()`): read cursor, check duplicates, write captures, update cursor

## LLM Client Contract

- Import: `from memento.llm import LLMClient`
- Init: `LLMClient.from_env()` — reads `MEMENTO_LLM_BASE_URL/API_KEY/MODEL` from env
- Returns `None` if env vars not set → graceful skip (no extraction, no cursor advance)
- Call: `llm.generate(prompt)` → returns raw string
- JSON parsing: use `LLMClient._extract_json()` or manual `parse_llm_response()` with markdown fence stripping
- Failure: log error, do NOT advance cursor (allows retry on next Stop hook)

## File Structure

```
src/memento/transcript.py       # NEW: Pure functions (no DB access):
                                #   - read_transcript_delta (file I/O only)
                                #   - clean_transcript (content sanitization)
                                #   - parse_llm_response (JSON parsing)
                                #   - run_extraction (orchestrator: file + LLM, then submit to DBThread)

src/memento/prompts.py          # MODIFY: Add build_transcript_extraction_prompt()

src/memento/worker.py           # MODIFY: Add HTTP route + DBThread actions:
                                #   - /transcript/extract (HTTP handler → background thread)
                                #   - "transcript_get_context" action (cursor + memory summary)
                                #   - "transcript_persist" action (dedup + capture + cursor update)

plugin/scripts/hook-handler.sh  # MODIFY: Add extraction dispatch to flush-and-epoch
src/memento/scripts/hook-handler.sh  # MODIFY: Keep in sync (both files exist)

tests/test_transcript.py        # NEW: Unit + integration tests
```

---

## Phase 1: Core Transcript Processing

### Task 1: Add transcript extraction prompt to prompts.py

**Files:**
- Modify: `src/memento/prompts.py`
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write the test**

Create `tests/test_transcript.py`:

```python
"""Transcript extraction tests."""
import pytest


def test_build_transcript_extraction_prompt_basic():
    """Prompt includes transcript and existing memories."""
    from memento.prompts import build_transcript_extraction_prompt

    result = build_transcript_extraction_prompt(
        transcript="[user]: 以后都用中文回答\n\n[assistant]: 好的",
        existing_memories="- [preference] 用户偏好暗色主题",
    )
    assert "以后都用中文回答" in result
    assert "用户偏好暗色主题" in result
    assert "preference" in result
    assert "convention" in result
    assert "JSON" in result


def test_build_transcript_extraction_prompt_empty_transcript():
    """Returns None for empty transcript."""
    from memento.prompts import build_transcript_extraction_prompt

    result = build_transcript_extraction_prompt(
        transcript="",
        existing_memories="",
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py::test_build_transcript_extraction_prompt_basic -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement the prompt**

Add to `src/memento/prompts.py`:

```python
def build_transcript_extraction_prompt(
    transcript: str,
    existing_memories: str,
) -> str | None:
    """Build prompt for transcript memory extraction.

    Returns None if transcript is empty.
    """
    if not transcript or not transcript.strip():
        return None

    return f"""你是一个记忆提炼专家。分析以下最近的对话，提取具有长期跨会话价值的信息。

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
  {{{{
    "content": "精炼的一句话结论",
    "type": "preference|convention|decision|fact",
    "importance": "normal|high|critical"
  }}}}
]

只返回 JSON，不要其他文字。"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v`
Expected: PASS

---

### Task 2: Implement transcript file parsing and cleaning (pure functions, no DB)

**Files:**
- Create: `src/memento/transcript.py`
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_transcript.py`:

```python
import json
import tempfile
import os
from pathlib import Path


def _make_transcript(entries: list[dict]) -> str:
    """Create a temporary transcript JSONL file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for entry in entries:
        tmp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp.close()
    return tmp.name


def _make_entry(role: str, content, **extra) -> dict:
    """Create a transcript JSONL entry matching Claude Code format."""
    msg = {"role": role, "content": content}
    return {"message": msg, "type": "assistant" if role == "assistant" else "user", **extra}


def test_read_transcript_delta_basic():
    """Reads user and assistant messages from transcript."""
    from memento.transcript import read_transcript_delta

    path = _make_transcript([
        _make_entry("user", "你好"),
        _make_entry("assistant", [{"type": "text", "text": "你好！有什么可以帮忙的？"}]),
        _make_entry("user", "帮我写个函数"),
    ])
    try:
        messages, new_offset = read_transcript_delta(path, last_offset=0)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "你好"
        assert new_offset == 3
    finally:
        os.unlink(path)


def test_read_transcript_delta_incremental():
    """Only reads new lines after offset."""
    from memento.transcript import read_transcript_delta

    path = _make_transcript([
        _make_entry("user", "第一轮"),
        _make_entry("assistant", [{"type": "text", "text": "回复一"}]),
        _make_entry("user", "第二轮"),
        _make_entry("assistant", [{"type": "text", "text": "回复二"}]),
    ])
    try:
        messages, offset = read_transcript_delta(path, last_offset=2)
        assert len(messages) == 2
        assert messages[0]["content"] == "第二轮"
        assert offset == 4
    finally:
        os.unlink(path)


def test_read_transcript_delta_skips_malformed():
    """Skips malformed lines without crashing."""
    from memento.transcript import read_transcript_delta

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    tmp.write(json.dumps(_make_entry("user", "正常行")) + "\n")
    tmp.write("this is not json\n")
    tmp.write(json.dumps(_make_entry("assistant", [{"type": "text", "text": "也正常"}])) + "\n")
    tmp.close()
    try:
        messages, offset = read_transcript_delta(tmp.name, last_offset=0)
        assert len(messages) == 2
        assert offset == 3
    finally:
        os.unlink(tmp.name)


def test_clean_transcript_strips_code_blocks():
    """Removes code blocks from transcript."""
    from memento.transcript import clean_transcript

    messages = [
        {"role": "user", "content": "帮我写个函数"},
        {"role": "assistant", "content": "好的：\n```python\ndef foo():\n    pass\n```\n这就是一个空函数。"},
    ]
    result = clean_transcript(messages)
    assert "def foo" not in result
    assert "空函数" in result


def test_clean_transcript_handles_content_blocks():
    """Extracts text from assistant content blocks — already normalized by read_transcript_delta."""
    from memento.transcript import clean_transcript

    messages = [
        {"role": "assistant", "content": "文件内容分析完毕，建议用 React。"},
    ]
    result = clean_transcript(messages)
    assert "React" in result


def test_clean_transcript_truncates_long_content():
    """Truncates messages longer than 800 chars."""
    from memento.transcript import clean_transcript

    messages = [{"role": "user", "content": "x" * 2000}]
    result = clean_transcript(messages)
    assert len(result) < 1000


def test_clean_transcript_window_limit():
    """Limits to last N messages."""
    from memento.transcript import clean_transcript

    messages = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    result = clean_transcript(messages, max_messages=4)
    assert "msg 19" in result
    assert "msg 0" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v -k "read_transcript or clean_transcript"`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement transcript.py (pure functions only)**

Create `src/memento/transcript.py`:

```python
"""Conversation Memory Extraction — transcript parsing, cleaning, and LLM extraction.

v0.9: Reads Claude Code transcript JSONL, cleans content, calls LLM to extract
high-value memories. All DB operations go through Worker's DBThread.execute().

This module contains ONLY pure functions (file I/O, text processing, LLM calls).
It does NOT import sqlite3 or call awake_capture directly.
"""

import hashlib
import json
import re
import time
from typing import Optional

from memento.logging import get_logger

logger = get_logger("memento.transcript")


# ── Throttling (in-memory, no DB) ──

_last_extract_time: dict[str, float] = {}
EXTRACT_COOLDOWN = 300  # 5 minutes


def should_extract(session_id: str) -> bool:
    """Check cooldown — return True if enough time has passed."""
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


# ── Main orchestrator (file I/O + LLM, DB ops via db_thread callback) ──

def run_extraction(
    transcript_path: str,
    memento_session_id: str,
    last_offset: int,
    existing_memories_summary: str,
    db_persist_callback,
):
    """Run transcript extraction: read file → clean → LLM → callback to persist.

    This function does NOT access SQLite directly. All DB operations happen
    through db_persist_callback(candidates, new_offset).

    Args:
        transcript_path: Path to Claude Code transcript JSONL
        memento_session_id: Memento session ID (for logging)
        last_offset: Line offset to start reading from
        existing_memories_summary: Pre-fetched summary of existing memories
        db_persist_callback: callable(candidates: list[dict], new_offset: int)
            Called on success. Each candidate has: content, type, importance, content_hash.
            The callback handles dedup check, awake_capture, and cursor update.
            If LLM fails, this is NOT called (cursor stays unchanged).
    """
    from memento.llm import LLMClient
    from memento.prompts import build_transcript_extraction_prompt

    try:
        # 1. Read incremental transcript (file I/O only)
        messages, new_offset = read_transcript_delta(transcript_path, last_offset)

        if not messages:
            # No new messages, but still advance cursor
            db_persist_callback([], new_offset)
            return

        # 2. Clean transcript (pure text processing)
        cleaned = clean_transcript(messages, max_messages=10)
        if not cleaned.strip():
            db_persist_callback([], new_offset)
            return

        # 3. Build prompt and call LLM
        llm = LLMClient.from_env()
        if llm is None:
            logger.info("No LLM configured, skipping transcript extraction")
            # No LLM = no extraction, but advance cursor (nothing to retry)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v`
Expected: All PASS

---

### Task 3: Add parse_llm_response tests

**Files:**
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_transcript.py`:

```python
def test_parse_llm_response_valid():
    """Parses valid JSON array from LLM response."""
    from memento.transcript import parse_llm_response

    raw = '[{"content": "用户偏好中文", "type": "preference", "importance": "critical"}]'
    result = parse_llm_response(raw)
    assert len(result) == 1
    assert result[0]["content"] == "用户偏好中文"
    assert result[0]["type"] == "preference"


def test_parse_llm_response_with_markdown():
    """Strips markdown fences before parsing."""
    from memento.transcript import parse_llm_response

    raw = '```json\n[{"content": "test", "type": "fact", "importance": "normal"}]\n```'
    result = parse_llm_response(raw)
    assert len(result) == 1


def test_parse_llm_response_empty_array():
    """Returns empty list for empty array."""
    from memento.transcript import parse_llm_response

    result = parse_llm_response("[]")
    assert result == []


def test_parse_llm_response_invalid():
    """Returns empty list for unparseable response."""
    from memento.transcript import parse_llm_response

    result = parse_llm_response("this is not json at all")
    assert result == []


def test_parse_llm_response_filters_invalid_types():
    """Filters out items with invalid type."""
    from memento.transcript import parse_llm_response

    raw = json.dumps([
        {"content": "valid", "type": "fact", "importance": "normal"},
        {"content": "invalid type", "type": "debugging", "importance": "normal"},
        {"content": "missing type"},
    ])
    result = parse_llm_response(raw)
    assert len(result) == 1
    assert result[0]["content"] == "valid"


def test_compute_content_hash():
    """Content hash is case-insensitive and strip-normalized."""
    from memento.transcript import compute_content_hash

    h1 = compute_content_hash("Hello World")
    h2 = compute_content_hash("  hello world  ")
    assert h1 == h2
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v`
Expected: All PASS

---

## Phase 2: Worker Integration

### Task 4: Add /transcript/extract route and DBThread actions to Worker

**Files:**
- Modify: `src/memento/worker.py`
- Test: `tests/test_transcript.py`

This is the most critical task. It must respect the DBThread boundary:
- Background thread: file I/O + LLM (via `run_extraction`)
- DBThread: cursor read/write, dedup check, awake_capture

- [ ] **Step 1: Write the tests**

Append to `tests/test_transcript.py`:

```python
def test_should_extract_cooldown():
    """Respects 5-minute cooldown."""
    from memento.transcript import should_extract, _last_extract_time

    _last_extract_time.clear()
    assert should_extract("test-session") is True
    assert should_extract("test-session") is False
    assert should_extract("other-session") is True
```

- [ ] **Step 2: Add DBThread actions for transcript extraction**

Add to `src/memento/worker.py`, inside `DBThread._handle_command()`, after the `elif cmd.action == "flush":` block:

```python
            elif cmd.action == "transcript_get_context":
                # Read cursor + existing memory summary for transcript extraction
                from memento.transcript import CURSOR_KEY_PREFIX
                session_id = cmd.kwargs.get("memento_session_id", "")
                cursor_key = CURSOR_KEY_PREFIX + session_id
                # Read cursor from runtime_cursors
                try:
                    row = self._api.conn.execute(
                        "SELECT value FROM runtime_cursors WHERE key = ?",
                        (cursor_key,),
                    ).fetchone()
                    last_offset = int(row["value"]) if row else 0
                except Exception:
                    last_offset = 0
                # Read top 30 existing memories for dedup context
                try:
                    rows = self._api.conn.execute(
                        """SELECT type, content FROM view_engrams
                           WHERE forgotten = 0
                           ORDER BY strength DESC
                           LIMIT 30"""
                    ).fetchall()
                    summary_lines = [f"- [{r['type']}] {r['content'][:80]}" for r in rows]
                    existing_summary = "\n".join(summary_lines) if summary_lines else "（暂无已有记忆）"
                except Exception:
                    existing_summary = "（暂无已有记忆）"
                cmd.result = {
                    "last_offset": last_offset,
                    "existing_memories_summary": existing_summary,
                }

            elif cmd.action == "transcript_persist":
                # Dedup, capture, and update cursor — all within DBThread
                from memento.transcript import CURSOR_KEY_PREFIX
                from memento.awake import awake_capture
                from datetime import datetime, timezone
                import json as _json

                candidates = cmd.kwargs.get("candidates", [])
                new_offset = cmd.kwargs.get("new_offset", 0)
                session_id = cmd.kwargs.get("memento_session_id", "")
                written = 0

                for c in candidates:
                    content_hash = c.get("content_hash", "")
                    # Dedup: check capture_log
                    try:
                        dup = self._api.conn.execute(
                            "SELECT 1 FROM capture_log WHERE content_hash = ? LIMIT 1",
                            (content_hash,),
                        ).fetchone()
                        if dup:
                            continue
                    except Exception:
                        pass
                    # Dedup: check engrams
                    try:
                        dup = self._api.conn.execute(
                            "SELECT 1 FROM engrams WHERE content_hash = ? AND forgotten = 0 LIMIT 1",
                            (content_hash,),
                        ).fetchone()
                        if dup:
                            continue
                    except Exception:
                        pass

                    # Write to capture_log via awake_capture
                    awake_capture(
                        self._api.conn,
                        content=c["content"],
                        type=c.get("type", "fact"),
                        tags=_json.dumps(["transcript-extracted"]),
                        importance=c.get("importance", "normal"),
                        origin="agent",
                        session_id=session_id,
                    )
                    written += 1

                # Update cursor (only after successful persist)
                cursor_key = CURSOR_KEY_PREFIX + session_id
                now = datetime.now(timezone.utc).isoformat()
                self._api.conn.execute(
                    "INSERT OR REPLACE INTO runtime_cursors (key, value, updated_at) VALUES (?, ?, ?)",
                    (cursor_key, str(new_offset), now),
                )
                self._api.conn.commit()

                cmd.result = {"written": written, "total_candidates": len(candidates)}
```

- [ ] **Step 3: Add the HTTP route**

Add to `src/memento/worker.py`, in `_WorkerHandler.do_POST()`, before the `else` branch:

```python
        elif self.path == "/transcript/extract":
            import threading as _threading
            from memento.transcript import should_extract, run_extraction

            transcript_path = body.get("transcript_path", "")
            claude_session_id = body.get("claude_session_id", "")

            if not transcript_path or not Path(transcript_path).exists():
                self._respond({"status": "skipped", "reason": "no_transcript"})
                return

            # Map claude_session_id → memento_session_id
            memento_session_id = self.server.db_thread.session_registry.get(claude_session_id)
            if not memento_session_id:
                self._respond({"status": "skipped", "reason": "no_session"})
                return

            # Throttle
            if not should_extract(memento_session_id):
                self._respond({"status": "skipped", "reason": "cooldown"})
                return

            # Get context from DBThread (cursor + existing memories)
            context = self.server.db_thread.execute(
                "transcript_get_context",
                memento_session_id=memento_session_id,
            )

            # Define persist callback that submits back to DBThread
            db_thread_ref = self.server.db_thread
            sid = memento_session_id

            def persist_callback(candidates, new_offset):
                db_thread_ref.execute(
                    "transcript_persist",
                    candidates=candidates,
                    new_offset=new_offset,
                    memento_session_id=sid,
                )

            # Run extraction in background thread (file I/O + LLM only, no DB)
            _threading.Thread(
                target=run_extraction,
                args=(
                    transcript_path,
                    memento_session_id,
                    context["last_offset"],
                    context["existing_memories_summary"],
                    persist_callback,
                ),
                daemon=True,
            ).start()

            self._respond({"status": "accepted"})
```

- [ ] **Step 4: Verify import works**

Run: `cd /Users/maizi/data/work/memento && python -c "from memento.worker import WorkerServer; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Run all tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v`
Expected: All PASS

---

## Phase 3: Hook Integration

### Task 5: Add transcript extraction dispatch to hook-handler.sh

**Files:**
- Modify: `plugin/scripts/hook-handler.sh`
- Modify: `src/memento/scripts/hook-handler.sh`

- [ ] **Step 1: Modify plugin/scripts/hook-handler.sh**

In the `flush-and-epoch)` branch, insert transcript extraction dispatch **after** the flush and **before** the epoch throttle logic. The full replacement for the `flush-and-epoch)` case:

```bash
  flush-and-epoch)
    # 1. Flush (unchanged)
    PAYLOAD=$(CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, os
print(json.dumps({'claude_session_id': os.environ['CLAUDE_SID']}))
")
    send_to_worker POST /flush "$PAYLOAD"

    # 2. Transcript extraction (v0.9 — async fire-and-forget, failure must not block)
    EXTRACT_PAYLOAD=$(echo "$HOOK_INPUT" | CLAUDE_SID="$CLAUDE_SID" python3 -c "
import json, sys, os
try:
    d = json.load(sys.stdin)
    print(json.dumps({
        'claude_session_id': os.environ['CLAUDE_SID'],
        'transcript_path': d.get('transcript_path', ''),
    }))
except Exception:
    print(json.dumps({'claude_session_id': os.environ['CLAUDE_SID'], 'transcript_path': ''}))
" 2>/dev/null)
    send_to_worker POST /transcript/extract "$EXTRACT_PAYLOAD" &

    # 3. Throttle epoch (unchanged from here)
    MIN_EPOCH_INTERVAL=300   # seconds
    MIN_PENDING_ITEMS=1

    STATUS_JSON=$(send_to_worker GET /status 2>/dev/null || echo '{}')
    SHOULD_EPOCH=$(echo "$STATUS_JSON" | python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    d = json.load(sys.stdin)
    # Check pending counts
    pending = d.get('pending_capture', 0) + d.get('pending_delta', 0) + d.get('pending_recon', 0)
    if pending < $MIN_PENDING_ITEMS:
        print('no')
        sys.exit(0)
    # Check cooldown
    last = d.get('last_epoch_committed_at')
    if last:
        last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        elapsed = (now - last_dt).total_seconds()
        if elapsed < $MIN_EPOCH_INTERVAL:
            print('no')
            sys.exit(0)
    print('yes')
except Exception:
    print('no')
" 2>/dev/null || echo "no")

    if [ "$SHOULD_EPOCH" = "yes" ]; then
      # Run light epoch in background to avoid blocking
      python3 -m memento epoch run --mode light --trigger auto > /dev/null 2>&1 &
    fi
    ;;
```

- [ ] **Step 2: Apply identical change to src/memento/scripts/hook-handler.sh**

Keep both hook-handler.sh files in sync.

- [ ] **Step 3: Verify hook runs without error**

Run: `echo '{"session_id":"test","transcript_path":"/nonexistent"}' | bash plugin/scripts/hook-handler.sh flush-and-epoch 2>&1; echo "exit: $?"`
Expected: No crash, exit 0

---

## Phase 4: Integration Tests

### Task 6: End-to-end integration tests

**Files:**
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write the integration tests**

Append to `tests/test_transcript.py`:

```python
def test_run_extraction_end_to_end():
    """Full extraction with mock LLM: transcript → candidates → callback."""
    from unittest.mock import patch, MagicMock
    from memento.transcript import run_extraction

    path = _make_transcript([
        _make_entry("user", "以后回答问题都用中文"),
        _make_entry("assistant", [{"type": "text", "text": "好的，我以后都用中文回答。"}]),
    ])

    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps([
        {"content": "用户要求始终用中文回答", "type": "preference", "importance": "critical"}
    ])

    callback_called = {}

    def mock_callback(candidates, new_offset):
        callback_called["candidates"] = candidates
        callback_called["new_offset"] = new_offset

    try:
        with patch("memento.transcript.LLMClient") as MockLLMClass:
            MockLLMClass.from_env.return_value = mock_llm

            run_extraction(
                transcript_path=path,
                memento_session_id="test-session",
                last_offset=0,
                existing_memories_summary="（暂无已有记忆）",
                db_persist_callback=mock_callback,
            )

        assert "candidates" in callback_called
        assert len(callback_called["candidates"]) == 1
        assert callback_called["candidates"][0]["content"] == "用户要求始终用中文回答"
        assert callback_called["candidates"][0]["type"] == "preference"
        assert callback_called["candidates"][0]["content_hash"]  # hash was computed
        assert callback_called["new_offset"] == 2
    finally:
        os.unlink(path)


def test_run_extraction_no_llm_graceful():
    """Without LLM configured, callback is called with empty candidates."""
    from unittest.mock import patch
    from memento.transcript import run_extraction

    path = _make_transcript([_make_entry("user", "hello")])
    callback_called = {}

    def mock_callback(candidates, new_offset):
        callback_called["candidates"] = candidates
        callback_called["new_offset"] = new_offset

    try:
        with patch("memento.transcript.LLMClient") as MockLLMClass:
            MockLLMClass.from_env.return_value = None
            run_extraction(path, "test", 0, "", mock_callback)

        assert callback_called["candidates"] == []
        assert callback_called["new_offset"] == 1  # cursor still advances (nothing to retry)
    finally:
        os.unlink(path)


def test_run_extraction_llm_failure_no_callback():
    """LLM failure: callback NOT called, cursor NOT advanced."""
    from unittest.mock import patch, MagicMock
    from memento.transcript import run_extraction

    path = _make_transcript([_make_entry("user", "重要偏好")])
    callback_called = {"called": False}

    def mock_callback(candidates, new_offset):
        callback_called["called"] = True

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("LLM API error")

    try:
        with patch("memento.transcript.LLMClient") as MockLLMClass:
            MockLLMClass.from_env.return_value = mock_llm
            run_extraction(path, "test", 0, "", mock_callback)

        # Callback should NOT be called on LLM failure
        assert callback_called["called"] is False
    finally:
        os.unlink(path)


def test_run_extraction_empty_transcript():
    """Empty transcript (no new messages): callback called with empty candidates."""
    from memento.transcript import run_extraction

    path = _make_transcript([])
    callback_called = {}

    def mock_callback(candidates, new_offset):
        callback_called["candidates"] = candidates

    run_extraction(path, "test", 0, "", mock_callback)
    assert callback_called["candidates"] == []
    os.unlink(path)
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/test_transcript.py -v`
Expected: All PASS

- [ ] **Step 3: Run full project test suite for regressions**

Run: `cd /Users/maizi/data/work/memento && python -m pytest tests/ -v --timeout=60`
Expected: No regressions

---

## Verification Checklist

After all tasks, verify against spec acceptance criteria:

- [ ] Stop hook dispatches transcript extraction to Worker
- [ ] Worker reads transcript incrementally (cursor in runtime_cursors)
- [ ] Conversation with preferences/decisions → refined captures (<100 chars)
- [ ] Pure tool-use conversation → no captures
- [ ] 5-minute cooldown prevents duplicate extraction
- [ ] Existing memories not duplicated (content_hash dedup)
- [ ] All captures are origin=agent (trust model)
- [ ] Async execution — does not block conversation
- [ ] No LLM configured → graceful skip (cursor advances, no error)
- [ ] LLM/persist failure → cursor NOT advanced, allows retry
- [ ] Worker restart → cursor recovered from runtime_cursors, no re-scan
- [ ] Extraction failure → logged, does not crash flush-and-epoch
