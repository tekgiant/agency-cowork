#!/usr/bin/env node
// NOTE: This file intentionally uses CommonJS (require). The bridge runs as a
// standalone child process spawned by Electron, and node-pty + net require
// CommonJS. Do NOT convert to ESM imports.
/**
 * Agency PTY Bridge — Named-pipe server managing persistent Agency CLI PTY sessions.
 *
 * Protocol (NDJSON over named pipe):
 *   Commands (client → bridge):
 *     { cmd: "spawn",  sessionKey, resumeId?, cwd?, env? }
 *     { cmd: "write",  sessionKey, prompt }
 *     { cmd: "kill",   sessionKey }
 *     { cmd: "ping" }
 *     { cmd: "status" }
 *     { cmd: "shutdown" }
 *
 *   Events (bridge → client):
 *     { event: "ready",             sessionKey }
 *     { event: "turn_end",          sessionKey }
 *     { event: "assistant_message", sessionKey, content }
 *     { event: "pty_data",          sessionKey, data }
 *     { event: "exit",              sessionKey, exitCode }
 *     { event: "error",             sessionKey?, message }
 *     { event: "pong" }
 *     { event: "status",            sessions: [...] }
 *     { event: "spawned",           sessionKey }
 *
 *   Client identification (on connect):
 *     { type: "ui" }       — receives pty_data events (terminal rendering)
 *     { type: "monitor" }  — receives all events except pty_data (lighter)
 *
 * Named pipe: \\.\pipe\agency-pty-bridge  (Windows)
 *             /tmp/agency-pty-bridge.sock  (macOS/Linux)
 */

"use strict";

const net = require("net");
const http = require("http");
const { execSync } = require("child_process");
const { EventEmitter } = require("events");
const fs = require("fs");
const path = require("path");
const os = require("os");

// ── Bridge Debug API (HTTP on port 9877) ────────────────────────────────────
// Only enabled when BRIDGE_DEBUG=1 env var is set (dev/troubleshooting only)
const BRIDGE_DEBUG_PORT = 9877;
const BRIDGE_RING_SIZE = 2000;
const bridgeRingBuffer = [];  // { ts, sessionKey, dir, data, clean }

function pushBridgeRing(sessionKey, dir, data, clean) {
  bridgeRingBuffer.push({ ts: Date.now(), sessionKey, dir, data: (data || "").slice(0, 500), clean: (clean || "").slice(0, 500) });
  if (bridgeRingBuffer.length > BRIDGE_RING_SIZE) bridgeRingBuffer.shift();
}

if (process.env.BRIDGE_DEBUG === "1") {
const debugServer = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${BRIDGE_DEBUG_PORT}`);
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Access-Control-Allow-Origin", "*");

  // GET /state — all session states
  if (req.method === "GET" && url.pathname === "/state") {
    const metas = {};
    for (const [key, m] of sessions) {
      metas[key] = {
        ready: m.ready, busy: m.busy, sessionId: m.sessionId,
        procAlive: !!m.proc, pid: m.proc?.pid,
        _isLoading: m._isLoading, _autopilotVerified: m._autopilotVerified,
        _promptAcked: m._promptAcked, _promptRetries: m._promptRetries,
        _lastMcpOutputAt: m._lastMcpOutputAt ? `${Date.now() - m._lastMcpOutputAt}ms ago` : null,
        _mcpDeferredAt: m._mcpDeferredAt ? `${Date.now() - m._mcpDeferredAt}ms ago` : null,
      };
    }
    res.end(JSON.stringify({ sessions: metas, clients: clients.size, registry: sessionRegistry }, null, 2));
    return;
  }

  // GET /buffer?last=N&dir=in|out — ring buffer
  if (req.method === "GET" && url.pathname === "/buffer") {
    const last = Math.min(parseInt(url.searchParams.get("last") || "200"), BRIDGE_RING_SIZE);
    const dirFilter = url.searchParams.get("dir");
    const keyFilter = url.searchParams.get("session");
    let items = bridgeRingBuffer.slice(-last);
    if (dirFilter) items = items.filter(i => i.dir === dirFilter);
    if (keyFilter) items = items.filter(i => i.sessionKey === keyFilter);
    res.end(JSON.stringify(items, null, 2));
    return;
  }

  // GET /buffer/tail?n=50 — compact text format
  if (req.method === "GET" && url.pathname === "/buffer/tail") {
    const n = Math.min(parseInt(url.searchParams.get("n") || "50"), 500);
    const items = bridgeRingBuffer.slice(-n);
    const lines = items.map(i => {
      const t = new Date(i.ts).toISOString().slice(11, 23);
      const arrow = i.dir === "in" ? ">>>" : "<<<";
      const text = i.dir === "in" ? i.data : i.clean;
      return `${t} ${arrow} [${i.sessionKey}] ${text.replace(/\n/g, "\\n")}`;
    });
    res.setHeader("Content-Type", "text/plain");
    res.end(lines.join("\n"));
    return;
  }

  // POST /write — write raw text to a session PTY { sessionKey, text }
  if (req.method === "POST" && url.pathname === "/write") {
    let body = "";
    req.on("data", c => body += c);
    req.on("end", () => {
      try {
        const { sessionKey, text } = JSON.parse(body);
        const meta = sessionKey ? sessions.get(sessionKey) : [...sessions.values()][0];
        if (!meta?.proc) { res.statusCode = 404; res.end(JSON.stringify({ error: "no session" })); return; }
        const resolved = text.replace(/\\r/g, "\r").replace(/\\n/g, "\n")
          .replace(/\\x1b/g, "\x1b").replace(/\\t/g, "\t");
        meta.proc.write(resolved);
        pushBridgeRing(meta.sessionKey, "in", `[debug-write] ${text}`, text);
        res.end(JSON.stringify({ ok: true, wrote: text, pid: meta.proc.pid }));
      } catch (e) { res.statusCode = 400; res.end(JSON.stringify({ error: e.message })); }
    });
    return;
  }

  // POST /autopilot — retry autopilot switch for a session { sessionKey? }
  if (req.method === "POST" && url.pathname === "/autopilot") {
    let body = "";
    req.on("data", c => body += c);
    req.on("end", () => {
      try {
        const { sessionKey } = JSON.parse(body || "{}");
        const meta = sessionKey ? sessions.get(sessionKey) : [...sessions.values()][0];
        if (!meta?.proc) { res.statusCode = 404; res.end(JSON.stringify({ error: "no session" })); return; }
        switchToAutopilot(meta, "debug-api");
        res.end(JSON.stringify({ ok: true, sessionKey: meta.sessionKey }));
      } catch (e) { res.statusCode = 400; res.end(JSON.stringify({ error: e.message })); }
    });
    return;
  }

  res.statusCode = 404;
  res.end(JSON.stringify({
    endpoints: [
      "GET  /state",
      "GET  /buffer?last=200&dir=in|out&session=key",
      "GET  /buffer/tail?n=50",
      "POST /write       {sessionKey?, text}",
      "POST /autopilot   {sessionKey?}",
    ]
  }));
});

debugServer.listen(BRIDGE_DEBUG_PORT, "127.0.0.1", () => {
  console.log(`[debug] Bridge debug API listening on http://127.0.0.1:${BRIDGE_DEBUG_PORT}`);
});
debugServer.on("error", (e) => {
  console.warn(`[debug] Bridge debug API failed to start: ${e.message}`);
});
} // end BRIDGE_DEBUG gate
// ─────────────────────────────────────────────────────────────────────────────

