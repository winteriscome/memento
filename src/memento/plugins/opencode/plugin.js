/**
 * Memento OpenCode Plugin
 *
 * Integrates Memento long-term memory with OpenCode's lifecycle:
 *
 * - session.created  → session start + recall priming memories
 * - session.updated  → mark dirty (no immediate flush)
 * - session.idle     → debounce flush + optional epoch trigger
 * - session.deleted  → final flush + session end
 * - tool.execute.after → observe tool usage
 * - experimental.chat.system.transform → inject priming memories
 *
 * Configuration (in opencode.json or .opencode.json):
 *   "plugin": [["memento", { "autoEpoch": true, "idleDebounceMs": 30000 }]]
 *
 * Requires: Bun runtime (used internally by OpenCode)
 */

import { normalizeEvent, normalizeToolAfter } from "./normalize.js";
import { formatPriming } from "./priming.js";
import {
  ensureWorker,
  sessionStart,
  sessionEnd,
  observe,
  flush,
  status,
  shutdownWorker,
} from "../shared/bridge.js";

// ── State ──

/** OpenCode sessionID → external session UUID for Memento */
const extSessionMap = new Map();
/** OpenCode sessionID → priming text cache */
const primingCache = new Map();
/** Debounce timers for idle flush, keyed by OpenCode sessionID */
const debounceTimers = new Map();

/** Default plugin options */
const DEFAULTS = {
  /** Debounce delay (ms) before flushing on session.idle */
  idleDebounceMs: 30_000,
  /** Whether to auto-trigger epoch on idle flush */
  autoEpoch: true,
  /** Max pending observations before forcing flush */
  maxObserveBuffer: 50,
};

// ── Helpers ──

/** Generate a UUID v4. */
function uuid4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Get or create an external session UUID for an OpenCode session. */
function getExtSessionId(opencodeSessionId) {
  let extId = extSessionMap.get(opencodeSessionId);
  if (!extId) {
    extId = uuid4();
    extSessionMap.set(opencodeSessionId, extId);
  }
  return extId;
}

/** Schedule a debounced flush for a session. */
function scheduleIdleFlush(sessionId, delayMs, onFlush) {
  const existing = debounceTimers.get(sessionId);
  if (existing) clearTimeout(existing);

  debounceTimers.set(
    sessionId,
    setTimeout(async () => {
      debounceTimers.delete(sessionId);
      try {
        await onFlush();
      } catch (e) {
        console.error(`[memento] idle flush error: ${e}`);
      }
    }, delayMs),
  );
}

// ── Plugin Entry ──

export const MementoPlugin = async (input, options = {}) => {
  const { client, project, directory, worktree, $, serverUrl } = input;
  const opts = { ...DEFAULTS, ...options };

  let workerReady = false;
  /** Per-session observe counters: OpenCode sessionID → count */
  const observeCounters = new Map();

  console.error("[memento] plugin initialized");

  /** Ensure worker is running on first meaningful event. */
  async function ensureWorkerReady() {
    if (!workerReady) {
      workerReady = await ensureWorker();
      if (!workerReady) {
        console.error("[memento] WARNING: Worker failed to start");
      }
    }
    return workerReady;
  }

  /** Increment observe counter for a session. */
  function bumpObserve(sessionId) {
    const c = (observeCounters.get(sessionId) || 0) + 1;
    observeCounters.set(sessionId, c);
    return c;
  }

  /** Reset observe counter for a session. */
  function resetObserve(sessionId) {
    observeCounters.delete(sessionId);
  }

  return {
    // ── Event listener (session lifecycle) ──

    event: async ({ event }) => {
      const normalized = normalizeEvent(event, directory);
      if (!normalized) return;

      try {
        switch (normalized.type) {
          case "session_start": {
            if (!(await ensureWorkerReady())) return;

            const ocSid = normalized.sessionId;
            // Each OpenCode session gets its own Memento external_session_id
            const extSid = getExtSessionId(ocSid);

            const result = await sessionStart(extSid, normalized.project, normalized.title);

            // Format and cache priming text keyed by OpenCode sessionID
            const primingText = formatPriming(result.primingMemories);
            if (primingText) {
              primingCache.set(ocSid, primingText);
              console.error(
                `[memento] priming: ${result.primingMemories.length} memories cached for session ${ocSid}`,
              );
            }
            break;
          }

          case "session_updated": {
            const ocSid = normalized.sessionId;
            // Mark dirty — don't flush immediately.
            // If observe buffer is full, force flush.
            const count = bumpObserve(ocSid);
            if (count >= opts.maxObserveBuffer) {
              await flush();
              resetObserve(ocSid);
            }
            break;
          }

          case "session_idle": {
            const ocSid = normalized.sessionId;
            // Debounce flush to avoid over-triggering
            scheduleIdleFlush(ocSid, opts.idleDebounceMs, async () => {
              if (!(await ensureWorkerReady())) return;
              await flush();
              resetObserve(ocSid);
              console.error("[memento] idle flush complete");

              // Optional: trigger light epoch if pending items exist
              if (opts.autoEpoch) {
                try {
                  const st = await status();
                  const pending =
                    (st.pending_capture || 0) +
                    (st.pending_delta || 0) +
                    (st.pending_recon || 0);
                  if (pending > 0) {
                    $`python3 -m memento epoch run --mode light --trigger auto`.catch(
                      () => {},
                    );
                    console.error(`[memento] epoch triggered: ${pending} pending`);
                  }
                } catch {
                  // Epoch check failed, skip
                }
              }
            });
            break;
          }

          case "session_end": {
            const ocSid = normalized.sessionId;
            // Cancel any pending idle flush
            const timer = debounceTimers.get(ocSid);
            if (timer) {
              clearTimeout(timer);
              debounceTimers.delete(ocSid);
            }

            if (await ensureWorkerReady()) {
              await flush();
              const extSid = extSessionMap.get(ocSid);
              if (extSid) {
                await sessionEnd(extSid, "completed");
              }
              console.error("[memento] session end: flushed and closed");

              // Cleanup cache and mappings
              primingCache.delete(ocSid);
              extSessionMap.delete(ocSid);
              resetObserve(ocSid);

              // If no active sessions, shutdown worker
              try {
                const st = await status();
                const activeSessions = st.active_sessions || 0;
                if (activeSessions === 0) {
                  await shutdownWorker();
                  console.error("[memento] worker shutdown (no active sessions)");
                }
              } catch {
                // Status check failed, skip
              }
            }
            break;
          }
        }
      } catch (e) {
        // Never crash the plugin
        console.error(`[memento] event handler error: ${e}`);
      }
    },

    // ── Tool observation ──

    "tool.execute.after": async (hookInput, hookOutput) => {
      const { tool, sessionID, callID, args } = hookInput;

      // Build observation content from tool output
      const output = hookOutput.output || "";
      const summary =
        typeof output === "string" ? output.slice(0, 500) : JSON.stringify(output).slice(0, 500);

      try {
        if (await ensureWorkerReady()) {
          // Use the external_session_id mapped from this OpenCode session
          const extSid = getExtSessionId(sessionID);
          observe(extSid, summary, tool, []);
          bumpObserve(sessionID);
        }
      } catch {
        // Observe is fire-and-forget, swallow errors
      }
    },

    // ── Priming injection via system prompt transform ──

    "experimental.chat.system.transform": async (hookInput, hookOutput) => {
      const sessionID = hookInput.sessionID;
      if (!sessionID) return;

      const primingText = primingCache.get(sessionID);
      if (primingText) {
        hookOutput.system.push(primingText);
      }
    },
  };
};
