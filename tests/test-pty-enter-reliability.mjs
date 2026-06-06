#!/usr/bin/env node
/**
 * PTY Enter-key Reliability Test
 *
 * Systematically measures which strategy most reliably submits a prompt
 * to the Copilot CLI's Ink TUI via node-pty.
 *
 * Problem: Text injection via bracketed paste works, but sending Enter (\r)
 * to actually *execute* the prompt is unreliable — the TUI's re-render
 * cycle can swallow the keystroke.
 *
 * This test compares strategies across multiple trials and produces a
 * statistical summary.  Each trial spawns a fresh PTY, waits for the
 * "Environment loaded:" gate, injects a trivial prompt, then measures
 * whether the prompt was actually submitted (user.message appears in JSONL).
 *
 * Strategies tested:
 *   paste-delay-300     — bracketed paste, \r after 300ms
 *   paste-delay-500     — bracketed paste, \r after 500ms
 *   paste-delay-800     — bracketed paste, \r after 800ms
 *   paste-delay-1500    — bracketed paste, \r after 1500ms
 *   echo-then-enter     — bracketed paste, wait for echo-back, then \r
 *   echo-150            — bracketed paste, wait for echo-back, 150ms, \r
 *   echo-300            — bracketed paste, wait for echo-back, 300ms, \r
 *   staggered-3x        — bracketed paste, 3x \r at 800/1200/1700ms (production)
 *   raw-echo-enter      — raw write (no paste wrapper), echo-back, \r
 *   ctrl-u-paste-enter  — Ctrl+U clear + bracketed paste, echo-back, 150ms, \r
 *
 * Usage:
 *   node tests/test-pty-enter-reliability.mjs [options]
 *
 * Options:
 *   --strategy=<name|all>   Run one strategy or all (default: all)
 *   --trials=N              Trials per strategy (default: 2)
 *   --timeout-ms=N          Per-trial timeout in ms (default: 90000)
 *   --model=<model>         LLM model (default: claude-haiku-4.5)
 *   --prompt=<text>         Prompt to inject (default: "What is 2+2? Reply with just the number.")
 *   --verbose               Log all PTY output
 *   --json                  Write results to tests/pty-enter-results.json
 *
 * Exit codes: 0 = at least one strategy has 100% success, 1 = none, 2 = env error
 */
import path from "path";
import fs from "fs";
import os from "os";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SESSION_STATE_DIR = path.join(os.homedir(), ".copilot", "session-state");

// ── Arg parsing ──
const args = new Map(process.argv.slice(2).map(arg => {
  const idx = arg.indexOf("=");
  return idx >= 0 ? [arg.slice(0, idx), arg.slice(idx + 1)] : [arg, "true"];
}));
const selectedStrategy = args.get("--strategy") || "all";
const trials = Number(args.get("--trials") || 2);
const timeoutMs = Number(args.get("--timeout-ms") || 90000);
const model = args.get("--model") || "claude-haiku-4.5";
const prompt = args.get("--prompt") || "What is 2+2? Reply with just the number.";
const verbose = args.has("--verbose");
const writeJson = args.has("--json");

// ── Environment checks ──
let pty;
try {
  const uiDir = path.resolve(__dirname, "..", "ui");
  const ptyPath = path.join(uiDir, "node_modules", "@homebridge", "node-pty-prebuilt-multiarch");
  if (fs.existsSync(ptyPath)) {
    pty = (await import(`file://${ptyPath.replace(/\\/g, "/")}/lib/index.js`)).default;
  } else {
    pty = (await import("@homebridge/node-pty-prebuilt-multiarch")).default;
  }
} catch (e) {
  console.error(`SKIP: node-pty not available (${e.message}). Run \`npm install\` in ui/ first.`);
  process.exit(2);
}

const agencyPath = process.env.AGENCY_PATH
  || path.join(process.env.APPDATA || "", "agency", "CurrentVersion", "agency.exe");
if (!fs.existsSync(agencyPath)) {
  console.error(`SKIP: Agency executable not found: ${agencyPath}`);
  process.exit(2);
}

// ── ANSI Stripping ──
function stripAnsi(s) {
  return s
    .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")         // CSI
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "") // OSC
    .replace(/\x1b[()][0-9A-Za-z]/g, "")              // charset
    .replace(/\x1b[=>M78DEHNO]/g, "")                  // single-char
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");   // control chars
}