// ── PTY Import ──────────────────────────────────────────────────────────────
let pty;
if (globalThis.__AGENCY_SHARED_PTY) {
  pty = globalThis.__AGENCY_SHARED_PTY;
} else try {
  pty = require("@homebridge/node-pty-prebuilt-multiarch");
} catch {
  // Fallback 1: packaged Electron app resources (app.asar.unpacked)
  const packagedNodeModules = process.resourcesPath
    ? path.join(process.resourcesPath, "app.asar.unpacked", "node_modules", "@homebridge", "node-pty-prebuilt-multiarch")
    : null;
  // Fallback 2: try the Electron app's node_modules (dev mode)
  const uiNodeModules = path.resolve(__dirname, "..", "..", "..", "..", "..", "ui", "node_modules", "@homebridge", "node-pty-prebuilt-multiarch");
  // Fallback 3: try the prebuilds directory from the Electron app
  const prebuildDir = path.resolve(__dirname, "..", "..", "..", "..", "..", "ui", "prebuilds");
  if (packagedNodeModules && fs.existsSync(path.join(packagedNodeModules, "package.json"))) {
    pty = require(packagedNodeModules);
  } else if (fs.existsSync(uiNodeModules)) {
    pty = require(uiNodeModules);
  } else if (fs.existsSync(prebuildDir)) {
    process.env.NODE_PTY_PREBUILD_PATH = prebuildDir;
    pty = require("@homebridge/node-pty-prebuilt-multiarch");
  } else {
    console.error("FATAL: node-pty not found. Run 'npm install' in pty-bridge/ or build the Electron app.");
    process.exit(1);
  }
}

// ── Constants ───────────────────────────────────────────────────────────────
const IS_WIN = process.platform === "win32";
const PIPE_PATH = IS_WIN
  ? "\\\\.\\pipe\\agency-pty-bridge"
  : "/tmp/agency-pty-bridge.sock";

const SESSION_STATE_DIR = path.join(os.homedir(), ".copilot", "session-state");

// ── Persistent Session Registry ─────────────────────────────────────────────
// Maps sessionKey → sessionId across restarts so CLI sessions are resumed
// rather than created fresh each time.
const REGISTRY_DIR = path.join(os.homedir(), ".agency-cowork");
const REGISTRY_FILE = path.join(REGISTRY_DIR, "session-registry.json");
const bridgeEvents = new EventEmitter();

/** @type {Object<string, string>} sessionKey → sessionId */
let sessionRegistry = {};
let registryLoaded = false;
let bridgeStarted = false;
let shuttingDown = false;
let bridgeShouldExitProcess = true;

function loadRegistry() {
  registryLoaded = true;
  try {
    if (fs.existsSync(REGISTRY_FILE)) {
      sessionRegistry = JSON.parse(fs.readFileSync(REGISTRY_FILE, "utf8"));
      log("info", `Session registry loaded: ${Object.keys(sessionRegistry).length} entries`);
    }
  } catch (err) {
    log("warn", `Failed to load session registry: ${err.message}`);
    sessionRegistry = {};
  }
}

function saveRegistry() {
  try {
    if (!fs.existsSync(REGISTRY_DIR)) fs.mkdirSync(REGISTRY_DIR, { recursive: true });
    fs.writeFileSync(REGISTRY_FILE, JSON.stringify(sessionRegistry, null, 2));
  } catch (err) {
    log("warn", `Failed to save session registry: ${err.message}`);
  }
}

function registrySet(sessionKey, sessionId) {
  if (sessionRegistry[sessionKey] !== sessionId) {
    sessionRegistry[sessionKey] = sessionId;
    saveRegistry();
    log("info", `Registry: ${sessionKey} → ${sessionId}`);
  }
}

// Regex patterns ported from ui/electron/main.js
const LOADED_RE = /Environment loaded:/i;
const LOADING_RE = /Loading environment:/i;
const FALLBACK_READY_RE = /Describe a task to get started\.|Type @|Type \/|^[❯›]\s/im;
const CLI_PROMPT_RE = /[❯›>$%]\s*(Type @|Type \/|$)|waiting for (your )?input|Enter your (message|prompt|response)/i;
const READY_FOOTER_RE = /shift\+tab switch mode|Unlimited reqs\.|Research Preview/i;
const TRUST_DIALOG_RE = /not trusted|Confirm folder trust|Do you trust the files/i;
const SESSION_STORAGE_RE = /Session storage|Choose where your Copilot sessions are stored/i;
const MCP_AUTH_EXPIRED_RE = /AADSTS500133|AADSTS9010010|Assertion is not within its valid time range/i;
const MCP_WARN_RE = /MCP (server|client)|still connecting|Connecting to MCP|Failed to connect|Unable to connect/i;
const ANSI_RE = /\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b[()][AB012]|\x1b\[[\?]?[0-9;]*[hlm]|\r/g;
// Autopilot mode indicator in Copilot CLI TUI footer
const AUTOPILOT_RE = /autopilot/i;
const MODE_INDICATOR_RE = /autopilot|plan mode|default mode|shift\+tab/i;
const YOLO_CONFIRMED_RE = /yolo mode|all permissions granted|permissions enabled/i;

// Global yolo mode flag — set by UI via pipe command
// Initialize from env vars passed by Electron at bridge spawn time (avoids race with pipe commands)
let yoloMode = process.env.BRIDGE_YOLO === "1";
let autopilotMode = process.env.BRIDGE_AUTOPILOT !== "0"; // default: on
let autoApprovePermissions = process.env.BRIDGE_AUTO_APPROVE !== "0"; // default: on
let smartPermissionMode = process.env.BRIDGE_SMART_PERMISSION === "1"; // smart-permission plugin handles permissions (mutually exclusive with yolo)

// Timing constants (ms) — increase if TUI renders slowly on resource-constrained machines
const PERM_DIALOG_DELAY_MS = parseInt(process.env.BRIDGE_PERM_DELAY, 10) || 1200;
const TEXT_PASTE_DELAY_MS = 500;
const READY_DETECT_INTERVAL_MS = 200;
const INIT_ENTER_DELAY_MS = 300;

function stripAnsi(str) {
  return str.replace(ANSI_RE, "");
}

// ── CLI Binary Resolution ───────────────────────────────────────────────────
const CLI_CACHE_FILE = path.join(os.homedir(), ".agency-cowork", "cli-path.json");

function resolveCliBinary() {
  // 1. Try cached path from Electron UI (userOverride takes priority)
  try {
    if (fs.existsSync(CLI_CACHE_FILE)) {
      const cached = JSON.parse(fs.readFileSync(CLI_CACHE_FILE, "utf8"));
      const override = cached.userOverride;
      if (override && fs.existsSync(override)) return override;
      const cachedPath = cached.resolvedPath || cached.path;
      if (cachedPath && fs.existsSync(cachedPath)) return cachedPath;
    }
  } catch {}

  // 2. Try well-known locations
  const candidates = IS_WIN
    ? [
        path.join(os.homedir(), "AppData", "Roaming", "agency", "CurrentVersion", "agency.exe"),
        path.join(os.homedir(), "AppData", "Local", "Programs", "agency", "agency.exe"),
        path.join(os.homedir(), "AppData", "Local", "Microsoft", "WinGet", "Links", "agency.exe"),
        path.join(os.homedir(), ".cargo", "bin", "agency.exe"),
      ]
    : [
        path.join(os.homedir(), ".config", "agency", "CurrentVersion", "agency"),
        "/usr/local/bin/agency",
        path.join(os.homedir(), ".cargo", "bin", "agency"),
        path.join(os.homedir(), ".local", "bin", "agency"),
      ];

  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }

  // 3. Fallback: assume it's on PATH
  return IS_WIN ? "agency.exe" : "agency";
}

