#!/usr/bin/env node
/**
 * Automated PTY Enter-key repro test
 * 
 * Spawns agency.exe copilot in a real PTY, monitors output for loading/loaded
 * transitions, injects a prompt at the right time, and verifies Enter submits.
 *
 * Tests multiple strategies:
 *   1. "post-loaded"  — wait for "Environment loaded:", then paste + Enter
 *   2. "during-load"  — inject during "Loading environment:" (current bug repro)
 *   3. "retry-enter"  — inject during load, then retry Enter after loaded
 *   4. "ctrl-s"       — use Ctrl+S instead of \r after paste
 *
 * Usage:
 *   node tests/test-pty-enter-repro.mjs [strategy] [prompt]
 *   node tests/test-pty-enter-repro.mjs post-loaded "what is 2+2?"
 *   node tests/test-pty-enter-repro.mjs   (defaults: post-loaded, "test")
 */

import { createRequire } from "module";
import { homedir } from "os";
import { join } from "path";
import { existsSync, statSync, readFileSync } from "fs";

const require = createRequire(import.meta.url);
const pty = require("C:/Projects/agency-cowork-1/ui/node_modules/@homebridge/node-pty-prebuilt-multiarch");
const _stripAnsi = require("C:/Projects/agency-cowork-1/ui/node_modules/strip-ansi");
const stripAnsi = _stripAnsi.default || _stripAnsi;

// ── Config ──
const AGENCY_CMD = join(process.env.APPDATA, "agency", "CurrentVersion", "agency.exe");
const CWD = "C:\\Projects\\maia-agent";
const STRATEGY = process.argv[2] || "post-loaded";
const PROMPT = process.argv[3] || "test";
const TIMEOUT_MS = 90_000; // 90s total timeout

// ── Regex (matches main.js) ──
const LOADED_RE = /Environment loaded:/i;
const LOADING_RE = /Loading environment:/i;
const FALLBACK_READY_RE = /Describe a task to get started\.|Type @|Type \/|^[❯›]\s/im;

// ── State ──
let isLoading = false;
let isLoaded = false;
let promptInjected = false;
let enterSent = false;
let promptAccepted = false;  // CLI started processing (output changes from prompt echo)
let loadStartTime = 0;
let loadedTime = 0;
let promptInjectTime = 0;
let enterTime = 0;
let acceptTime = 0;
let spawnTime = Date.now();
let exitCode = null;

// Track JSONL events to detect prompt acceptance
const SESSION_STATE = join(homedir(), ".copilot", "session-state");
let sessionId = null;
let jsonlSize = 0;

const log = (tag, msg) => {
  const elapsed = ((Date.now() - spawnTime) / 1000).toFixed(1);
  console.log(`[${elapsed}s] [${tag}] ${msg}`);
};

// ── Spawn PTY ──
log("spawn", `${AGENCY_CMD} copilot --model claude-sonnet-4 in ${CWD}`);
log("spawn", `Strategy: ${STRATEGY}, Prompt: "${PROMPT}"`);

const proc = pty.spawn(AGENCY_CMD, ["copilot", "--model", "claude-sonnet-4"], {
  name: "xterm-256color",
  cols: 120,
  rows: 40,
  cwd: CWD,
  env: { ...process.env, MSFT_AGENCY: "true" },
});

// ── Helper: write to PTY ──
function writePty(label, bytes) {
  try { proc.write(bytes); } catch (e) { log("error", `write failed: ${e.message}`); }
  log("write", `${label}: ${JSON.stringify(bytes).slice(0, 80)}`);
}

// ── Helper: inject prompt ──
function injectPrompt() {
  if (promptInjected) return;
  promptInjected = true;
  promptInjectTime = Date.now();

  log("inject", `Pasting prompt (${PROMPT.length} chars)`);
  // Match bridge.js approach exactly: Ctrl+U + bracketed paste + delay + Enter
  writePty("ctrl-u", "\x15");
  writePty("paste", `\x1b[200~${PROMPT}\x1b[201~`);

  const enterDelay = Math.min(2000, 500 + Math.floor(PROMPT.length / 5));
  log("inject", `Scheduling Enter in ${enterDelay}ms`);

  setTimeout(() => {
    enterSent = true;
    enterTime = Date.now();
    if (STRATEGY === "ctrl-s") {
      writePty("submit", "\x13"); // Ctrl+S
      log("enter", `Ctrl+S sent (${enterDelay}ms post-paste)`);
    } else {
      writePty("submit", "\r");
      log("enter", `\\r sent (${enterDelay}ms post-paste)`);
    }
  }, enterDelay);
}

// ── Helper: retry Enter (for retry-enter strategy) ──
function retryEnter(label) {
  if (promptAccepted) return;
  log("retry", `${label}: sending \\r again`);
  writePty("retry-enter", "\r");
}

// ── Session ID detection ──
function detectSessionId(clean) {
  if (sessionId) return;
  // Look for workspace dirs to find session
  const sessionDirs = [];
  try {
    const entries = require("fs").readdirSync(SESSION_STATE);
    for (const e of entries) {
      const wsPath = join(SESSION_STATE, e, "workspace.yaml");
      if (existsSync(wsPath)) {
        const mtime = statSync(wsPath).mtimeMs;
        if (mtime > spawnTime - 5000) {
          sessionDirs.push({ id: e, mtime });
        }
      }
    }
  } catch { return; }

  sessionDirs.sort((a, b) => b.mtime - a.mtime);
  if (sessionDirs.length > 0) {
    sessionId = sessionDirs[0].id;
    const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
    if (existsSync(jsonlPath)) {
      jsonlSize = statSync(jsonlPath).size;
    }
    log("session", `Detected session: ${sessionId}`);
  }
}

