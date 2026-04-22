"""Transcript extraction tests."""
import json
import os
import tempfile
import pytest
from pathlib import Path


# ── Test helpers ──

def _make_transcript(entries: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for entry in entries:
        tmp.write(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp.close()
    return tmp.name


def _make_entry(role: str, content, **extra) -> dict:
    msg = {"role": role, "content": content}
    return {"message": msg, "type": "assistant" if role == "assistant" else "user", **extra}


# ── Prompt tests ──

def test_build_transcript_extraction_prompt_basic():
    from memento.prompts import build_transcript_extraction_prompt
    result = build_transcript_extraction_prompt(
        transcript="[user]: 以后都用中文回答\n\n[assistant]: 好的",
        existing_memories="- [preference] 用户偏好暗色主题",
    )
    assert "以后都用中文回答" in result
    assert "用户偏好暗色主题" in result
    assert "preference" in result
    assert "JSON" in result


def test_build_transcript_extraction_prompt_empty():
    from memento.prompts import build_transcript_extraction_prompt
    assert build_transcript_extraction_prompt("", "") is None
    assert build_transcript_extraction_prompt("   ", "") is None


# ── Read tests ──

def test_read_transcript_delta_basic():
    from memento.transcript import read_transcript_delta
    path = _make_transcript([
        _make_entry("user", "你好"),
        _make_entry("assistant", [{"type": "text", "text": "你好！"}]),
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


# ── Clean tests ──

def test_clean_transcript_strips_code_blocks():
    from memento.transcript import clean_transcript
    messages = [
        {"role": "user", "content": "帮我写个函数"},
        {"role": "assistant", "content": "好的：\n```python\ndef foo():\n    pass\n```\n这就是一个空函数。"},
    ]
    result = clean_transcript(messages)
    assert "def foo" not in result
    assert "空函数" in result


def test_clean_transcript_truncates_long():
    from memento.transcript import clean_transcript
    messages = [{"role": "user", "content": "x" * 2000}]
    result = clean_transcript(messages)
    assert len(result) < 1000


def test_clean_transcript_window_limit():
    from memento.transcript import clean_transcript
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    result = clean_transcript(messages, max_messages=4)
    assert "msg 19" in result
    assert "msg 0" not in result


# ── Parse LLM response tests ──

def test_parse_llm_response_valid():
    from memento.transcript import parse_llm_response
    raw = '[{"content": "用户偏好中文", "type": "preference", "importance": "critical"}]'
    result = parse_llm_response(raw)
    assert len(result) == 1
    assert result[0]["content"] == "用户偏好中文"


def test_parse_llm_response_with_markdown():
    from memento.transcript import parse_llm_response
    raw = '```json\n[{"content": "test", "type": "fact", "importance": "normal"}]\n```'
    result = parse_llm_response(raw)
    assert len(result) == 1


def test_parse_llm_response_empty():
    from memento.transcript import parse_llm_response
    assert parse_llm_response("[]") == []


def test_parse_llm_response_invalid():
    from memento.transcript import parse_llm_response
    assert parse_llm_response("not json") == []


def test_parse_llm_response_filters_invalid_types():
    from memento.transcript import parse_llm_response
    raw = json.dumps([
        {"content": "valid", "type": "fact", "importance": "normal"},
        {"content": "bad type", "type": "debugging", "importance": "normal"},
        {"content": "missing type"},
    ])
    result = parse_llm_response(raw)
    assert len(result) == 1
    assert result[0]["content"] == "valid"


# ── Content hash tests ──

def test_compute_content_hash():
    from memento.transcript import compute_content_hash
    h1 = compute_content_hash("Hello World")
    h2 = compute_content_hash("  hello world  ")
    assert h1 == h2


# ── Throttle tests ──

def test_should_extract_cooldown():
    from memento.transcript import should_extract, _last_extract_time
    _last_extract_time.clear()
    assert should_extract("test-session") is True
    assert should_extract("test-session") is False
    assert should_extract("other-session") is True


# ── run_extraction tests ──

def test_run_extraction_end_to_end():
    from unittest.mock import patch, MagicMock
    from memento.transcript import run_extraction

    path = _make_transcript([
        _make_entry("user", "以后回答问题都用中文"),
        _make_entry("assistant", [{"type": "text", "text": "好的"}]),
    ])
    mock_llm = MagicMock()
    mock_llm.generate.return_value = json.dumps([
        {"content": "用户要求始终用中文回答", "type": "preference", "importance": "critical"}
    ])
    callback_data = {}
    def cb(candidates, new_offset):
        callback_data["candidates"] = candidates
        callback_data["new_offset"] = new_offset

    try:
        with patch("memento.llm.LLMClient") as M:
            M.from_config.return_value = mock_llm
            run_extraction(path, "test", 0, "（暂无）", cb)
        assert len(callback_data["candidates"]) == 1
        assert callback_data["candidates"][0]["content"] == "用户要求始终用中文回答"
        assert callback_data["candidates"][0]["content_hash"]
        assert callback_data["new_offset"] == 2
    finally:
        os.unlink(path)


def test_run_extraction_no_llm():
    from unittest.mock import patch
    from memento.transcript import run_extraction

    path = _make_transcript([_make_entry("user", "hello")])
    callback_data = {}
    def cb(candidates, new_offset):
        callback_data["candidates"] = candidates
        callback_data["new_offset"] = new_offset

    try:
        with patch("memento.llm.LLMClient") as M:
            M.from_config.return_value = None
            run_extraction(path, "test", 0, "", cb)
        assert callback_data["candidates"] == []
        assert callback_data["new_offset"] == 1
    finally:
        os.unlink(path)


def test_run_extraction_llm_failure_no_callback():
    from unittest.mock import patch, MagicMock
    from memento.transcript import run_extraction

    path = _make_transcript([_make_entry("user", "重要偏好")])
    called = {"v": False}
    def cb(candidates, new_offset):
        called["v"] = True

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = Exception("LLM API error")

    try:
        with patch("memento.llm.LLMClient") as M:
            M.from_config.return_value = mock_llm
            run_extraction(path, "test", 0, "", cb)
        assert called["v"] is False  # callback NOT called on failure
    finally:
        os.unlink(path)