// ── Logging ─────────────────────────────────────────────────────────────────
const LOG_DIR = path.join(os.homedir(), ".agency-cowork", "logs");
if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
const logStream = fs.createWriteStream(path.join(LOG_DIR, "pty-bridge.log"), { flags: "a" });

function log(level, msg, ...args) {
  const ts = new Date().toISOString();
  const text = `[${ts}] ${level.toUpperCase().padEnd(5)} | ${msg}` +
    (args.length ? " " + args.map(a => typeof a === "object" ? JSON.stringify(a) : a).join(" ") : "");
  logStream.write(text + "\n");
  if (level === "error") console.error(text);
}

// ── Session Manager ─────────────────────────────────────────────────────────
/** @type {Map<string, SessionMeta>} */
const sessions = new Map();
// Dynamic terminal size from the UI (updated via "resize" command)
let bridge_cols = 120;
let bridge_rows = 40;

/**
 * @typedef {Object} SessionMeta
 * @property {import('@homebridge/node-pty-prebuilt-multiarch').IPty} proc
 * @property {string} sessionKey
 * @property {string|null} sessionId - Copilot session ID (from session-state dir)
 * @property {boolean} ready - TUI is ready for input
 * @property {boolean} busy - Currently processing a prompt
 * @property {NodeJS.Timeout|null} jsonlInterval
 * @property {number} jsonlBytesRead
 * @property {string} jsonlPendingLine
 * @property {string[]} messageAccumulator - Current turn's assistant messages
 * @property {NodeJS.Timeout|null} idleTimer
 * @property {boolean} [_autopilotVerified] - True once autopilot mode confirmed in PTY output
 * @property {number} [_autopilotAttempts] - Number of Shift+Tab switch attempts
 */

/**
 * Switch a session to autopilot mode by sending Shift+Tab keypresses.
 * Sends focus-in first (ESC[I) to ensure TUI accepts input, then 2x Shift+Tab.
 * After sending, monitors PTY output for "autopilot" indicator and retries if needed.
 */
function switchToAutopilot(meta, source = "auto") {
  if (!meta.proc) return;
  meta._autopilotAttempts = (meta._autopilotAttempts || 0) + 1;
  const attempt = meta._autopilotAttempts;

  log("info", `Session ${meta.sessionKey}: autopilot switch attempt #${attempt} (source: ${source})`);
  pushBridgeRing(meta.sessionKey, "in", `[autopilot-switch] attempt #${attempt} source=${source}`, "");

  // Send focus-in first to ensure TUI accepts keyboard input
  meta.proc.write("\x1b[I");

  setTimeout(() => {
    if (!meta.proc) return;
    log("info", `Session ${meta.sessionKey}: sending Shift+Tab #1`);
    pushBridgeRing(meta.sessionKey, "in", "[shift-tab-1] \\x1b[Z", "Shift+Tab #1");
    meta.proc.write("\x1b[Z"); // Shift+Tab: default → plan

    setTimeout(() => {
      if (!meta.proc) return;
      log("info", `Session ${meta.sessionKey}: sending Shift+Tab #2`);
      pushBridgeRing(meta.sessionKey, "in", "[shift-tab-2] \\x1b[Z", "Shift+Tab #2");
      meta.proc.write("\x1b[Z"); // Shift+Tab: plan → autopilot

      // --allow-all only works with -p (non-interactive mode).
      // In PTY mode the permission dialog always appears — auto-answer it.
      setTimeout(() => {
        if (!meta.proc || meta._autopilotVerified) return;
        if (autoApprovePermissions) {
          log("info", `Session ${meta.sessionKey}: sending Enter to accept autopilot permissions (option 1)`);
          pushBridgeRing(meta.sessionKey, "in", "[autopilot-accept] Enter", "accept permission dialog");
          meta.proc.write("\x1b[I"); // focus-in
          meta.proc.write("\r");     // Enter — accepts option 1
        } else {
          log("info", `Session ${meta.sessionKey}: selecting limited permissions (option 2)`);
          pushBridgeRing(meta.sessionKey, "in", "[autopilot-limited] Down+Enter", "limited permissions");
          meta.proc.write("\x1b[I"); // focus-in
          meta.proc.write("\x1b[B"); // down arrow — move to option 2
          setTimeout(() => {
            if (!meta.proc) return;
            meta.proc.write("\x1b[I");
            meta.proc.write("\r");
          }, 200);
        }
        meta._autopilotPermissionAnswered = true;
      }, PERM_DIALOG_DELAY_MS);

      // Verify after a delay
      setTimeout(() => {
        if (meta._autopilotVerified) {
          log("info", `Session ${meta.sessionKey}: autopilot VERIFIED after attempt #${attempt}`);
          return;
        }
        if (attempt < 3) {
          log("warn", `Session ${meta.sessionKey}: autopilot NOT verified after attempt #${attempt}, retrying...`);
          switchToAutopilot(meta, "retry");
        } else {
          log("error", `Session ${meta.sessionKey}: autopilot NOT verified after ${attempt} attempts — giving up`);
        }
      }, 2000);
    }, 300);
  }, 150);
}

