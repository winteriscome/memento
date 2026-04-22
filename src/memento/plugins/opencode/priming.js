/**
 * OpenCode Priming Formatter
 *
 * Converts Memento priming memories into OpenCode system prompt text.
 *
 * OpenCode uses `experimental.chat.system.transform` to inject text into
 * the system prompt array. This formatter produces text blocks suitable for
 * that hook.
 *
 * Unlike Claude Code which injects memories via hook return values,
 * OpenCode requires explicit system prompt modification.
 */

/**
 * Format priming memories into OpenCode system prompt text.
 *
 * @param {Array<Record<string, unknown>>} memories
 *   Each item: { id, content, type, importance, score }
 * @returns {string} Formatted string ready for system prompt injection
 */
export function formatPriming(memories) {
  if (!memories || memories.length === 0) return "";

  // Group by type
  const layers = {
    preference: [],
    convention: [],
    decision: [],
    fact: [],
    insight: [],
  };

  for (const m of memories) {
    const type = m.type || "fact";
    const content = m.content || "";
    if (layers[type] && content) {
      layers[type].push(content);
    }
  }

  const sections = [];

  // L0: Identity (preference + convention)
  const l0Items = [...(layers.preference || []), ...(layers.convention || [])];
  if (l0Items.length > 0) {
    sections.push(
      `[Memento - Identity]\n${l0Items.map((item) => `- ${item}`).join("\n")}`,
    );
  }

  // L1: Core (decision + fact + insight)
  const l1Items = [...(layers.decision || []), ...(layers.fact || []), ...(layers.insight || [])];
  if (l1Items.length > 0) {
    sections.push(
      `[Memento - Core Memory]\n${l1Items.map((item) => `- ${item}`).join("\n")}`,
    );
  }

  if (sections.length === 0) return "";

  return [
    "# Memento — 跨会话长期记忆 (自动注入，不可修改)",
    ...sections,
    "",
  ].join("\n\n");
}

/**
 * Format a single priming memory for display in system prompt.
 * Useful for incremental injection.
 *
 * @param {Record<string, unknown>} memory
 * @returns {string|null}
 */
export function formatSingleMemory(memory) {
  const content = memory.content;
  const type = memory.type;
  if (!content) return null;
  return `[Memento/${type}] ${content}`;
}
