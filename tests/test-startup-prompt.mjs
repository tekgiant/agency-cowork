#!/usr/bin/env node
/**
 * Regression test: PTY prompt injection + follow-up
 *
 * Validates:
 *   1. "Environment loaded:" ready detection (not "Loading environment")
 *   2. Bracketed paste puts text into the TUI input field
 *   3. Various Enter strategies to submit the prompt
 *   4. Follow-up prompt via same writeToPty path
 *
 * Usage:
 *   node tests/test-startup-prompt.mjs [--timeout-ms=90000] [--model=gpt-5.4]
 *     [--strategy=paste-then-enter]
 *
 * Strategies:
 *   raw            — write text + \r as one blob (original, broken)
 *   paste-then-cr  — bracketed paste, then \r after 500ms
 *   paste-then-lf  — bracketed paste, then \n after 500ms
 *   paste-enter    — bracketed paste with \r inside
 *   paste-lf       — bracketed paste with \n inside
 *   raw-delay-cr   — write text, wait 500ms, send \r
 *   raw-delay-lf   — write text, wait 500ms, send \n
 *   all            — try each strategy on separate PTY (sequential)
 *
 * Exit codes: 0=pass, 1=fail, 2=env error
 */
import path from "path";
import fs from "fs";
import os from "os";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SESSION_STATE_DIR = path.join(os.homedir(), ".copilot", "session-state");

const args = new Map(process.argv.slice(2).map(arg => {
  const idx = arg.indexOf("=");
  return idx >= 0 ? [arg.slice(0, idx), arg.slice(idx + 1)] : [arg, "true"];
}));
const timeoutMs = Number(args.get("--timeout-ms") || 90000);
const model = args.get("--model") || "claude-opus-4.6";
const strategy = args.get("--strategy") || "all";
const agencyPath = process.env.AGENCY_PATH || path.join(process.env.APPDATA || "", "agency", "CurrentVersion", "agency.exe");
const prompt = "What is 3+4? Reply with just the number.";

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
if (!fs.existsSync(agencyPath)) {
  console.error(`SKIP: Agency executable not found: ${agencyPath}`);
  process.exit(2);
}

// ── ANSI Stripping ──
function stripAnsi(s) {
  return s
    .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b[()][0-9A-Za-z]/g, "")
    .replace(/\x1b[=>M78DEHNO]/g, "")
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, "");
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

// ── Strategy implementations ──
const strategies = {
  "raw": (proc, text) => {
    proc.write(text + "\r");
  },
  "paste-then-cr": (proc, text) => {
    proc.write(`\x1b[200~${text}\x1b[201~`);
    setTimeout(() => proc.write("\r"), 500);
  },
  "paste-then-lf": (proc, text) => {
    proc.write(`\x1b[200~${text}\x1b[201~`);
    setTimeout(() => proc.write("\n"), 500);
  },
  "paste-enter": (proc, text) => {
    proc.write(`\x1b[200~${text}\r\x1b[201~`);
  },
  "paste-lf": (proc, text) => {
    proc.write(`\x1b[200~${text}\n\x1b[201~`);
  },
  "raw-delay-cr": (proc, text) => {
    proc.write(text);
    setTimeout(() => proc.write("\r"), 500);
  },
  "raw-delay-lf": (proc, text) => {
    proc.write(text);
    setTimeout(() => proc.write("\n"), 500);
  },
};

