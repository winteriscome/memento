/**
 * Memento Bridge — runtime-agnostic Worker client for JavaScript environments.
 *
 * Communicates with the Memento Worker HTTP server over Unix Domain Socket.
 * Used by both Claude Code (via Bun shell) and OpenCode plugins.
 *
 * Session ID convention: Worker accepts either `external_session_id` (preferred)
 * or `claude_session_id` (backward compat). This bridge always uses the new name.
 *
 * Runtime: Requires Bun (used by OpenCode for plugin execution).
 *   - `$` from "bun" for shell commands
 *   - Bun's fetch() supports http://unix: socket URLs
 */

import crypto from "node:crypto";
import path from "node:path";
import { $ } from "bun";

/**
 * Compute the Worker socket path from database path.
 * @param {string} [dbPath] - Override database path
 * @returns {string}
 */
function socketPath(dbPath) {
  const db = dbPath || process.env.MEMENTO_DB || `${process.env.HOME}/.memento/default.db`;
  const hash = crypto.createHash("md5").update(path.resolve(db)).digest("hex").slice(0, 12);
  return `/tmp/memento-worker-${hash}.sock`;
}

/**
 * Send HTTP request to Worker over Unix Domain Socket.
 * @param {string} reqPath
 * @param {"GET"|"POST"} method
 * @param {Record<string, unknown>} [body]
 * @returns {Promise<Record<string, unknown>>}
 */
async function workerRequest(reqPath, method = "GET", body) {
  const sock = socketPath();

  try {
    // Bun's fetch supports http://unix:<socket><path>
    const url = `http://unix:${sock}${reqPath}`;
    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    return await resp.json();
  } catch {
    // Fallback: curl via Bun shell
    const bodyStr = body ? JSON.stringify(body) : "{}";
    const result = await $`curl -s -X ${method} --unix-socket ${sock} http://localhost${reqPath} -H 'Content-Type: application/json' -d ${bodyStr}`.quiet();
    const text = result.stdout.trim();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { error: text };
    }
  }
}

/**
 * Ensure Worker is running (spawn if needed).
 * @returns {Promise<boolean>}
 */
export async function ensureWorker() {
  const sock = socketPath();

  // Check if socket exists and is alive
  try {
    const result = await workerRequest("/status");
    if (result && !result.error) return true;
  } catch {
    // Worker not running, spawn it
  }

  // Clean stale socket
  try {
    await $`rm -f ${sock}`.quiet();
  } catch {
    // Socket doesn't exist, fine
  }

  // Start worker
  try {
    await $`nohup memento-worker > /dev/null 2>&1 &`.quiet();
  } catch (e) {
    console.error("[memento] Failed to start memento-worker:", e.message);
    return false;
  }

  // Wait for readiness (max 4s)
  for (let i = 0; i < 20; i++) {
    try {
      const result = await workerRequest("/status");
      if (result && !result.error) return true;
    } catch {
      // Not ready yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  return false;
}

/**
 * Start a Memento session, returns priming memories.
 * Maps to Worker POST /session/start.
 * @param {string} externalSessionId
 * @param {string} [project]
 * @param {string} [task]
 * @returns {Promise<{sessionId: string, primingMemories: Array<Record<string, unknown>>}>}
 */
export async function sessionStart(externalSessionId, project, task) {
  const result = await workerRequest("/session/start", "POST", {
    external_session_id: externalSessionId,
    project: project || process.cwd(),
    task,
  });

  return {
    sessionId: result.session_id || "",
    primingMemories: result.priming_memories || [],
  };
}

/**
 * End a Memento session.
 * Maps to Worker POST /session/end.
 * @param {string} externalSessionId
 * @param {string} [outcome]
 * @param {string} [summary]
 * @returns {Promise<Record<string, unknown>>}
 */
export async function sessionEnd(externalSessionId, outcome = "completed", summary) {
  return workerRequest("/session/end", "POST", {
    external_session_id: externalSessionId,
    outcome,
    summary,
  });
}

/**
 * Record an observation (tool use, file access, etc.).
 * Maps to Worker POST /observe (fire-and-forget).
 * @param {string} externalSessionId
 * @param {string} content
 * @param {string} [tool]
 * @param {string[]} [files]
 * @returns {Promise<void>}
 */
export async function observe(externalSessionId, content, tool, files) {
  workerRequest("/observe", "POST", {
    external_session_id: externalSessionId,
    content,
    tool,
    files,
  }).catch(() => {});
}

/**
 * Flush pending observations.
 * Maps to Worker POST /flush.
 * @returns {Promise<Record<string, unknown>>}
 */
export async function flush() {
  return workerRequest("/flush", "POST");
}

/**
 * Get Worker status including pending counts.
 * @returns {Promise<Record<string, unknown>>}
 */
export async function status() {
  return workerRequest("/status");
}

/**
 * Shutdown the Worker (graceful).
 * @returns {Promise<Record<string, unknown>>}
 */
export async function shutdownWorker() {
  return workerRequest("/shutdown", "POST");
}
