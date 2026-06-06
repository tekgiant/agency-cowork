#!/usr/bin/env node
// qmd-mcp-adapter.js — Protocol framing adapter for QMD MCP server
//
// GitHub Copilot CLI sends MCP messages using Content-Length framing (LSP-style):
//   Content-Length: 234\r\n\r\n{...json...}
//
// MCP SDK v1.25+ (used by QMD v1.x and v2.x) uses NDJSON framing:
//   {...json...}\n
//
// This adapter sits between Copilot CLI and qmd, translating in both directions.
// It auto-detects the client's framing format so it's a no-op if Copilot CLI
// is updated to speak NDJSON natively.
//
// Usage (mcp-config.json / .mcp.json):
//   "command": "node",
//   "args": ["/abs/path/to/scripts/qmd-mcp-adapter.js", "--", "node", "/abs/path/to/qmd.js", "mcp"]
//
// The args after "--" are passed directly to spawn().

"use strict";
const { spawn } = require("child_process");

const argv = process.argv.slice(2);
const sepIdx = argv.indexOf("--");
const cmdArgs = sepIdx >= 0 ? argv.slice(sepIdx + 1) : argv;

if (cmdArgs.length === 0) {
  process.stderr.write("qmd-mcp-adapter: no command specified. Usage: node qmd-mcp-adapter.js -- <cmd> [args...]\n");
  process.exit(1);
}

const child = spawn(cmdArgs[0], cmdArgs.slice(1), {
  stdio: ["pipe", "pipe", "inherit"],
  windowsHide: true,
});

child.on("error", (err) => {
  process.stderr.write(`qmd-mcp-adapter: failed to spawn '${cmdArgs[0]}': ${err.message}\n`);
  process.exit(1);
});
// Use 'close' (not 'exit') so all stdio streams are fully drained before exit
child.on("close", (code) => process.exit(code ?? 0));

// ── stdin: Copilot CLI → child ──────────────────────────────────────────────
// Detect format on first chunk, then translate Content-Length → NDJSON if needed.
let stdinFormat = null; // "cl" | "ndjson"
let stdinBuf = Buffer.alloc(0);

process.stdin.on("data", (chunk) => {
  stdinBuf = Buffer.concat([stdinBuf, chunk]);

  if (!stdinFormat) {
    const peek = stdinBuf.slice(0, 20).toString("ascii");
    if (peek.startsWith("Content-Length:")) stdinFormat = "cl";
    else if (peek.trimStart().startsWith("{")) stdinFormat = "ndjson";
    else return; // wait for more data
  }

  if (stdinFormat === "cl") {
    // Parse one or more Content-Length frames, emit each body as an NDJSON line
    while (stdinBuf.length > 0) {
      const headerEnd = crlfcrlfIndex(stdinBuf);
      if (headerEnd === -1) break;

      const header = stdinBuf.slice(0, headerEnd).toString("ascii");
      const clMatch = header.match(/Content-Length:\s*(\d+)/i);
      if (!clMatch) { stdinBuf = stdinBuf.slice(headerEnd + 4); continue; }

      const bodyLen = parseInt(clMatch[1], 10);
      const bodyStart = headerEnd + 4;
      if (stdinBuf.length < bodyStart + bodyLen) break;

      const body = stdinBuf.slice(bodyStart, bodyStart + bodyLen);
      child.stdin.write(body);
      child.stdin.write("\n");
      stdinBuf = stdinBuf.slice(bodyStart + bodyLen);
    }
  } else {
    // Already NDJSON — pass through unchanged
    child.stdin.write(stdinBuf);
    stdinBuf = Buffer.alloc(0);
  }
});
process.stdin.on("end", () => child.stdin.end());

// ── stdout: child → Copilot CLI ─────────────────────────────────────────────
// Detect format on first chunk, then translate NDJSON → Content-Length if needed.
let stdoutFormat = null; // "cl" | "ndjson"
let stdoutBuf = Buffer.alloc(0);

child.stdout.on("data", (chunk) => {
  stdoutBuf = Buffer.concat([stdoutBuf, chunk]);

  if (!stdoutFormat) {
    const peek = stdoutBuf.slice(0, 20).toString("ascii");
    if (peek.startsWith("Content-Length:")) stdoutFormat = "cl";
    else if (peek.trimStart().startsWith("{")) stdoutFormat = "ndjson";
    else return;
  }

  if (stdoutFormat === "ndjson") {
    // Split on newlines, wrap each JSON line with Content-Length header
    let nlIdx;
    while ((nlIdx = stdoutBuf.indexOf(0x0a)) !== -1) {
      const line = stdoutBuf.slice(0, nlIdx);
      stdoutBuf = stdoutBuf.slice(nlIdx + 1);
      if (line.length === 0) continue;
      process.stdout.write(`Content-Length: ${line.length}\r\n\r\n`);
      process.stdout.write(line);
    }
  } else {
    // Already Content-Length framed — pass through unchanged
    process.stdout.write(stdoutBuf);
    stdoutBuf = Buffer.alloc(0);
  }
});

// Flush any unterminated final line when child stdout closes
child.stdout.on("end", () => {
  const remaining = stdoutBuf.toString().trimEnd();
  if (remaining.length > 0 && stdoutFormat === "ndjson") {
    const line = Buffer.from(remaining);
    process.stdout.write(`Content-Length: ${line.length}\r\n\r\n`);
    process.stdout.write(line);
  }
  stdoutBuf = Buffer.alloc(0);
});

function crlfcrlfIndex(buf) {
  for (let i = 0; i <= buf.length - 4; i++) {
    if (buf[i] === 0x0d && buf[i + 1] === 0x0a && buf[i + 2] === 0x0d && buf[i + 3] === 0x0a) return i;
  }
  return -1;
}