// ── Pre-seed folder trust ──
function ensureFolderTrust(dir) {
  const cfgPath = path.join(os.homedir(), ".copilot", "config.json");
  try {
    let cfg = {};
    if (fs.existsSync(cfgPath)) cfg = JSON.parse(fs.readFileSync(cfgPath, "utf-8"));
    if (!Array.isArray(cfg.trusted_folders)) cfg.trusted_folders = [];
    const norm = dir.replace(/\//g, "\\");
    if (!cfg.trusted_folders.includes(norm)) {
      cfg.trusted_folders.push(norm);
      fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2), "utf-8");
    }
  } catch {}
}

const testCwd = path.resolve(__dirname, "..");
ensureFolderTrust(testCwd);

// ── Strategy definitions ──
// Each strategy is (proc, text, onEchoCb) => void
// onEchoCb: a function the strategy can call to register an echo-back watcher.
//   onEchoCb(proc, fingerprint, postEchoDelayMs, fallbackMs) returns a dispose fn.
//   It watches PTY output for `fingerprint`, waits `postEchoDelayMs`, then sends \r.
//   Falls back to sending \r after `fallbackMs` if echo never appears.

function makeEchoWatcher(proc, fingerprint, postEchoDelay, fallbackMs, timings) {
  let enterSent = false;
  const sendEnter = (reason) => {
    if (enterSent) return;
    enterSent = true;
    timings.enterSentAt = Date.now();
    timings.enterReason = reason;
    proc.write("\r");
  };

  const watcher = proc.onData((data) => {
    if (enterSent) { watcher.dispose(); return; }
    const clean = stripAnsi(data);
    if (clean.includes(fingerprint)) {
      watcher.dispose();
      timings.echoDetectedAt = Date.now();
      if (postEchoDelay <= 0) {
        sendEnter("echo-immediate");
      } else {
        setTimeout(() => sendEnter(`echo+${postEchoDelay}ms`), postEchoDelay);
      }
    }
  });

  // Fallback
  const fallbackTimer = setTimeout(() => {
    watcher.dispose();
    sendEnter(`fallback-${fallbackMs}ms`);
  }, fallbackMs);

  return () => { watcher.dispose(); clearTimeout(fallbackTimer); };
}

const PASTE_START = "\x1b[200~";
const PASTE_END = "\x1b[201~";

