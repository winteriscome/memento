"""Tests for LLM prompt templates."""

from memento.prompts import build_structuring_prompt, build_reconsolidation_prompt


def test_structuring_prompt_contains_items():
    items = [
        {"id": "c1", "content": "Redis needs TTL config", "type": "fact", "tags": None},
        {"id": "c2", "content": "User prefers dark mode", "type": "fact", "tags": None},
    ]
    prompt = build_structuring_prompt(items)
    assert "Redis needs TTL config" in prompt
    assert "User prefers dark mode" in prompt
    assert "JSON" in prompt


def test_structuring_prompt_empty_items():
    prompt = build_structuring_prompt([])
    assert prompt is None


def test_reconsolidation_prompt_contains_engram_and_context():
    prompt = build_reconsolidation_prompt(
        engram_content="Redis cache config uses default TTL",
        engram_type="fact",
        recon_contexts=["User asked about Redis TTL settings", "Cache expiry discussed"],
    )
    assert "Redis cache config" in prompt
    assert "Redis TTL settings" in prompt
    assert "JSON" in prompt


def test_reconsolidation_prompt_no_contexts():
    prompt = build_reconsolidation_prompt(
        engram_content="Some memory",
        engram_type="fact",
        recon_contexts=[],
    )
    assert prompt is None
