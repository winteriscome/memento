"""LLM prompt templates for Epoch structuring and reconsolidation."""

from typing import Optional


VALID_TYPES = ["decision", "insight", "convention", "debugging", "preference", "fact"]


def build_structuring_prompt(items: list[dict]) -> Optional[str]:
    """Build prompt for Phase 2: L2→L3 structuring.

    Input: list of capture_log dicts with id, content, type, tags.
    Output: prompt string asking LLM to return JSON array of structured results.
    Returns None if items is empty.
    """
    if not items:
        return None

    items_text = "\n".join(
        f"- [{item['id']}] {item['content']}"
        for item in items
    )

    return f"""Analyze the following memory captures and return a JSON array.

For each item, determine:
1. "type": the most appropriate category from {VALID_TYPES}
2. "tags": a list of 2-5 short keyword tags (lowercase)
3. "content": the original content, optionally cleaned up for clarity (fix typos, normalize formatting, but preserve meaning). IMPORTANT: keep the SAME LANGUAGE as the original — do NOT translate.
4. "merge_with": if this item is a near-duplicate of another item in the list, set this to the other item's id; otherwise null

Input items:
{items_text}

Return ONLY a JSON array. Each element must have: "id" (original), "type", "tags", "content", "merge_with".
Example:
[
  {{"id": "c1", "type": "fact", "tags": ["redis", "cache", "ttl"], "content": "Redis needs TTL config for cache entries", "merge_with": null}},
  {{"id": "c2", "type": "preference", "tags": ["ui", "dark-mode"], "content": "User prefers dark mode", "merge_with": null}}
]"""


def build_reconsolidation_prompt(
    engram_content: str,
    engram_type: str,
    recon_contexts: list[str],
) -> Optional[str]:
    """Build prompt for Phase 5: reconsolidation.

    Input: engram content + list of query contexts from recon_buffer.
    Output: prompt asking LLM to refine the engram content based on new context.
    Returns None if recon_contexts is empty.
    """
    if not recon_contexts:
        return None

    contexts_text = "\n".join(f"- {ctx}" for ctx in recon_contexts)

    return f"""You are refining a stored memory based on new context from recent interactions.

Current memory ({engram_type}):
"{engram_content}"

New context from recent queries:
{contexts_text}

If the new context provides meaningful additional information, return an updated version of the memory.
If the memory is already accurate and complete, return it unchanged.
IMPORTANT: keep the SAME LANGUAGE as the original memory — do NOT translate.

Return ONLY a JSON object with:
- "content": the refined memory text (keep concise, under 200 characters)
- "changed": true if you modified the content, false if unchanged

Do not add information that isn't supported by the context. Do not change the meaning."""


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
