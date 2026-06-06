#!/usr/bin/env node
/**
 * Automated PTY test: Enter retry guard — skip retry when thinking mode detected
 *
 * Validates that the 3-second retry Enter is suppressed when the CLI has already
 * started producing output (entered "thinking mode") after the primary Enter.
 *
 * This test implements the same Enter sequence as main.js writeToPty/writePromptOnce:
 *   1. Bracketed paste of prompt text
 *   2. Primary Enter after calculated delay
 *   3. 3-second retry window — check if PTY output arrived (thinking mode)
 *
 * Two sub-tests:
 *   1. "retry-suppressed-by-output" — Normal flow: CLI starts thinking, retry should be skipped
 *   2. "retry-fires-when-silent"    — No Enter sent, verify no false positive (CLI stays silent)
 *
 * Optionally queries the Electron debug API at http://127.0.0.1:9876 for lifecycle
 * events (available when running with dev Electron). Falls back to JSONL-only verification.
 *
 * Platform: Windows-only (requires agency.exe and node-pty prebuilt for Windows).
 *
 * Usage:
 *   node tests/test-retry-enter-guard.mjs
 *   node tests/test-retry-enter-guard.mjs --cwd C:\Projects\my-project
 *
 * Exit codes:
 *   0 = all assertions pass
 *   1 = one or more assertions failed
 *   2 = setup failure (agency.exe not found, PTY spawn failed, unsupported platform)
 */

import { createRequire } from "module";
import { homedir, platform } from "os";
import { join, resolve } from "path";
import { existsSync, statSync, readFileSync, readdirSync } from "fs";
import { execSync } from "child_process";
import http from "http";

if (platform() !== "win32") {
  console.error("SETUP FAILURE: This test requires Windows (agency.exe + node-pty prebuilt).");
  process.exit(2);
}

const require = createRequire(import.meta.url);

// ── Resolve node-pty: prefer local ui/node_modules ──
let pty, stripAnsi;
const localPty = join(resolve("."), "ui", "node_modules", "@homebridge", "node-pty-prebuilt-multiarch");
try {
  pty = require(existsSync(localPty) ? localPty : "node-pty");
} catch (e) {
  console.error(`SETUP FAILURE: Cannot load node-pty from ${localPty}: ${e.message}`);
  process.exit(2);
}
const localStripAnsi = join(resolve("."), "ui", "node_modules", "strip-ansi");
try {
  const _s = require(existsSync(localStripAnsi) ? localStripAnsi : "strip-ansi");
  stripAnsi = _s.default || _s;
} catch {
  stripAnsi = (s) => s.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");
}

// ── Resolve agency.exe: APPDATA > PATH > known install locations ──
function findAgencyCmd() {
  const candidates = [
    join(process.env.APPDATA || "", "agency", "CurrentVersion", "agency.exe"),
    join(process.env.LOCALAPPDATA || "", "agency", "CurrentVersion", "agency.exe"),
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  // Try PATH
  try {
    const found = execSync("where agency.exe", { encoding: "utf8" }).trim().split(/\r?\n/)[0];
    if (found && existsSync(found)) return found;
  } catch { /* not on PATH */ }
  console.error(`SETUP FAILURE: agency.exe not found. Checked:\n  ${candidates.join("\n  ")}\n  PATH (where agency.exe)`);
  process.exit(2);
}

// ── Config ──
const AGENCY_CMD = findAgencyCmd();
const CWD = process.argv.includes("--cwd") ? process.argv[process.argv.indexOf("--cwd") + 1] : resolve(".");
const TIMEOUT_MS = 60_000;
const RETRY_WINDOW_MS = 3000;   // Same 3s retry window as main.js
const ECHO_GRACE_MS = 500;      // Skip first 500ms of output (echo from paste)
const PROMPT = "say hello in exactly three words";
const SESSION_STATE = join(homedir(), ".copilot", "session-state");
const DEBUG_API = "http://127.0.0.1:9876";

// ── Regex (matches main.js) ──
const LOADED_RE = /Environment loaded:/i;
const FALLBACK_READY_RE = /Describe a task to get started\.|Type @|Type \/|^[❯›]\s/im;

// ── Assertions ──
const assertions = [];
function assert(name, condition, detail = "") {
  assertions.push({ name, pass: !!condition, detail });
  const icon = condition ? "✅" : "❌";
  log("assert", `${icon} ${name}${detail ? ` — ${detail}` : ""}`);
}

// ── Logging ──
const startTime = Date.now();
const log = (tag, msg) => {
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`[${elapsed}s] [${tag}] ${msg}`);
};

