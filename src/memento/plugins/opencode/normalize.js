/**
 * OpenCode Event Normalizer
 *
 * Converts OpenCode SDK events into Memento's unified internal event schema.
 * This layer isolates platform-specific event formats from the core bridge.
 *
 * OpenCode Event types (from @opencode-ai/sdk):
 *   - EventSessionCreated  → { type: "session_start", sessionId, project, directory }
 *   - EventSessionUpdated  → { type: "session_updated", sessionId, info }
 *   - EventSessionIdle     → { type: "session_idle", sessionId }
 *   - EventSessionDeleted  → { type: "session_end", sessionId, info }
 *   - tool.execute.after   → { type: "tool_after", sessionId, tool, args }
 */

/**
 * @typedef {Object} MementoEvent
 * @property {"session_start"|"session_updated"|"session_idle"|"session_end"|"tool_after"} type
 * @property {string} sessionId
 * @property {string} [project]
 * @property {string} [directory]
 * @property {string} [title]
 * @property {Record<string, unknown>} [info]
 * @property {string} [tool]
 * @property {Record<string, unknown>} [args]
 * @property {string} [callID]
 */

/**
 * Normalize an OpenCode Event to Memento's unified schema.
 * Returns null for events that Memento doesn't care about.
 *
 * @param {Object} event - OpenCode SDK event object
 * @param {string} directory - Current working directory
 * @returns {MementoEvent|null}
 */
export function normalizeEvent(event, directory) {
  const eventType = event.type;
  const props = event.properties || {};

  switch (eventType) {
    case "session.created": {
      const info = props.info || {};
      return {
        type: "session_start",
        sessionId: info.id || "",
        project: info.projectID || directory,
        directory: info.directory || directory,
        title: info.title,
      };
    }

    case "session.updated": {
      const info = props.info || {};
      return {
        type: "session_updated",
        sessionId: info.id || "",
        info,
      };
    }

    case "session.idle": {
      return {
        type: "session_idle",
        sessionId: props.sessionID || "",
      };
    }

    case "session.deleted": {
      const info = props.info || {};
      return {
        type: "session_end",
        sessionId: info.id || "",
        info,
      };
    }

    default:
      return null;
  }
}

/**
 * Normalize a tool.execute.after hook input to Memento event.
 * This is called from the `tool.execute.after` plugin hook, not from events.
 *
 * @param {string} tool
 * @param {string} sessionID
 * @param {string} callID
 * @param {Record<string, unknown>} args
 * @returns {MementoEvent}
 */
export function normalizeToolAfter(tool, sessionID, callID, args) {
  return {
    type: "tool_after",
    sessionId: sessionID,
    tool,
    args,
    callID,
  };
}