const strategies = {
  // ── Fixed delay strategies ──
  "paste-delay-300": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    setTimeout(() => {
      timings.enterSentAt = Date.now();
      timings.enterReason = "fixed-300ms";
      proc.write("\r");
    }, 300);
  },
  "paste-delay-500": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    setTimeout(() => {
      timings.enterSentAt = Date.now();
      timings.enterReason = "fixed-500ms";
      proc.write("\r");
    }, 500);
  },
  "paste-delay-800": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    setTimeout(() => {
      timings.enterSentAt = Date.now();
      timings.enterReason = "fixed-800ms";
      proc.write("\r");
    }, 800);
  },
  "paste-delay-1500": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    setTimeout(() => {
      timings.enterSentAt = Date.now();
      timings.enterReason = "fixed-1500ms";
      proc.write("\r");
    }, 1500);
  },

  // ── Echo-back strategies ──
  "echo-then-enter": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    makeEchoWatcher(proc, text.slice(0, 20), 0, 3000, timings);
  },
  "echo-150": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    makeEchoWatcher(proc, text.slice(0, 20), 150, 3000, timings);
  },
  "echo-300": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    makeEchoWatcher(proc, text.slice(0, 20), 300, 3000, timings);
  },

  // ── Staggered multi-Enter (current production approach) ──
  "staggered-3x": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    timings.enterReason = "staggered-3x";
    setTimeout(() => {
      timings.enterSentAt = Date.now();
      proc.write("\r");
      setTimeout(() => proc.write("\r"), 400);
      setTimeout(() => proc.write("\r"), 900);
    }, 800);
  },

  // ── Raw (no bracketed paste) + echo-back ──
  "raw-echo-enter": (proc, text, _echoHelper, timings) => {
    proc.write(text);
    makeEchoWatcher(proc, text.slice(0, 20), 150, 3000, timings);
  },

  // ── Ctrl+U clear line + bracketed paste + echo-back ──
  "ctrl-u-paste-enter": (proc, text, _echoHelper, timings) => {
    proc.write("\x15"); // Ctrl+U clears input line
    setTimeout(() => {
      proc.write(`${PASTE_START}${text}${PASTE_END}`);
      makeEchoWatcher(proc, text.slice(0, 20), 150, 3000, timings);
    }, 50);
  },

  // ── Retry loop: send \r every 200ms until JSONL confirms submission ──
  // This is the brute-force "keep knocking" approach.
  "retry-enter-200": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    timings.enterReason = "retry-200ms";
    let count = 0;
    const iv = setInterval(() => {
      if (timings.userMessageAt) { clearInterval(iv); return; } // submitted!
      count++;
      if (count === 1) timings.enterSentAt = Date.now();
      proc.write("\r");
      timings.enterRetries = count;
    }, 200);
    // Safety: stop retrying after 10s
    setTimeout(() => clearInterval(iv), 10000);
  },

  // ── Prompt-char detection: wait for ❯ to appear after echo ──
  // The ❯ character signals Ink has finished its re-render and is idle.
  "prompt-char-enter": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    const fingerprint = text.slice(0, 15);
    let echoed = false;
    let enterSent = false;

    const sendEnter = (reason) => {
      if (enterSent) return;
      enterSent = true;
      timings.enterSentAt = Date.now();
      timings.enterReason = reason;
      proc.write("\r");
    };

    const watcher = proc.onData((data) => {
      if (enterSent) { watcher.dispose(); return; }
      const clean = stripAnsi(data);
      // Stage 1: wait for echo-back
      if (!echoed && clean.includes(fingerprint)) {
        echoed = true;
        timings.echoDetectedAt = Date.now();
      }
      // Stage 2: after echo, wait for prompt char ❯ (Ink idle signal)
      if (echoed && /[❯›>]\s*$/.test(clean)) {
        watcher.dispose();
        // Small delay for safety after prompt char
        setTimeout(() => sendEnter("prompt-char+50ms"), 50);
      }
    });

    // Fallback: send Enter after 3s if prompt char never seen
    setTimeout(() => { watcher.dispose(); sendEnter("prompt-char-fallback-3s"); }, 3000);
  },

  // ── Echo-back + double Enter (belt and suspenders) ──
  "echo-double-enter": (proc, text, _echoHelper, timings) => {
    proc.write(`${PASTE_START}${text}${PASTE_END}`);
    const fingerprint = text.slice(0, 20);
    let enterSent = false;

    const sendDoubleEnter = (reason) => {
      if (enterSent) return;
      enterSent = true;
      timings.enterSentAt = Date.now();
      timings.enterReason = reason;
      proc.write("\r");
      setTimeout(() => proc.write("\r"), 300);
    };

    const watcher = proc.onData((data) => {
      if (enterSent) { watcher.dispose(); return; }
      const clean = stripAnsi(data);
      if (clean.includes(fingerprint)) {
        watcher.dispose();
        timings.echoDetectedAt = Date.now();
        setTimeout(() => sendDoubleEnter("echo+200ms+double"), 200);
      }
    });

    setTimeout(() => { watcher.dispose(); sendDoubleEnter("fallback-3s+double"); }, 3000);
  },
};