function spawnSession(sessionKey, { resumeId, cwd, env } = {}) {
  const existing = sessions.get(sessionKey);
  if (existing) {
    // If existing session is still alive, reuse it — don't kill a booting session
    if (existing.proc && !existing.proc._exited) {
      log("info", `Session ${sessionKey} already exists — reusing (ready=${existing.ready})`);
      // Re-emit current state so the new caller gets the right events
      broadcastToAll({ event: "spawned", sessionKey });
      if (existing.ready) {
        broadcastToAll({ event: "ready", sessionKey });
      }
      return;
    }
    log("warn", `Session ${sessionKey} exists but proc is dead — replacing`);
    killSession(sessionKey);
  }

  // Auto-resume from registry if no explicit resumeId provided
  if (!resumeId && sessionRegistry[sessionKey]) {
    resumeId = sessionRegistry[sessionKey];
    log("info", `Session ${sessionKey}: resuming from registry → ${resumeId}`);
  }

  const cliBinary = resolveCliBinary();

  // In packaged Electron apps, process.cwd() returns "/" — use default-folder.json as fallback
  let workDir = cwd;
  if (!workDir) {
    try {
      const dfPath = path.join(os.homedir(), ".agency-cowork", "default-folder.json");
      const df = JSON.parse(fs.readFileSync(dfPath, "utf8"));
      if (df.workDir) workDir = df.workDir;
    } catch { /* ignore */ }
  }
  if (!workDir) workDir = process.cwd();
  const args = ["copilot"];
  // --allow-all only works with -p (non-interactive); harmless in PTY mode.
  if (yoloMode) args.push("--allow-all");
  if (resumeId) args.push(`--resume=${resumeId}`);

  log("info", `Spawning session ${sessionKey}: ${cliBinary} ${args.join(" ")} cwd=${workDir}`);

  const ptyProc = pty.spawn(cliBinary, args, {
    name: "xterm-256color",
    cols: bridge_cols,
    rows: bridge_rows,
    cwd: workDir,
    env: { ...(env || process.env), MSFT_AGENCY: "true" },
    // Use WinPTY on Windows — ConPTY's helper process (conpty_console_list_agent.js)
    // fails with "AttachConsole failed" when the bridge runs as a child of Electron.
    useConpty: process.platform !== "win32" ? undefined : false,
  });

  /** @type {SessionMeta} */
  const meta = {
    proc: ptyProc,
    sessionKey,
    sessionId: resumeId || null,
    ready: false,
    busy: false,
    jsonlInterval: null,
    jsonlBytesRead: 0,
    jsonlPendingLine: "",
    messageAccumulator: [],
    lastTurnContent: "",
    idleTimer: null,
    _detectRunning: false,
    _isLoading: false,
    spawnedAt: Date.now(),
    _autopilotVerified: false,
    _autopilotAttempts: 0,
    _autopilotPermissionAnswered: false,
    _yoloSent: false,
    // Prompt delivery tracking (ACK gate + retry)
    _pendingPrompt: null,
    _promptAcked: false,
    _promptRetries: 0,
    _promptAckTimer: null,
    // MCP init settle guard
    _lastMcpOutputAt: null,
    _mcpDeferredAt: null,
  };

  sessions.set(sessionKey, meta);

  // ── PTY output handler ──────────────────────────────────────────────────
  let readyDetected = false;
  let trustDialogSent = false;
  let sessionStorageSent = false;

  ptyProc.onData((data) => {
    // Forward raw PTY data to UI clients
    broadcastToUi({ event: "pty_data", sessionKey, data });

    const clean = stripAnsi(data);

    // Log to debug ring buffer
    pushBridgeRing(sessionKey, "out", data.slice(0, 300), clean.slice(0, 300));

    // Autopilot permission dialog — "Enable autopilot mode" with numbered options
    // Detect various forms of the permission prompt text
    if (!meta._autopilotPermissionAnswered &&
        (/Enable all permissions|enable permissions|all permissions/i.test(clean) ||
         /1\.\s*Enable all/i.test(clean))) {
      if (autoApprovePermissions) {
        meta._autopilotPermissionAnswered = true;
        meta._autopilotVerified = true; // Permission dialog implies autopilot mode is being activated
        log("info", `Session ${sessionKey}: detected autopilot permission dialog — auto-selecting option 1 (Enable all)`);
        pushBridgeRing(sessionKey, "in", "[autopilot-permission] auto-select 1", "");
        setTimeout(() => {
          if (!meta.proc) return;
          meta.proc.write("\x1b[I"); // focus-in
          meta.proc.write("\r");     // Enter to confirm option 1 (already selected with ›)
        }, 300);
        return; // Don't process further — wait for dialog to dismiss
      } else {
        meta._autopilotPermissionAnswered = true;
        meta._autopilotVerified = true;
        log("info", `Session ${sessionKey}: detected autopilot permission dialog — auto-selecting option 2 (limited permissions)`);
        pushBridgeRing(sessionKey, "in", "[autopilot-permission] auto-select 2", "limited permissions");
        setTimeout(() => {
          if (!meta.proc) return;
          meta.proc.write("\x1b[I"); // focus-in
          meta.proc.write("\x1b[B"); // down arrow — move to option 2
          setTimeout(() => {
            if (!meta.proc) return;
            meta.proc.write("\x1b[I"); // focus-in
            meta.proc.write("\r");     // Enter to confirm option 2
          }, 200);
        }, 300);
        return;
      }
    }

    // Autopilot mode verification — detect "autopilot" in TUI footer AFTER permission is handled
    // Also accept if permission wasn't needed (no dialog shown)
    if (!meta._autopilotVerified && AUTOPILOT_RE.test(clean) &&
        !/Enable autopilot mode/i.test(clean)) {
      // Only match footer indicator, not the dialog title
      meta._autopilotVerified = true;
      meta._autopilotPermissionAnswered = true;
      log("info", `Session ${sessionKey}: AUTOPILOT MODE CONFIRMED in PTY output`);
      pushBridgeRing(sessionKey, "out", "[autopilot-confirmed]", "autopilot mode detected in output");
    }

    // Send /yolo after autopilot mode is confirmed (regardless of permission dialog).
    // /yolo suppresses all confirmation prompts — distinct from the permissions dialog
    // which only grants base tool permissions.
    // Skip when smart-permission mode is active — the plugin hook handles permissions instead.
    if (meta._autopilotVerified && yoloMode && !smartPermissionMode && !meta._yoloSent) {
      meta._yoloSent = true;
      const afterPermDialog = meta._autopilotPermissionAnswered;
      setTimeout(() => {
        if (!meta.proc) return;
        log("info", `Session ${sessionKey}: sending /yolo (yolo mode enabled${afterPermDialog ? ', after permission dialog' : ''})`);
        pushBridgeRing(sessionKey, "in", "[yolo] /yolo\\r", "/yolo command");
        meta.proc.write("\x1b[I");  // focus-in
        meta.proc.write("\x15");    // Ctrl+U clear line
        meta.proc.write(`\x1b[200~/yolo\x1b[201~`); // bracketed paste
        setTimeout(() => {
          if (meta.proc) {
            meta.proc.write("\x1b[I"); // re-focus before Enter
            meta.proc.write("\r");
          }
        }, 500);
      }, afterPermDialog ? 1500 : 500);
    }

    // Trust dialog auto-answer
    if (!trustDialogSent && TRUST_DIALOG_RE.test(clean)) {
      trustDialogSent = true;
      setTimeout(() => {
        if (meta.proc) {
          meta.proc.write("\x1b[I"); // Focus-in
          meta.proc.write("2");
          setTimeout(() => { if (meta.proc) { meta.proc.write("\x1b[I"); meta.proc.write("\r"); } }, 100);
        }
      }, 500);
      log("info", `Session ${sessionKey}: auto-answered trust dialog`);
      return;
    }

    // Session storage prompt auto-answer — select option 1 "Keep on this device only"
    // Right arrow expands scope from "this session" to "this workspace" before confirming.
    if (!sessionStorageSent && SESSION_STORAGE_RE.test(clean)) {
      sessionStorageSent = true;
      setTimeout(() => {
        if (meta.proc) {
          meta.proc.write("\x1b[I"); // Focus-in
          meta.proc.write("\x1b[C"); // Right arrow — apply to workspace, not just this session
          setTimeout(() => {
            if (meta.proc) {
              meta.proc.write("\x1b[I"); // Focus-in
              meta.proc.write("\r");     // Enter to confirm
            }
          }, 200);
        }
      }, 500);
      log("info", `Session ${sessionKey}: auto-answered session storage dialog (option 1: local, workspace scope)`);
      return;
    }

    // MCP auth expiry
    if (MCP_AUTH_EXPIRED_RE.test(clean)) {
      broadcastToAll({ event: "error", sessionKey, message: "MCP auth expired" });
      log("warn", `Session ${sessionKey}: MCP auth expired`);
    }

    // MCP init settle guard — track the last time MCP connection warnings appeared.
    // writeToPty checks this to defer prompt delivery until the CLI has settled.
    if (readyDetected && MCP_WARN_RE.test(clean)) {
      meta._lastMcpOutputAt = Date.now();
    }

    // Ready detection — only trust "Environment loaded:" during MCP bootstrap.
    // Resumed sessions can skip that line and land directly on the prompt/footer,
    // so after a short grace period accept the real CLI prompt as ready too.
    if (!readyDetected) {
      if (LOADING_RE.test(clean)) meta._isLoading = true;
      const isLoaded = LOADED_RE.test(clean);
      const elapsedMs = Date.now() - meta.spawnedAt;
      const hasPromptHint = CLI_PROMPT_RE.test(clean) || READY_FOOTER_RE.test(clean);
      const isFallback = (!meta._isLoading && FALLBACK_READY_RE.test(clean)) ||
        (elapsedMs >= 5000 && hasPromptHint);
      if (isLoaded || isFallback) {
        readyDetected = true;
        meta.ready = true;
        meta._isLoading = false;
        broadcastToAll({ event: "ready", sessionKey });
        log("info", `Session ${sessionKey}: ready (${isLoaded ? "loaded" : "fallback"})`);

        // Switch to autopilot mode with verification & retry (if enabled)
        if (autopilotMode) {
          setTimeout(() => switchToAutopilot(meta, "ready"), 500);
        } else {
          log("info", `Session ${sessionKey}: autopilot mode DISABLED — staying in default mode`);
        }
        // Start JSONL watcher if we have a session ID
        if (meta.sessionId) {
          registrySet(sessionKey, meta.sessionId);
          startJsonlWatcher(meta);
        } else {
          detectSessionId(meta);
        }
      }
    }
  });

  ptyProc.onExit(({ exitCode }) => {
    log("info", `Session ${sessionKey}: exited (code=${exitCode})`);
    meta.proc._exited = true;
    if (meta.jsonlInterval) clearInterval(meta.jsonlInterval);
    if (meta.idleTimer) clearTimeout(meta.idleTimer);
    if (meta._promptAckTimer) { clearTimeout(meta._promptAckTimer); meta._promptAckTimer = null; }
    sessions.delete(sessionKey);
    broadcastToAll({ event: "exit", sessionKey, exitCode });
  });

  // Session ID detection for new sessions (not --resume)
  if (!resumeId) {
    detectSessionId(meta);
  }

  return meta;
}

