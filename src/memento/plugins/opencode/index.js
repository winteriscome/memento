import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import os from "os";
import crypto from "crypto";
import http from "http";

// --- Memento Worker Socket Resolution (Mimics hook-handler.sh) ---
function getDbPath() {
  let dbPath = process.env.MEMENTO_DB;
  if (!dbPath) {
    const cfgPath = path.join(os.homedir(), ".memento", "config.json");
    if (fs.existsSync(cfgPath)) {
      try {
        const config = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
        dbPath = config?.database?.path;
      } catch (e) {
        // Ignore JSON parse errors
      }
    }
  }
  if (!dbPath) {
    dbPath = path.join(os.homedir(), ".memento", "default.db");
  } else {
    // Resolve ~ if present
    if (dbPath.startsWith("~/")) {
      dbPath = path.join(os.homedir(), dbPath.slice(2));
    } else {
      dbPath = path.resolve(dbPath);
    }
  }
  return dbPath;
}

function getSocketPath() {
  const dbPath = getDbPath();
  const absPath = path.resolve(dbPath);
  const hash = crypto.createHash("md5").update(absPath).digest("hex").slice(0, 12);
  return `/tmp/memento-worker-${hash}.sock`;
}

function ensureWorkerRunning() {
  const sockPath = getSocketPath();
  if (fs.existsSync(sockPath)) {
    // Basic ping to check if it's alive (we could use the GET /status here)
    return true;
  }
  
  // Background start
  const mementoPath = path.resolve(__dirname, "../../scripts/worker-service.py");
  const p = spawn("python3", [mementoPath], {
    detached: true,
    stdio: "ignore"
  });
  p.unref();
  return false;
}

function sendToWorker(method, requestPath, body = {}) {
  const sockPath = getSocketPath();
  const payload = JSON.stringify(body);
  
  return new Promise((resolve) => {
    const req = http.request({
      socketPath: sockPath,
      path: requestPath,
      method: method,
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload)
      }
    }, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch (e) {
          resolve({ status: res.statusCode, data: { raw: data } });
        }
      });
    });

    req.on("error", (e) => {
      resolve({ status: 500, error: e.message });
    });

    req.write(payload);
    req.end();
  });
}

export default async function opencodeMementoPlugin(input, options) {
  const { client, project, directory, worktree, serverUrl, $ } = input;
  
  // Try to ensure worker is ready on plugin load
  ensureWorkerRunning();

  return {
    "session.created": async (ctx, output) => {
      const sessionID = ctx.sessionID || output?.info?.id || "default";
      
      const res = await sendToWorker("POST", "/session/start", {
        claude_session_id: sessionID,
        project: project?.worktree || directory
      });
      
      // Auto-Priming Logic: Format memory into # $CMEM blocks and inject to TUI
      if (res.data?.priming_memories && res.data.priming_memories.length > 0) {
        const lines = ["# $CMEM memento: Priming contextual memories..."];
        res.data.priming_memories.forEach(m => {
          const t = m.type ? `[${m.type}]` : "[fact]";
          lines.push(`- ${t} ${m.content}`);
        });
        
        const primingText = lines.join("\n") + "\n";
        
        try {
          // OpenCode TUI event appending
          await client.post({
            url: "/tui/publish",
            body: {
              type: "tui.prompt.append",
              properties: {
                text: primingText
              }
            }
          });
        } catch (e) {
          // TUI publish failed or unsupported version
          console.error("Memento Auto-Priming Failed:", e.message);
        }
      }
    },

    "tool.execute.after": async (ctx, output) => {
      const sessionID = ctx.sessionID || "default";
      const tool = ctx.tool || "unknown";
      const args = ctx.args || {};
      
      let files = [];
      if (args.file_path) files.push(String(args.file_path));
      if (args.path) files.push(String(args.path));
      if (args.command) files.push(String(args.command));
      if (args.pattern) files.push(String(args.pattern));

      const toolResponse = output?.output ? String(output.output).slice(0, 200) : "";
      const summary = `${tool}: ${toolResponse}`;

      sendToWorker("POST", "/observe", {
        claude_session_id: sessionID,
        content: summary,
        tool: tool,
        files: files
      }).catch(() => {}); // Non-blocking
    },

    "session.updated": async (ctx) => {
      const sessionID = ctx.sessionID || "default";
      sendToWorker("POST", "/flush", {
        claude_session_id: sessionID
      }).catch(() => {});
    },

    "session.idle": async (ctx) => {
      const sessionID = ctx.sessionID || "default";
      
      // Flush first
      await sendToWorker("POST", "/flush", {
        claude_session_id: sessionID
      });
      
      // Check status to see if epoch is needed
      try {
        const statusRes = await sendToWorker("GET", "/status");
        if (statusRes.status === 200 && statusRes.data) {
          const d = statusRes.data;
          const pending = (d.pending_capture || 0) + (d.pending_delta || 0) + (d.pending_recon || 0);
          
          if (pending > 0) {
            let shouldEpoch = true;
            const lastStr = d.last_epoch_committed_at;
            if (lastStr) {
              const lastDate = new Date(lastStr.replace("Z", "+00:00"));
              const elapsed = (Date.now() - lastDate.getTime()) / 1000;
              if (elapsed < 300) shouldEpoch = false; // 5 minute cooldown
            }
            
            if (shouldEpoch) {
              // Run light epoch detached
              const p = spawn("python3", ["-m", "memento", "epoch", "run", "--mode", "light", "--trigger", "auto"], {
                detached: true,
                stdio: "ignore"
              });
              p.unref();
            }
          }
        }
      } catch (e) {
        // Ignore epoch errors on idle
      }
    },

    "session.deleted": async (ctx, payload) => {
      const sessionID = ctx.sessionID || payload?.info?.id || "default";
      await sendToWorker("POST", "/session/end", {
        claude_session_id: sessionID,
        outcome: "completed"
      });
      
      // Shutdown worker if no active sessions
      try {
        const statusRes = await sendToWorker("GET", "/status");
        if (statusRes.status === 200 && statusRes.data) {
          const activeIds = statusRes.data.active_session_ids || [];
          if (activeIds.length === 0) {
            await sendToWorker("POST", "/shutdown", {});
          }
        }
      } catch (e) {}
    }
  };
}