// ── Broadcast JSONL watcher ──
// Monitors ALL session directories for new user.message / assistant.message events.
// Solves the chicken-and-egg problem: the CLI may auto-resume a session, so we
// can't know which session to watch until events appear.
function watchAllSessions(startedAt, callbacks) {
  // Snapshot baseline sizes of all events.jsonl files
  const baselines = new Map(); // sessionId → bytesRead
  const pendingLines = new Map(); // sessionId → trailing partial line
  let detectedSession = null;

  try {
    for (const dir of fs.readdirSync(SESSION_STATE_DIR, { withFileTypes: true })) {
      if (!dir.isDirectory()) continue;
      const jf = path.join(SESSION_STATE_DIR, dir.name, "events.jsonl");
      try {
        if (fs.existsSync(jf)) baselines.set(dir.name, fs.statSync(jf).size);
        else baselines.set(dir.name, 0);
      } catch {}
    }
  } catch {}

  const iv = setInterval(() => {
    try {
      for (const dir of fs.readdirSync(SESSION_STATE_DIR, { withFileTypes: true })) {
        if (!dir.isDirectory()) continue;
        const sid = dir.name;
        const jf = path.join(SESSION_STATE_DIR, sid, "events.jsonl");
        if (!fs.existsSync(jf)) continue;

        const currentSize = fs.statSync(jf).size;
        const baseline = baselines.get(sid) || 0;
        if (currentSize <= baseline) continue;

        // New bytes — read them
        const fd = fs.openSync(jf, "r");
        const buf = Buffer.alloc(currentSize - baseline);
        fs.readSync(fd, buf, 0, buf.length, baseline);
        fs.closeSync(fd);
        baselines.set(sid, currentSize);

        const pending = pendingLines.get(sid) || "";
        const chunk = pending + buf.toString("utf8");
        const parts = chunk.split("\n");
        pendingLines.set(sid, parts.pop() || "");

        for (const line of parts) {
          if (!line.trim()) continue;
          try {
            const evt = JSON.parse(line);
            // Only process events with recent timestamps
            const evtTs = new Date(evt.timestamp).getTime();
            if (evtTs < startedAt - 5000) continue;

            if (!detectedSession && evt.type) {
              detectedSession = sid;
              callbacks.onSessionDetected?.(sid);
            }
            if (evt.type === "user.message") callbacks.onUserMessage?.(evt);
            if (evt.type === "assistant.message") callbacks.onAssistantMessage?.(evt);
          } catch {}
        }
      }
    } catch {}
  }, 100);

  return () => clearInterval(iv);
}

// ── Run a single trial ──
const READY_RE = /Environment loaded:/i;

async function runTrial(strategyName, trialNum) {
  return new Promise((resolve) => {
    const started = Date.now();
    const elapsed = () => ((Date.now() - started) / 1000).toFixed(1);
    const log = (msg) => console.log(`    [${strategyName}#${trialNum}] [${elapsed()}s] ${msg}`);

    const timings = {
      spawnAt: started,
      gateAt: null,
      textWrittenAt: null,
      echoDetectedAt: null,
      enterSentAt: null,
      enterReason: null,
      userMessageAt: null,
      assistantMessageAt: null,
    };

    let done = false;
    let stopWatcher = null;
    let timer = null;

    const proc = pty.spawn(agencyPath, ["copilot", "--model", model], {
      name: "xterm-256color", cols: 120, rows: 40, cwd: testCwd,
      env: { ...process.env, MSFT_AGENCY: "true" },
    });
    log("spawned");

    const cleanup = (result) => {
      if (done) return;
      done = true;
      if (timer) clearTimeout(timer);
      if (stopWatcher) stopWatcher();
      try { proc.kill(); } catch {}
      resolve({ strategy: strategyName, trial: trialNum, ...result, timings });
    };

    // Start broadcast JSONL watcher immediately — monitors ALL sessions
    stopWatcher = watchAllSessions(started, {
      onSessionDetected: (id) => {
        log(`session: ${id}`);
      },
      onUserMessage: (evt) => {
        timings.userMessageAt = Date.now();
        log(`✓ user.message (${((timings.userMessageAt - started) / 1000).toFixed(1)}s)`);
      },
      onAssistantMessage: (evt) => {
        timings.assistantMessageAt = Date.now();
        log(`✓ assistant.message (${((timings.assistantMessageAt - started) / 1000).toFixed(1)}s)`);
        cleanup({ pass: true });
      },
    });

    // PTY output handler
    let injected = false;
    let textEchoed = false;

    proc.onData((data) => {
      if (done) return;
      const clean = stripAnsi(data);

      if (verbose) {
        const oneLine = clean.replace(/\s+/g, " ").trim();
        if (oneLine) log(`stdout: ${oneLine.slice(0, 200)}`);
      }

      // Gate: wait for "Environment loaded:"
      if (!injected && READY_RE.test(clean)) {
        injected = true;
        timings.gateAt = Date.now();
        const gateDelay = timings.gateAt - started;
        log(`gate matched (${(gateDelay / 1000).toFixed(1)}s)`);

        // Small settle delay, then inject
        setTimeout(() => {
          if (done) return;
          timings.textWrittenAt = Date.now();
          log(`injecting: ${strategyName}`);
          strategies[strategyName](proc, prompt, null, timings);
        }, 300);
      }

      // Check for echo-back (for reporting, strategies also check internally)
      if (injected && !textEchoed && clean.includes(prompt.slice(0, 15))) {
        textEchoed = true;
        if (!timings.echoDetectedAt) timings.echoDetectedAt = Date.now();
      }
    });

    proc.onExit(({ exitCode }) => {
      log(`exit: ${exitCode}`);
      cleanup({ pass: !!timings.userMessageAt });
    });

    // Per-trial timeout
    timer = setTimeout(() => {
      log(`TIMEOUT (${timeoutMs / 1000}s)`);
      cleanup({
        pass: false,
        timeout: true,
        injected,
        textEchoed,
        userMessageSeen: !!timings.userMessageAt,
      });
    }, timeoutMs);
  });
}