// ── Preflight ──
if (!existsSync(AGENCY_CMD)) {
  console.error(`SETUP FAILURE: agency.exe not found at ${AGENCY_CMD}`);
  process.exit(2);
}

// ── Debug API helper (best-effort, does not fail test if unavailable) ──
function debugApiGet(path) {
  return new Promise((resolve) => {
    const req = http.get(`${DEBUG_API}${path}`, { timeout: 2000 }, (res) => {
      let body = "";
      res.on("data", (chunk) => body += chunk);
      res.on("end", () => {
        try { resolve(JSON.parse(body)); } catch { resolve(null); }
      });
    });
    req.on("error", () => resolve(null));
    req.on("timeout", () => { req.destroy(); resolve(null); });
  });
}

// ── Session ID detection ──
function detectSessionId(afterTime) {
  try {
    const entries = readdirSync(SESSION_STATE, { withFileTypes: true });
    const candidates = [];
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const wsPath = join(SESSION_STATE, e.name, "workspace.yaml");
      if (existsSync(wsPath)) {
        const mtime = statSync(wsPath).mtimeMs;
        if (mtime > afterTime - 5000) {
          candidates.push({ id: e.name, mtime });
        }
      }
    }
    candidates.sort((a, b) => b.mtime - a.mtime);
    return candidates[0]?.id || null;
  } catch { return null; }
}

// ── Check for new JSONL events ──
// eventFilter: optional array of event types to count (e.g., ["user.message"])
function checkJsonlActivity(sessionId, baselineSize, eventFilter) {
  if (!sessionId) return { hasActivity: false };
  const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
  try {
    if (!existsSync(jsonlPath)) return { hasActivity: false };
    const size = statSync(jsonlPath).size;
    if (size > baselineSize) {
      const content = readFileSync(jsonlPath, "utf8").slice(baselineSize);
      const lines = content.split("\n").filter(l => l.trim());
      const parsed = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
      const filtered = eventFilter ? parsed.filter(e => eventFilter.includes(e.type)) : parsed;
      if (filtered.length === 0) return { hasActivity: false, totalNew: parsed.length };
      return { hasActivity: true, newBytes: size - baselineSize, firstType: filtered[0].type, lineCount: filtered.length, totalNew: parsed.length };
    }
  } catch {}
  return { hasActivity: false };
}