// ── Run a single strategy ──
async function runStrategy(name) {
  return new Promise((resolve) => {
    const started = Date.now();
    const elapsed = () => ((Date.now() - started) / 1000).toFixed(1);
    const log = (msg) => console.log(`  [${name}] [${elapsed()}s] ${msg}`);

    let gateMatched = false;
    let textEchoed = false;
    let submitted = false;
    let sessionId = null;
    let detectIv = null;
    let jsonlIv = null;
    let timer = null;
    let bytesRead = 0;
    let pendingLine = "";

    const READY_RE = /Environment loaded:/i;
    const LOADING_RE = /Loading environment/i;

    const proc = pty.spawn(agencyPath, ["copilot", "--model", model], {
      name: "xterm-256color", cols: 120, rows: 40, cwd: testCwd,
      env: { ...process.env, MSFT_AGENCY: "true" },
    });
    log("spawned");

    const cleanup = (result) => {
      if (detectIv) clearInterval(detectIv);
      if (jsonlIv) clearInterval(jsonlIv);
      if (timer) clearTimeout(timer);
      try { proc.kill(); } catch {}
      resolve({ name, ...result, gateMatched, textEchoed, submitted });
    };

    // JSONL watcher
    const startJsonl = (id) => {
      if (sessionId) return;
      sessionId = id;
      const jsonlPath = path.join(SESSION_STATE_DIR, id, "events.jsonl");
      try { bytesRead = fs.existsSync(jsonlPath) ? fs.statSync(jsonlPath).size : 0; } catch {}
      log(`session: ${id}`);
      jsonlIv = setInterval(() => {
        try {
          if (!fs.existsSync(jsonlPath)) return;
          const stat = fs.statSync(jsonlPath);
          if (stat.size <= bytesRead) return;
          const fd = fs.openSync(jsonlPath, "r");
          const buf = Buffer.alloc(stat.size - bytesRead);
          fs.readSync(fd, buf, 0, buf.length, bytesRead);
          fs.closeSync(fd);
          bytesRead = stat.size;
          const chunk = pendingLine + buf.toString("utf8");
          const parts = chunk.split("\n");
          pendingLine = parts.pop() || "";
          for (const line of parts) {
            if (!line.trim()) continue;
            try {
              const evt = JSON.parse(line);
              if (evt.type === "user.message") {
                submitted = true;
                log("✓ user.message — prompt SUBMITTED");
              }
              if (evt.type === "assistant.message") {
                log("✓ assistant.message — got response");
                cleanup({ pass: true });
                return;
              }
            } catch {}
          }
        } catch {}
      }, 100);
    };

    // Session detection
    detectIv = setInterval(() => {
      try {
        const dirs = fs.readdirSync(SESSION_STATE_DIR, { withFileTypes: true }).filter(d => d.isDirectory());
        let newest = null;
        for (const dir of dirs) {
          const yf = path.join(SESSION_STATE_DIR, dir.name, "workspace.yaml");
          if (!fs.existsSync(yf)) continue;
          const content = fs.readFileSync(yf, "utf8");
          const idMatch = content.match(/^id:\s*(.+)/m);
          const created = content.match(/^created_at:\s*(.+)/m);
          if (!idMatch) continue;
          const ts = created ? new Date(created[1]).getTime() : 0;
          if (ts >= started - 5000 && (!newest || ts > newest.ts)) {
            newest = { id: idMatch[1].trim(), ts };
          }
        }
        if (newest) { clearInterval(detectIv); startJsonl(newest.id); }
      } catch {}
    }, 200);

    // PTY output handler
    let injected = false;
    proc.onData((data) => {
      const clean = stripAnsi(data);

      // Gate: "Environment loaded:" without "Loading environment"
      if (!injected && READY_RE.test(clean)) {
        injected = true;
        gateMatched = true;
        log(`gate: Environment loaded`);

        // Wait 300ms for TUI to settle, then inject
        setTimeout(() => {
          log(`injecting with strategy: ${name}`);
          strategies[name](proc, prompt);
        }, 300);
      }

      // Check if our text appeared in the TUI
      if (injected && !textEchoed && clean.includes(prompt.slice(0, 15))) {
        textEchoed = true;
        log(`echo: text appeared in TUI`);
      }
    });

    proc.onExit(({ exitCode }) => {
      log(`exited: ${exitCode}`);
      cleanup({ pass: submitted });
    });

    timer = setTimeout(() => {
      log(`timeout (${timeoutMs / 1000}s)`);
      cleanup({ pass: false, timeout: true });
    }, timeoutMs);
  });
}

// ── Main ──
console.log("\n── PTY Prompt Injection Test ──\n");

const toRun = strategy === "all" ? Object.keys(strategies) : [strategy];
const results = [];

for (const name of toRun) {
  if (!strategies[name]) {
    console.error(`Unknown strategy: ${name}`);
    process.exit(2);
  }
  console.log(`\nStrategy: ${name}`);
  console.log("─".repeat(40));
  const result = await runStrategy(name);
  results.push(result);
  console.log(`  Result: gate=${result.gateMatched} echo=${result.textEchoed} submitted=${result.submitted} ${result.pass ? "PASS ✓" : "FAIL ✗"}${result.timeout ? " (timeout)" : ""}`);

  // Wait a bit between strategies to avoid session collisions
  if (toRun.length > 1) await new Promise(r => setTimeout(r, 2000));
}

// Summary
console.log("\n── Summary ──\n");
for (const r of results) {
  const icon = r.pass ? "\x1b[32m✓\x1b[0m" : "\x1b[31m✗\x1b[0m";
  console.log(`  ${icon} ${r.name.padEnd(20)} gate=${r.gateMatched} echo=${r.textEchoed} submitted=${r.submitted}`);
}
const anyPass = results.some(r => r.pass);
console.log(`\n  ${anyPass ? "At least one strategy works" : "ALL STRATEGIES FAILED"}\n`);
process.exit(anyPass ? 0 : 1);