// ── Main ──
console.log("\n╔══════════════════════════════════════════════════════════╗");
console.log("║         PTY Enter-Key Reliability Test                  ║");
console.log("╚══════════════════════════════════════════════════════════╝\n");
console.log(`  Model:    ${model}`);
console.log(`  Prompt:   "${prompt}"`);
console.log(`  Trials:   ${trials} per strategy`);
console.log(`  Timeout:  ${timeoutMs / 1000}s per trial`);
console.log(`  Agency:   ${agencyPath}`);
console.log(`  CWD:      ${testCwd}\n`);

const toRun = selectedStrategy === "all"
  ? Object.keys(strategies)
  : selectedStrategy.split(",").map(s => s.trim());

for (const name of toRun) {
  if (!strategies[name]) {
    console.error(`Unknown strategy: ${name}`);
    console.error(`Available: ${Object.keys(strategies).join(", ")}`);
    process.exit(2);
  }
}

const allResults = [];

for (const name of toRun) {
  console.log(`\n  Strategy: ${name}`);
  console.log("  " + "─".repeat(50));

  for (let t = 1; t <= trials; t++) {
    const result = await runTrial(name, t);
    allResults.push(result);

    const icon = result.pass ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m";
    const reason = result.timings.enterReason || "n/a";
    const echoMs = result.timings.echoDetectedAt && result.timings.textWrittenAt
      ? `${result.timings.echoDetectedAt - result.timings.textWrittenAt}ms`
      : "n/a";
    const submitMs = result.timings.userMessageAt && result.timings.enterSentAt
      ? `${result.timings.userMessageAt - result.timings.enterSentAt}ms`
      : "n/a";
    console.log(`    ${icon} trial ${t}: enter=${reason} echo-lag=${echoMs} submit-lag=${submitMs}${result.timeout ? " TIMEOUT" : ""}`);

    // Wait between trials to avoid session-state collisions
    if (t < trials) await new Promise(r => setTimeout(r, 3000));
  }

  // Wait between strategies
  if (toRun.indexOf(name) < toRun.length - 1) {
    await new Promise(r => setTimeout(r, 3000));
  }
}

// ── Results table ──
console.log("\n\n╔══════════════════════════════════════════════════════════════════════════╗");
console.log("║                         RESULTS SUMMARY                                ║");
console.log("╠══════════════════════════════════════════════════════════════════════════╣");
console.log("║ Strategy             │ Pass │ Fail │ Rate  │ Avg Echo │ Enter Reason    ║");
console.log("╠══════════════════════╪══════╪══════╪═══════╪══════════╪═════════════════╣");

const summaries = [];
for (const name of toRun) {
  const stratResults = allResults.filter(r => r.strategy === name);
  const passed = stratResults.filter(r => r.pass).length;
  const failed = stratResults.length - passed;
  const rate = ((passed / stratResults.length) * 100).toFixed(0);

  // Average echo-back latency (time from text write to echo detection)
  const echoLags = stratResults
    .filter(r => r.timings.echoDetectedAt && r.timings.textWrittenAt)
    .map(r => r.timings.echoDetectedAt - r.timings.textWrittenAt);
  const avgEcho = echoLags.length > 0
    ? `${Math.round(echoLags.reduce((a, b) => a + b, 0) / echoLags.length)}ms`
    : "n/a";

  // Most common enter reason
  const reasons = stratResults.map(r => r.timings.enterReason).filter(Boolean);
  const reason = reasons[0] || "n/a";

  const rateColor = rate === "100" ? "\x1b[32m" : rate === "0" ? "\x1b[31m" : "\x1b[33m";
  console.log(
    `║ ${name.padEnd(20)} │ ${String(passed).padStart(4)} │ ${String(failed).padStart(4)} │ ${rateColor}${rate.padStart(4)}%\x1b[0m │ ${avgEcho.padStart(8)} │ ${reason.padEnd(15)} ║`
  );

  summaries.push({ strategy: name, passed, failed, rate: Number(rate), avgEchoMs: echoLags.length ? Math.round(echoLags.reduce((a, b) => a + b, 0) / echoLags.length) : null, enterReason: reason });
}