function detectSessionId(meta) {
  // Prevent concurrent detection loops for the same session
  if (meta._detectRunning) return;
  if (meta.sessionId) return; // already known
  meta._detectRunning = true;

  const spawnTime = Date.now();
  let attempts = 0;
  // Poll for up to 120 attempts (60 seconds). If it times out, writeToPty
  // will retry detection on-demand so no prompt is silently lost.
  const maxAttempts = 120;
  const interval = setInterval(() => {
    attempts++;
    try {
      if (!fs.existsSync(SESSION_STATE_DIR)) {
        if (attempts >= maxAttempts) { clearInterval(interval); return; }
        return;
      }
      const dirs = fs.readdirSync(SESSION_STATE_DIR, { withFileTypes: true })
        .filter(d => d.isDirectory());
      let newest = null;
      for (const dir of dirs) {
        const wsPath = path.join(SESSION_STATE_DIR, dir.name, "workspace.yaml");
        if (!fs.existsSync(wsPath)) continue;
        const content = fs.readFileSync(wsPath, "utf8");
        const idMatch = content.match(/^id:\s*(.+)$/m);
        if (!idMatch) continue;

        // Check created_at content (for new sessions) OR file mtime
        // (for auto-resumed sessions where created_at is old)
        const createdMatch = content.match(/^created_at:\s*(.+)$/m);
        const created = createdMatch ? new Date(createdMatch[1]).getTime() : 0;
        const wsMtime = fs.statSync(wsPath).mtimeMs;
        const recentEnough = Math.max(created, wsMtime) >= spawnTime - 5000;

        if (recentEnough) {
          const ts = Math.max(created, wsMtime);
          if (!newest || ts > newest.created) {
            newest = { id: idMatch[1].trim(), created: ts };
          }
        }
      }
      if (newest) {
        meta.sessionId = newest.id;
        meta._detectRunning = false;
        clearInterval(interval);
        registrySet(meta.sessionKey, newest.id);
        startJsonlWatcher(meta);
        log("info", `Session ${meta.sessionKey}: detected session ID ${newest.id}`);
      }
    } catch {}
    if (attempts >= maxAttempts) {
      meta._detectRunning = false;
      clearInterval(interval);
      log("warn", `Session ${meta.sessionKey}: session ID detection timed out after ${maxAttempts * 500 / 1000}s — will retry on next write`);
    }
  }, 500);
}

function startJsonlWatcher(meta) {
  if (meta.jsonlInterval) return; // already watching

  const jsonlPath = path.join(SESSION_STATE_DIR, meta.sessionId, "events.jsonl");

  // Start reading from current file size (skip historical events on resume)
  try {
    meta.jsonlBytesRead = fs.existsSync(jsonlPath) ? fs.statSync(jsonlPath).size : 0;
  } catch {
    meta.jsonlBytesRead = 0;
  }

  meta.jsonlInterval = setInterval(() => {
    try {
      if (!fs.existsSync(jsonlPath)) return;
      const stat = fs.statSync(jsonlPath);
      if (stat.size <= meta.jsonlBytesRead) return;

      // Read only new bytes
      const fd = fs.openSync(jsonlPath, "r");
      const buf = Buffer.alloc(stat.size - meta.jsonlBytesRead);
      fs.readSync(fd, buf, 0, buf.length, meta.jsonlBytesRead);
      fs.closeSync(fd);
      meta.jsonlBytesRead = stat.size;

      const chunk = meta.jsonlPendingLine + buf.toString("utf8");
      const parts = chunk.split("\n");
      meta.jsonlPendingLine = parts.pop() || "";

      for (const line of parts.filter(l => l.trim())) {
        try {
          const evt = JSON.parse(line);
          handleJsonlEvent(meta, evt);
        } catch {} // skip malformed lines
      }
    } catch (err) {
      log("error", `Session ${meta.sessionKey}: JSONL read error: ${err.message}`);
    }
  }, 200);

  log("info", `Session ${meta.sessionKey}: JSONL watcher started on ${jsonlPath}`);
}