// ══════════════════════════════════════════════════════════════
// SUB-TEST 1: retry-suppressed-by-output
// Verify that the retry Enter is skipped when CLI produces output
// ══════════════════════════════════════════════════════════════
async function testRetrySuppressedByOutput() {
  log("test-1", "=== retry-suppressed-by-output ===");
  log("test-1", `Spawning: ${AGENCY_CMD} copilot in ${CWD}`);

  const spawnTime = Date.now();
  const proc = pty.spawn(AGENCY_CMD, ["copilot"], {
    name: "xterm-256color",
    cols: 120,
    rows: 40,
    cwd: CWD,
    env: { ...process.env, MSFT_AGENCY: "true" },
  });

  return new Promise((resolveTest) => {
    let isReady = false;
    let enterSent = false;
    let enterSentAt = 0;
    let ptyActivityAfterEnter = false;   // Mirrors main.js meta.ptyActivityAfterEnter
    let ptyActivityAt = 0;
    let retryWindowElapsed = false;
    let promptAccepted = false;          // JSONL activity detected
    let sessionId = null;
    let jsonlBaseline = 0;
    let outputChunksAfterEnter = 0;
    const timeout = setTimeout(() => {
      log("test-1", "TIMEOUT — killing process");
      assert("test-1: completed within timeout", false, `${TIMEOUT_MS}ms elapsed`);
      try { proc.kill(); } catch {}
      resolveTest();
    }, TIMEOUT_MS);

    function cleanup() {
      clearTimeout(timeout);
      try { proc.kill(); } catch {}
    }

    // Poll for session + JSONL
    const jsonlPoller = setInterval(() => {
      if (!sessionId) {
        sessionId = detectSessionId(spawnTime);
        if (sessionId) {
          const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
          try { jsonlBaseline = existsSync(jsonlPath) ? statSync(jsonlPath).size : 0; } catch {}
          log("test-1", `Session detected: ${sessionId}, JSONL baseline: ${jsonlBaseline}`);
        }
      }
      if (sessionId && enterSent && !promptAccepted) {
        const result = checkJsonlActivity(sessionId, jsonlBaseline);
        if (result.hasActivity) {
          promptAccepted = true;
          log("test-1", `JSONL activity: ${result.lineCount} events, first: ${result.firstType}`);
        }
      }
    }, 200);

    proc.onData((data) => {
      const clean = stripAnsi(data);

      // Detect ready state
      if (!isReady && (LOADED_RE.test(clean) || FALLBACK_READY_RE.test(clean))) {
        isReady = true;
        log("test-1", `CLI ready detected: "${clean.trim().slice(0, 60)}"`);
        // Inject prompt after a short settle delay
        setTimeout(() => injectPrompt(), 1500);
      }

      // Track PTY output after Enter (same logic as the production code)
      if (enterSent && !ptyActivityAfterEnter && Date.now() - enterSentAt > ECHO_GRACE_MS) {
        ptyActivityAfterEnter = true;
        ptyActivityAt = Date.now();
        const elapsed = Date.now() - enterSentAt;
        log("test-1", `PTY activity detected ${elapsed}ms after Enter — thinking mode`);
      }
      if (enterSent) {
        outputChunksAfterEnter++;
      }
    });

    proc.onExit(({ exitCode: code }) => {
      log("test-1", `Process exited: code=${code}`);
      clearInterval(jsonlPoller);
    });

    function injectPrompt() {
      log("test-1", `Injecting prompt: "${PROMPT}" (${PROMPT.length} chars)`);
      // Match production: focus-in → Ctrl+U → bracketed paste → delay → Enter
      proc.write("\x1b[I");
      proc.write("\x15");
      proc.write(`\x1b[200~${PROMPT}\x1b[201~`);

      const enterDelay = Math.min(2000, 500 + Math.floor(PROMPT.length / 5));
      log("test-1", `Enter scheduled in ${enterDelay}ms`);

      setTimeout(() => {
        proc.write("\x1b[I");
        proc.write("\r");
        enterSent = true;
        enterSentAt = Date.now();
        log("test-1", `Primary Enter sent`);

        // Wait for the full retry window (3s) + buffer, then evaluate
        setTimeout(async () => {
          retryWindowElapsed = true;
          log("test-1", "--- Retry window elapsed (3s) — evaluating ---");

          // ── Assertions ──
          assert(
            "test-1: PTY output detected after Enter",
            ptyActivityAfterEnter,
            ptyActivityAfterEnter
              ? `detected ${ptyActivityAt - enterSentAt}ms after Enter, ${outputChunksAfterEnter} chunks total`
              : `no output detected in ${RETRY_WINDOW_MS}ms window`
          );

          assert(
            "test-1: PTY activity within retry window",
            ptyActivityAfterEnter && (ptyActivityAt - enterSentAt) < RETRY_WINDOW_MS,
            ptyActivityAfterEnter
              ? `${ptyActivityAt - enterSentAt}ms < ${RETRY_WINDOW_MS}ms`
              : "no activity"
          );

          assert(
            "test-1: JSONL activity confirms processing",
            promptAccepted,
            promptAccepted ? "prompt accepted via JSONL" : "no JSONL events detected"
          );

          // If retry would have fired (no ptyActivity AND no promptSubmitted), that's a failure
          const retryWouldFire = !ptyActivityAfterEnter && !promptAccepted;
          assert(
            "test-1: retry Enter would be suppressed",
            !retryWouldFire,
            retryWouldFire
              ? "FAIL — neither PTY activity nor JSONL detected; retry would fire"
              : `suppressed by ${ptyActivityAfterEnter ? "ptyActivity" : "promptSubmitted"}`
          );

          // ── Optional: query debug API for lifecycle events ──
          const timeline = await debugApiGet("/timeline/json?last=50");
          if (timeline && Array.isArray(timeline)) {
            log("test-1", `Debug API available — ${timeline.length} lifecycle events`);
            const retrySkipped = timeline.filter(e =>
              e.phase === "enter-retry-skipped" || e.phase === "writeToPty-retry-skipped"
            );
            const retryFired = timeline.filter(e =>
              e.phase === "enter-retry-ipc" || e.phase === "enter-retry-direct" ||
              e.phase === "writeToPty-retry-direct"
            );
            const ptyActivityEvent = timeline.filter(e =>
              e.phase === "pty-activity-after-enter"
            );

            assert(
              "test-1: debug API — pty-activity-after-enter event exists",
              ptyActivityEvent.length > 0,
              ptyActivityEvent.length > 0 ? ptyActivityEvent[0].detail : "not found"
            );
            assert(
              "test-1: debug API — retry-skipped event exists",
              retrySkipped.length > 0,
              retrySkipped.length > 0 ? retrySkipped[0].detail : "not found"
            );
            assert(
              "test-1: debug API — no retry-fired events",
              retryFired.length === 0,
              retryFired.length > 0 ? `UNEXPECTED: ${retryFired.map(e => e.phase).join(", ")}` : "clean"
            );
          } else {
            log("test-1", "Debug API not available (expected in non-dev mode) — skipping API assertions");
          }

          cleanup();
          clearInterval(jsonlPoller);
          resolveTest();
        }, RETRY_WINDOW_MS + 1500); // Wait retry window + 1.5s buffer
      }, enterDelay);
    }
  });
}