// ── JSONL watcher (check for new events = prompt accepted) ──
function checkJsonl() {
  if (!sessionId || promptAccepted) return;
  const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
  try {
    if (!existsSync(jsonlPath)) return;
    const size = statSync(jsonlPath).size;
    if (size > jsonlSize) {
      // New JSONL events — prompt was accepted!
      promptAccepted = true;
      acceptTime = Date.now();
      const newBytes = readFileSync(jsonlPath, "utf8").slice(jsonlSize);
      const firstEvent = newBytes.split("\n").find(l => l.trim());
      let eventType = "unknown";
      try { eventType = JSON.parse(firstEvent).type; } catch {}
      log("JSONL", `New events detected! First: ${eventType}`);
      log("SUCCESS", `Prompt accepted — CLI is processing`);
      printResults(true);
    }
  } catch {}
}

// ── PTY output handler ──
proc.onData((data) => {
  const clean = stripAnsi(data);
  const trimmed = clean.trim();
  if (!trimmed) return;

  // Log significant output (not spinner frames)
  const isSpinner = /^[●◉◎○]\s*Loading/.test(trimmed) && isLoading;
  if (!isSpinner) {
    log("stdout", trimmed.slice(0, 150));
  }

  // Track loading state
  if (LOADING_RE.test(clean) && !isLoading) {
    isLoading = true;
    loadStartTime = Date.now();
    log("STATE", "Loading environment started (isLoading=true)");
  }

  if (LOADED_RE.test(clean) && !isLoaded) {
    isLoaded = true;
    isLoading = false;
    loadedTime = Date.now();
    const loadDuration = ((loadedTime - loadStartTime) / 1000).toFixed(1);
    log("STATE", `Environment loaded! (${loadDuration}s load time)`);

    // Strategy-specific actions on loaded
    if (STRATEGY === "post-loaded") {
      log("strategy", "post-loaded: injecting prompt now (1.5s delay)");
      setTimeout(injectPrompt, 1500);
    } else if (STRATEGY === "retry-enter") {
      log("strategy", "retry-enter: sending retry \\r now (prompt was injected during load)");
      setTimeout(() => retryEnter("post-loaded"), 500);
      setTimeout(() => retryEnter("post-loaded+2s"), 2000);
      setTimeout(() => retryEnter("post-loaded+4s"), 4000);
    }
  }

  // Fallback ready detection (for non-loading case)
  if (!isLoading && !isLoaded && FALLBACK_READY_RE.test(clean)) {
    log("STATE", "Fallback ready detected (no loading phase)");
    if (!promptInjected) {
      setTimeout(injectPrompt, 1000);
    }
  }

  // Strategy: during-load — inject as soon as loading starts
  if (STRATEGY === "during-load" || STRATEGY === "retry-enter") {
    if (isLoading && !promptInjected) {
      // Wait 2s after loading starts to let TUI stabilize
      setTimeout(() => {
        if (!promptInjected) {
          log("strategy", `${STRATEGY}: injecting during load phase`);
          injectPrompt();
        }
      }, 2000);
    }
  }

  // Detect if prompt text appears in output AND then disappears (submission)
  if (enterSent && !promptAccepted && clean.includes(PROMPT)) {
    // The prompt text is echoed — but is it being processed or just sitting there?
    detectSessionId(clean);
  }

  // Also try detecting session any time
  if (!sessionId) detectSessionId(clean);
});

proc.onExit(({ exitCode: code }) => {
  exitCode = code;
  log("exit", `Process exited with code ${code}`);
  if (!promptAccepted) {
    printResults(false);
  }
});

// ── JSONL polling ──
const jsonlPoll = setInterval(checkJsonl, 500);

// ── Timeout ──
const timeout = setTimeout(() => {
  log("TIMEOUT", `${TIMEOUT_MS / 1000}s elapsed — killing process`);
  printResults(false);
}, TIMEOUT_MS);

// ── Results ──
function printResults(success) {
  clearInterval(jsonlPoll);
  clearTimeout(timeout);

  console.log("\n" + "=".repeat(70));
  console.log("TEST RESULTS");
  console.log("=".repeat(70));
  console.log(`Strategy:         ${STRATEGY}`);
  console.log(`Prompt:           "${PROMPT}"`);
  console.log(`Result:           ${success ? "✅ PASS — prompt accepted" : "❌ FAIL — prompt not accepted"}`);
  console.log("");
  console.log("Timeline:");
  console.log(`  Spawn:          0.0s`);
  if (loadStartTime)    console.log(`  Loading start:  ${((loadStartTime - spawnTime) / 1000).toFixed(1)}s`);
  if (promptInjectTime) console.log(`  Prompt inject:  ${((promptInjectTime - spawnTime) / 1000).toFixed(1)}s`);
  if (enterTime)        console.log(`  Enter sent:     ${((enterTime - spawnTime) / 1000).toFixed(1)}s`);
  if (loadedTime)       console.log(`  Env loaded:     ${((loadedTime - spawnTime) / 1000).toFixed(1)}s`);
  if (acceptTime)       console.log(`  Prompt accept:  ${((acceptTime - spawnTime) / 1000).toFixed(1)}s`);
  console.log(`  Session ID:     ${sessionId || "(not detected)"}`);
  console.log("=".repeat(70));

  // Kill the process after a short delay to let output flush
  setTimeout(() => {
    try { proc.kill(); } catch {}
    process.exit(success ? 0 : 1);
  }, 2000);
}