function handleJsonlEvent(meta, evt) {
  switch (evt.type) {
    case "user.message": {
      // Prompt was acknowledged by the CLI — clear the ACK retry timer.
      if (meta._promptAckTimer) {
        clearTimeout(meta._promptAckTimer);
        meta._promptAckTimer = null;
      }
      meta._promptAcked = true;
      meta._promptRetries = 0;
      log("info", `Session ${meta.sessionKey}: user.message — prompt confirmed delivered`);
      break;
    }
    case "assistant.message": {
      const content = evt.data?.content;
      if (content) {
        meta.messageAccumulator.push(content);
        broadcastToAll({ event: "assistant_message", sessionKey: meta.sessionKey, content });
      }
      break;
    }
    case "assistant.turn_end": {
      // Save this turn's content and reset — we only want the LAST turn's text.
      // Intermediate turns contain reasoning ("Let me check...", "Good, I now have...")
      // that should not be posted to Teams. The final turn has the actual answer.
      const turnContent = meta.messageAccumulator.join("");
      if (turnContent.length > 0) {
        meta.lastTurnContent = turnContent;
        meta.messageAccumulator = [];
        log("info", `Session ${meta.sessionKey}: assistant.turn_end — saved ${turnContent.length} chars, reset accumulator`);
      } else {
        log("info", `Session ${meta.sessionKey}: assistant.turn_end (empty turn) — keeping lastTurnContent (${meta.lastTurnContent.length} chars)`);
      }
      break;
    }
    case "session.task_complete":
    case "result": {
      // Definitive "agent is done" signal.
      // Use current accumulator if non-empty (final turn text arrived after last
      // turn_end), otherwise fall back to lastTurnContent (the last completed turn).
      const currentContent = meta.messageAccumulator.join("");
      const fullResponse = currentContent || meta.lastTurnContent || "";
      meta.messageAccumulator = [];
      meta.lastTurnContent = "";
      meta.busy = false;
      if (fullResponse.length > 0) {
        broadcastToAll({ event: "turn_end", sessionKey: meta.sessionKey, response: fullResponse });
        log("info", `Session ${meta.sessionKey}: task_complete → turn_end (${fullResponse.length} chars, source: ${currentContent ? "accumulator" : "lastTurn"})`);
      } else {
        // Empty response — still signal completion but with no content.
        // This can happen on tool-only turns or when the CLI loads/reloads.
        broadcastToAll({ event: "turn_end", sessionKey: meta.sessionKey, response: "" });
        log("warn", `Session ${meta.sessionKey}: task_complete with empty accumulator and no lastTurnContent — may be a startup artifact`);
      }
      break;
    }
    case "system": {
      // Only treat turn-complete system events, and only if we have content
      if (evt.data?.subtype === "turn_complete" ||
          /idle|ready|waiting/i.test(JSON.stringify(evt.data || {}))) {
        const currentContent = meta.messageAccumulator.join("");
        const fullResponse = currentContent || meta.lastTurnContent || "";
        if (fullResponse.length > 0) {
          meta.messageAccumulator = [];
          meta.lastTurnContent = "";
          meta.busy = false;
          broadcastToAll({ event: "turn_end", sessionKey: meta.sessionKey, response: fullResponse });
        } else {
          log("info", `Session ${meta.sessionKey}: system event with empty accumulator — ignoring`);
        }
      }
      break;
    }
    case "session.error": {
      const msg = evt.data?.message || evt.data?.error || "Unknown error";
      broadcastToAll({ event: "error", sessionKey: meta.sessionKey, message: msg });
      break;
    }
  }
}