console.log("╚══════════════════════╧══════╧══════╧═══════╧══════════╧═════════════════╝");

// ── Detailed timing breakdown ──
console.log("\n  Detailed Timings (per trial):");
console.log("  " + "─".repeat(70));
for (const r of allResults) {
  const t = r.timings;
  const gate = t.gateAt ? `gate=${((t.gateAt - t.spawnAt) / 1000).toFixed(1)}s` : "gate=n/a";
  const echo = t.echoDetectedAt && t.textWrittenAt
    ? `echo=${t.echoDetectedAt - t.textWrittenAt}ms`
    : "echo=n/a";
  const enter = t.enterSentAt && t.textWrittenAt
    ? `enter=${t.enterSentAt - t.textWrittenAt}ms`
    : "enter=n/a";
  const submit = t.userMessageAt && t.enterSentAt
    ? `submit=${((t.userMessageAt - t.enterSentAt) / 1000).toFixed(1)}s`
    : "submit=n/a";
  const total = t.userMessageAt
    ? `total=${((t.userMessageAt - t.spawnAt) / 1000).toFixed(1)}s`
    : "total=n/a";
  const icon = r.pass ? "✓" : "✗";
  console.log(`  ${icon} ${r.strategy.padEnd(22)} #${r.trial} ${gate} ${echo} ${enter} ${submit} ${total}`);
}

// ── Recommendation ──
const best = summaries.sort((a, b) => {
  if (b.rate !== a.rate) return b.rate - a.rate;
  // Tie-break: prefer lower average echo latency (faster)
  return (a.avgEchoMs || Infinity) - (b.avgEchoMs || Infinity);
})[0];

console.log("\n  ─────────────────────────────────────────────────────────");
if (best.rate === 100) {
  console.log(`  \x1b[32m✓ RECOMMENDATION: "${best.strategy}" — 100% reliable across ${trials} trials\x1b[0m`);
} else if (best.rate > 0) {
  console.log(`  \x1b[33m~ BEST: "${best.strategy}" at ${best.rate}% — not fully reliable\x1b[0m`);
} else {
  console.log(`  \x1b[31m✗ ALL STRATEGIES FAILED — investigate PTY output with --verbose\x1b[0m`);
}
console.log();

// ── Write JSON results ──
if (writeJson) {
  const outPath = path.join(__dirname, "pty-enter-results.json");
  const output = {
    timestamp: new Date().toISOString(),
    config: { model, prompt, trials, timeoutMs },
    summaries,
    trials: allResults.map(r => ({
      strategy: r.strategy,
      trial: r.trial,
      pass: r.pass,
      timeout: r.timeout || false,
      timings: {
        gateMs: r.timings.gateAt ? r.timings.gateAt - r.timings.spawnAt : null,
        echoMs: r.timings.echoDetectedAt && r.timings.textWrittenAt
          ? r.timings.echoDetectedAt - r.timings.textWrittenAt : null,
        enterMs: r.timings.enterSentAt && r.timings.textWrittenAt
          ? r.timings.enterSentAt - r.timings.textWrittenAt : null,
        submitMs: r.timings.userMessageAt && r.timings.enterSentAt
          ? r.timings.userMessageAt - r.timings.enterSentAt : null,
        totalMs: r.timings.userMessageAt
          ? r.timings.userMessageAt - r.timings.spawnAt : null,
        enterReason: r.timings.enterReason,
      },
    })),
  };
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2));
  console.log(`  Results written to: ${outPath}\n`);
}

// Exit code
const anyPerfect = summaries.some(s => s.rate === 100);
process.exit(anyPerfect ? 0 : 1);