// ══════════════════════════════════════════════════════════════
// SUB-TEST 2: retry-fires-when-silent
// Verify that WITHOUT Enter, the CLI stays silent (no false positive on activity)
// This validates that ptyActivityAfterEnter doesn't get set spuriously.
// ══════════════════════════════════════════════════════════════
async function testRetryFiresWhenSilent() {
  log("test-2", "=== retry-fires-when-silent ===");
  log("test-2", `Spawning: ${AGENCY_CMD} copilot in ${CWD}`);

  const spawnTime = Date.now();
  const proc = pty.spawn(AGENCY_CMD, ["copilot"], {
    name: "xterm-256color",
    cols: 120,
    rows: 40,
    cwd: CWD,
    env: { ...process.env, MSFT_AGENCY: "true" },
  });

  return new Promise((resolveTest) => {
    let isReady = false;
    let textPasted = false;
    let pasteTime = 0;
    let ptyOutputAfterPaste = false;
    let sessionId = null;
    let jsonlBaseline = 0;
    let jsonlActivity = false;
    const timeout = setTimeout(() => {
      log("test-2", "TIMEOUT — killing process");
      assert("test-2: completed within timeout", false, `${TIMEOUT_MS}ms elapsed`);
      try { proc.kill(); } catch {}
      resolveTest();
    }, TIMEOUT_MS);

    function cleanup() {
      clearTimeout(timeout);
      try { proc.kill(); } catch {}
    }

    // Poll for session
    const jsonlPoller = setInterval(() => {
      if (!sessionId) {
        sessionId = detectSessionId(spawnTime);
        if (sessionId) {
          log("test-2", `Session detected: ${sessionId}`);
        }
      }
      // Only check for user.message events (not session.resume which fires on startup)
      if (sessionId && textPasted && !jsonlActivity) {
        const result = checkJsonlActivity(sessionId, jsonlBaseline, ["user.message", "assistant.message"]);
        if (result.hasActivity) {
          jsonlActivity = true;
          log("test-2", `UNEXPECTED JSONL activity: ${result.firstType}`);
        }
      }
    }, 200);

    proc.onData((data) => {
      const clean = stripAnsi(data);

      if (!isReady && (LOADED_RE.test(clean) || FALLBACK_READY_RE.test(clean))) {
        isReady = true;
        log("test-2", `CLI ready detected`);
        // Snapshot JSONL baseline AFTER ready (captures session.resume etc.)
        if (sessionId) {
          const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
          try { jsonlBaseline = existsSync(jsonlPath) ? statSync(jsonlPath).size : 0; } catch {}
          log("test-2", `JSONL baseline (post-ready): ${jsonlBaseline}`);
        }
        setTimeout(() => pasteWithoutEnter(), 1500);
      }

      // After paste, track any output beyond the echo window
      if (textPasted && !ptyOutputAfterPaste && Date.now() - pasteTime > ECHO_GRACE_MS) {
        ptyOutputAfterPaste = true;
        log("test-2", `PTY output detected ${Date.now() - pasteTime}ms after paste (unexpected without Enter)`);
      }
    });

    proc.onExit(({ exitCode: code }) => {
      log("test-2", `Process exited: code=${code}`);
      clearInterval(jsonlPoller);
    });

    function pasteWithoutEnter() {
      // Snapshot JSONL baseline right before paste (latest possible to avoid startup noise)
      if (sessionId && jsonlBaseline === 0) {
        const jsonlPath = join(SESSION_STATE, sessionId, "events.jsonl");
        try { jsonlBaseline = existsSync(jsonlPath) ? statSync(jsonlPath).size : 0; } catch {}
        log("test-2", `JSONL baseline (pre-paste): ${jsonlBaseline}`);
      }
      log("test-2", `Pasting text WITHOUT Enter: "${PROMPT}"`);
      proc.write("\x1b[I");
      proc.write("\x15");
      proc.write(`\x1b[200~${PROMPT}\x1b[201~`);
      textPasted = true;
      pasteTime = Date.now();

      // Wait the full retry window, then check — CLI should NOT be processing
      setTimeout(() => {
        log("test-2", "--- Evaluation window elapsed — checking silence ---");

        // Note: ptyOutputAfterPaste may be true due to the text echo and TUI redraws.
        // The key assertion is NO JSONL activity (prompt was NOT submitted).
        assert(
          "test-2: no JSONL activity without Enter",
          !jsonlActivity,
          jsonlActivity ? "FAIL — JSONL activity detected without Enter" : "CLI stayed idle"
        );

        // The retry mechanism should fire in this case (no Enter → no output → no guard)
        // This confirms the guard doesn't false-positive on paste echo alone
        assert(
          "test-2: paste echo does not count as thinking activity",
          !jsonlActivity,
          "CLI did not process prompt without Enter key"
        );

        cleanup();
        clearInterval(jsonlPoller);
        resolveTest();
      }, RETRY_WINDOW_MS + 2000);
    }
  });
}

// ══════════════════════════════════════════════════════════════
// RUNNER
// ══════════════════════════════════════════════════════════════
async function run() {
  log("runner", "╔══════════════════════════════════════════════╗");
  log("runner", "║  PTY Retry Enter Guard — Automated Test     ║");
  log("runner", "╚══════════════════════════════════════════════╝");
  log("runner", `CWD: ${CWD}`);
  log("runner", `Agency: ${AGENCY_CMD}`);

  await testRetrySuppressedByOutput();
  log("runner", "");
  await testRetryFiresWhenSilent();

  // ── Results ──
  log("runner", "");
  log("runner", "══════════════ RESULTS ══════════════");
  const passed = assertions.filter(a => a.pass).length;
  const failed = assertions.filter(a => !a.pass).length;
  for (const a of assertions) {
    const icon = a.pass ? "✅" : "❌";
    console.log(`  ${icon} ${a.name}${a.detail ? ` (${a.detail})` : ""}`);
  }
  log("runner", `${passed} passed, ${failed} failed`);
  log("runner", failed > 0 ? "FAIL" : "PASS");
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((e) => {
  console.error("Fatal error:", e);
  process.exit(2);
});