function writeToPty(sessionKey, prompt) {
  const meta = sessions.get(sessionKey);
  if (!meta?.proc) {
    log("error", `writeToPty: session ${sessionKey} not found`);
    return false;
  }
  if (!meta.ready) {
    log("warn", `writeToPty: session ${sessionKey} not ready yet`);
    return false;
  }

  // P2-2: Busy guard — reject concurrent writes to prevent interleaved PTY output.
  // The ACK retry handles the case where the CLI misses the prompt; callers should
  // wait for busy=false (turn_end / error event) before sending the next prompt.
  if (meta.busy) {
    log("warn", `writeToPty: session ${sessionKey} is busy — rejecting concurrent write`);
    return false;
  }

  // If sessionId was never detected (detection timed out), retry now.
  // This ensures the JSONL watcher starts before we write the prompt,
  // so the response will be captured.
  if (!meta.sessionId) {
    log("info", `writeToPty: session ${sessionKey} has no sessionId — retrying detection`);
    detectSessionId(meta);
  }

  // MCP settle guard: if MCP init warnings appeared within the last 10s, defer
  // the write to avoid the prompt being absorbed while the CLI is still initializing
  // MCP servers. Cap total deferral at 90s so stuck sessions don't wait forever.
  const MCP_QUIET_MS = 10000;
  const MCP_MAX_DEFER_MS = 90000;
  const mcpAge = meta._lastMcpOutputAt ? (Date.now() - meta._lastMcpOutputAt) : Infinity;
  const deferAge = meta._mcpDeferredAt ? (Date.now() - meta._mcpDeferredAt) : Infinity;
  // P2-1 fix: use (!meta._mcpDeferredAt || ...) so the guard activates on the first
  // call (deferAge was Infinity before, making the original check always false).
  if (mcpAge < MCP_QUIET_MS && (!meta._mcpDeferredAt || deferAge < MCP_MAX_DEFER_MS)) {
    const waitMs = MCP_QUIET_MS - mcpAge;
    if (!meta._mcpDeferredAt) meta._mcpDeferredAt = Date.now();
    log("warn", `Session ${sessionKey}: MCP init still active (last warning ${Math.round(mcpAge / 1000)}s ago) — deferring prompt write ${Math.round(waitMs / 1000)}s`);
    // P1 fix: capture meta reference and verify it still owns this sessionKey before
    // re-entering writeToPty — prevents injecting into a recycled session that reuses
    // the same key after the original session exits.
    const capturedMeta = meta;
    setTimeout(() => {
      if (capturedMeta.proc && !capturedMeta.proc._exited && sessions.get(sessionKey) === capturedMeta) {
        writeToPty(sessionKey, prompt);
      }
    }, waitMs + 200);
    return true;
  }
  if (meta._mcpDeferredAt) {
    log("info", `Session ${sessionKey}: proceeding with deferred prompt write after ${Math.round(deferAge / 1000)}s`);
    meta._mcpDeferredAt = null;
  }

  meta.busy = true;
  meta.messageAccumulator = [];
  meta.lastTurnContent = "";
  meta._pendingPrompt = prompt;
  meta._promptAcked = false;

  // Pattern: focus-in → Ctrl+U → bracketed paste → delay → focus-in → Enter.
  // Focus-in (ESC[I) ensures Ink's TextInput accepts input.
  // Bracketed paste delivers the prompt atomically.
  const doWrite = () => {
    if (!meta.proc || meta.proc._exited) return;
    meta.proc.write("\x1b[I");
    meta.proc.write("\x15");
    meta.proc.write(`\x1b[200~${prompt}\x1b[201~`);
    const delay = Math.min(2000, 500 + Math.floor(prompt.length / 5));
    setTimeout(() => {
      if (meta.proc && !meta.proc._exited) {
        meta.proc.write("\x1b[I");
        meta.proc.write("\r");
      }
    }, delay);
  };
  doWrite();

  const retryCount = meta._promptRetries || 0;
  log("info", `Session ${sessionKey}: wrote prompt (${prompt.length} chars)${retryCount > 0 ? ` (retry #${retryCount})` : ""}`);

  // ACK gate: watch for user.message in events.jsonl within 30s.
  // If the CLI doesn't acknowledge the prompt (e.g., it was written during MCP init
  // when the terminal buffer consumed the text but the CLI wasn't listening), retry.
  const PROMPT_ACK_TIMEOUT_MS = 30000;
  const MAX_RETRIES = 2;
  const scheduleAckCheck = (attempt) => {
    if (meta._promptAckTimer) clearTimeout(meta._promptAckTimer);
    meta._promptAckTimer = setTimeout(() => {
      meta._promptAckTimer = null;
      if (meta._promptAcked || !meta.proc || meta.proc._exited) return;
      if (attempt >= MAX_RETRIES) {
        log("error", `Session ${sessionKey}: prompt not acknowledged after ${attempt} retries — giving up`);
        meta.busy = false;
        meta._promptRetries = 0;  // reset so next prompt's log message shows (retry #1), not (retry #3)
        broadcastToAll({ event: "error", sessionKey, message: "Prompt not acknowledged by CLI after retries" });
        return;
      }
      meta._promptRetries = attempt + 1;
      log("warn", `Session ${sessionKey}: no user.message within ${PROMPT_ACK_TIMEOUT_MS / 1000}s — retrying prompt (attempt ${meta._promptRetries}/${MAX_RETRIES})`);
      doWrite();
      scheduleAckCheck(meta._promptRetries);
    }, PROMPT_ACK_TIMEOUT_MS);
  };
  scheduleAckCheck(retryCount);

  return true;
}

function killSession(sessionKey) {
  const meta = sessions.get(sessionKey);
  if (!meta) return false;
  log("info", `Killing session ${sessionKey}`);
  if (meta.jsonlInterval) clearInterval(meta.jsonlInterval);
  if (meta.idleTimer) clearTimeout(meta.idleTimer);
  if (meta._promptAckTimer) clearTimeout(meta._promptAckTimer);
  // On Windows, tree-kill FIRST while parent is alive (kills copilot.exe → pwsh.exe → conhost.exe).
  // proc.kill() alone only kills the immediate PTY process, orphaning its children.
  if (IS_WIN && meta.proc?.pid) {
    try { execSync(`taskkill /pid ${meta.proc.pid} /T /F`, { stdio: "ignore", timeout: 5000 }); } catch {}
  }
  try { meta.proc.kill(); } catch {}
  sessions.delete(sessionKey);
  return true;
}

// ── Client Management ───────────────────────────────────────────────────────
/** @type {Set<ClientConn>} */
const clients = new Set();

/**
 * @typedef {Object} ClientConn
 * @property {net.Socket} socket
 * @property {string} type - "ui" | "monitor" | "unknown"
 * @property {string} buffer - partial line buffer
 */

function broadcastToAll(obj) {
  const line = JSON.stringify(obj) + "\n";
  for (const client of clients) {
    try { client.socket.write(line); } catch {}
  }
}

function broadcastToUi(obj) {
  const line = JSON.stringify(obj) + "\n";
  for (const client of clients) {
    if (client.type === "ui") {
      try { client.socket.write(line); } catch {}
    }
  }
}

function handleClientMessage(client, msg) {
  // Client identification
  if (msg.type) {
    client.type = msg.type;
    log("info", `Client identified as ${msg.type}`);
    return;
  }

  switch (msg.cmd) {
    case "spawn": {
      const { sessionKey, resumeId, cwd, env } = msg;
      if (!sessionKey) {
        sendToClient(client, { event: "error", message: "spawn requires sessionKey" });
        return;
      }
      try {
        spawnSession(sessionKey, { resumeId, cwd, env });
        sendToClient(client, { event: "spawned", sessionKey });
      } catch (err) {
        sendToClient(client, { event: "error", sessionKey, message: err.message });
      }
      break;
    }
    case "write": {
      const { sessionKey, prompt } = msg;
      if (!sessionKey || !prompt) {
        sendToClient(client, { event: "error", message: "write requires sessionKey and prompt" });
        return;
      }
      const ok = writeToPty(sessionKey, prompt);
      if (!ok) {
        sendToClient(client, { event: "error", sessionKey, message: "write failed — session not found or not ready" });
      }
      break;
    }
    case "raw_input": {
      // Raw keyboard data → first active session PTY (for interactive monitor terminal)
      const { data } = msg;
      if (!data) return;
      const target = msg.sessionKey
        ? sessions.get(msg.sessionKey)
        : [...sessions.values()].find(m => m.proc);
      if (target?.proc) {
        target.proc.write(data);
        pushBridgeRing(target.sessionKey, "in", `[raw_input] ${JSON.stringify(data).slice(0, 80)}`, data.slice(0, 80));
      } else {
        log("warn", `raw_input: no target session found (sessions: ${sessions.size})`);
        pushBridgeRing("?", "in", `[raw_input-MISS] no target, sessions=${sessions.size}`, "");
      }
      break;
    }
    case "resize": {
      // Resize all active PTY sessions to match the UI terminal dimensions
      const { cols, rows } = msg;
      if (cols > 0 && rows > 0) {
        log("info", `resize: ${bridge_cols}x${bridge_rows} → ${cols}x${rows} (${sessions.size} sessions)`);
        for (const [key, meta] of sessions) {
          if (meta.proc) {
            try {
              meta.proc.resize(cols, rows);
            } catch (err) {
              log("warn", `resize ${key}: ${err.message}`);
            }
          }
        }
        // Store for future session spawns
        bridge_cols = cols;
        bridge_rows = rows;
        pushBridgeRing("*", "in", `[resize] ${cols}x${rows}`, "");
      }
      break;
    }
    case "kill": {
      const { sessionKey } = msg;
      killSession(sessionKey);
      break;
    }
    case "ping": {
      sendToClient(client, { event: "pong" });
      break;
    }
    case "status": {
      const info = [];
      for (const [key, meta] of sessions) {
        info.push({
          sessionKey: key,
          sessionId: meta.sessionId,
          ready: meta.ready,
          busy: meta.busy,
          pid: meta.proc?.pid,
        });
      }
      sendToClient(client, { event: "status", sessions: info });
      break;
    }
    case "shutdown": {
      log("info", "Shutdown command received");
      shutdown();
      break;
    }
    case "set_yolo": {
      yoloMode = !!msg.enabled;
      // Mutual exclusion: disable smart permission when yolo is enabled
      if (yoloMode && smartPermissionMode) {
        smartPermissionMode = false;
        log("info", "Smart permission mode auto-disabled (mutually exclusive with yolo)");
      }
      log("info", `Yolo mode ${yoloMode ? "ENABLED" : "DISABLED"}`);
      // Apply to any existing sessions that are already in autopilot
      if (yoloMode && !smartPermissionMode) {
        for (const [key, meta] of sessions) {
          if (meta._autopilotVerified && !meta._yoloSent && meta.proc) {
            meta._yoloSent = true;
            log("info", `Session ${key}: sending /yolo (retroactive)`);
            pushBridgeRing(key, "in", "[yolo] /yolo\\r", "/yolo command (retroactive)");
            meta.proc.write("\x1b[I");
            meta.proc.write("\x15");
            meta.proc.write(`\x1b[200~/yolo\x1b[201~`);
            setTimeout(() => {
              if (meta.proc) {
                meta.proc.write("\x1b[I");
                meta.proc.write("\r");
              }
            }, 500);
          }
        }
      }
      sendToClient(client, { event: "yolo_set", enabled: yoloMode });
      break;
    }
    case "set_autopilot": {
      autopilotMode = !!msg.enabled;
      log("info", `Autopilot mode ${autopilotMode ? "ENABLED" : "DISABLED"}`);
      if (autopilotMode) {
        for (const [key, meta] of sessions) {
          if (!meta.proc || !meta.ready || meta._autopilotVerified) continue;
          meta._autopilotAttempts = 0;
          meta._autopilotPermissionAnswered = false;
          log("info", `Session ${key}: applying autopilot retroactively to existing ready session`);
          pushBridgeRing(key, "in", "[autopilot-retroactive] retry", "settings enabled after spawn");
          switchToAutopilot(meta, "set_autopilot");
        }
      }
      sendToClient(client, { event: "autopilot_set", enabled: autopilotMode });
      break;
    }
    case "set_auto_approve": {
      // NOTE: Same asymmetry as set_autopilot — see comment above.
      autoApprovePermissions = !!msg.enabled;
      log("info", `Auto-approve permissions ${autoApprovePermissions ? "ENABLED" : "DISABLED"}`);
      sendToClient(client, { event: "auto_approve_set", enabled: autoApprovePermissions });
      break;
    }
    case "set_smart_permission": {
      smartPermissionMode = !!msg.enabled;
      log("info", `Smart permission mode ${smartPermissionMode ? "ENABLED" : "DISABLED"}`);
      // Mutual exclusion: disable yolo when smart permission is enabled
      if (smartPermissionMode && yoloMode) {
        yoloMode = false;
        log("info", "Yolo mode auto-disabled (mutually exclusive with smart permission)");
      }
      sendToClient(client, { event: "smart_permission_set", enabled: smartPermissionMode });
      break;
    }
    default: {
      sendToClient(client, { event: "error", message: `Unknown command: ${msg.cmd}` });
    }
  }
}

function sendToClient(client, obj) {
  try {
    client.socket.write(JSON.stringify(obj) + "\n");
  } catch {}
}

// ── Named Pipe Server ───────────────────────────────────────────────────────
function cleanupSocket() {
  if (!IS_WIN && fs.existsSync(PIPE_PATH)) {
    try { fs.unlinkSync(PIPE_PATH); } catch {}
  }
}

const server = net.createServer((socket) => {
  /** @type {ClientConn} */
  const client = { socket, type: "unknown", buffer: "" };
  clients.add(client);
  log("info", `Client connected (${clients.size} total)`);

  socket.on("data", (data) => {
    client.buffer += data.toString();
    const lines = client.buffer.split("\n");
    client.buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        handleClientMessage(client, msg);
      } catch (err) {
        log("error", `Invalid JSON from client: ${err.message}`);
      }
    }
  });

  socket.on("error", (err) => {
    log("warn", `Client socket error: ${err.message}`);
    clients.delete(client);
  });

  socket.on("close", () => {
    clients.delete(client);
    log("info", `Client disconnected (${clients.size} remaining)`);
  });
});

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  log("info", "Shutting down bridge...");
  // Kill all sessions
  for (const key of [...sessions.keys()]) {
    killSession(key);
  }
  server.close(() => {
    cleanupSocket();
    bridgeStarted = false;
    shuttingDown = false;
    log("info", "Bridge stopped");
    bridgeEvents.emit("exit", 0);
    if (bridgeShouldExitProcess) process.exit(0);
  });
  if (bridgeShouldExitProcess) {
    // Force exit after 5s for standalone bridge mode.
    setTimeout(() => process.exit(0), 5000);
  }
}

function startBridge({ exitProcess = true } = {}) {
  if (bridgeStarted) {
    return { pipePath: PIPE_PATH, pid: process.pid };
  }

  bridgeShouldExitProcess = exitProcess;
  shuttingDown = false;
  if (!registryLoaded) {
    log("info", "PTY Bridge starting...");
    loadRegistry();
  }

  cleanupSocket();
  server.listen(PIPE_PATH, () => {
    bridgeStarted = true;
    log("info", `PTY Bridge listening on ${PIPE_PATH}`);
    console.log(`PTY Bridge listening on ${PIPE_PATH}`);

    // Write the pipe path to a discovery file so clients can find it
    const discoveryDir = path.join(os.homedir(), ".agency-cowork");
    if (!fs.existsSync(discoveryDir)) fs.mkdirSync(discoveryDir, { recursive: true });
    fs.writeFileSync(
      path.join(discoveryDir, "pty-bridge.json"),
      JSON.stringify({ pipe: PIPE_PATH, pid: process.pid, started: new Date().toISOString() }, null, 2)
    );
  });

  return { pipePath: PIPE_PATH, pid: process.pid };
}

server.on("error", (err) => {
  bridgeStarted = false;
  shuttingDown = false;
  if (err.code === "EADDRINUSE") {
    // Another bridge is already running
    log("warn", "Named pipe already in use — another bridge is running");
    console.error("PTY Bridge: pipe already in use. Another instance may be running.");
    bridgeEvents.emit("exit", 1);
    if (bridgeShouldExitProcess) process.exit(1);
    return;
  }
  log("error", `Server error: ${err.message}`);
  bridgeEvents.emit("exit", 1);
});

module.exports = {
  PIPE_PATH,
  startBridge,
  stopBridge: shutdown,
  bridgeEvents,
};

if (require.main === module) {
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("SIGHUP", shutdown);
  if (IS_WIN) {
    process.on("message", (msg) => { if (msg === "shutdown") shutdown(); });
  }
  startBridge({ exitProcess: true });
}
