#!/usr/bin/env node
// ──────────────────────────────────────────────────────────────────────────────
// Dashboard Skill — Offline Regression Tests
// Date:    2026-04-06
// Covers:  Skill metadata, IPC path validation, content CRUD security,
//          scanMemoryDirectory logic, patchFrontmatter YAML handling
// ──────────────────────────────────────────────────────────────────────────────

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const REPO = path.resolve(import.meta.dirname, "..");
const SKILL_ROOT = path.join(REPO, "skills", "dashboard");

// ── 1. Skill Metadata ───────────────────────────────────────────────────────

describe("Dashboard skill metadata", () => {
  it("skill.json is valid JSON with required fields", () => {
    const raw = fs.readFileSync(path.join(SKILL_ROOT, "skill.json"), "utf-8");
    const obj = JSON.parse(raw);
    assert.equal(obj.name, "dashboard");
    assert.ok(obj.version, "version missing");
    assert.ok(obj.description, "description missing");
  });

  it("plugin.json is valid JSON with required fields", () => {
    const raw = fs.readFileSync(path.join(SKILL_ROOT, ".claude-plugin", "plugin.json"), "utf-8");
    const obj = JSON.parse(raw);
    assert.equal(obj.name, "dashboard");
    assert.ok(obj.version);
    assert.ok(obj.description);
    assert.ok(Array.isArray(obj.keywords) && obj.keywords.length > 0, "keywords missing");
    assert.equal(obj.author?.name, "Agency Cowork");
  });

  it("SKILL.md exists and has YAML frontmatter with name + description", () => {
    const raw = fs.readFileSync(path.join(SKILL_ROOT, "skills", "dashboard", "SKILL.md"), "utf-8");
    assert.ok(raw.startsWith("---"), "SKILL.md must start with ---");
    const fmEnd = raw.indexOf("---", 4);
    assert.ok(fmEnd > 3, "No closing --- in frontmatter");
    const fm = raw.slice(4, fmEnd);
    assert.ok(/^name:\s/m.test(fm), "frontmatter missing name:");
    assert.ok(/^description:\s/m.test(fm), "frontmatter missing description:");
  });

  it("commands/customize.md exists and is non-empty", () => {
    const p = path.join(SKILL_ROOT, "commands", "customize.md");
    assert.ok(fs.existsSync(p), "customize.md missing");
    assert.ok(fs.readFileSync(p, "utf-8").length > 50, "customize.md too short");
  });

  it("starter template exists", () => {
    assert.ok(fs.existsSync(path.join(SKILL_ROOT, "templates", "dashboard.html")));
  });
});

// ── 2. Path Validation (extracted from main.js:validateDashboardPath) ────────

function validateDashboardPath(workDir, filePath) {
  const memRoot = path.join(workDir, "memory");
  const resolved = path.isAbsolute(filePath) ? filePath : path.join(memRoot, filePath);
  const normalized = path.normalize(resolved);
  if (!normalized.startsWith(path.normalize(memRoot))) {
    return { error: "Access denied: path must be within memory/" };
  }
  const rel = path.relative(memRoot, normalized).replace(/\\/g, "/");
  if (/^Dashboards\/[^/]+\.html$/i.test(rel)) {
    return { error: "Cannot modify dashboard HTML files via content API" };
  }
  return { normalized, relative: rel, memRoot };
}

describe("validateDashboardPath — security", () => {
  const workDir = "C:\\cowork\\agency-cowork";

  // Note: validateDashboardPath joins filePath with memRoot (workDir/memory/).
  // Relative paths are resolved against memory/, so pass paths relative to memory/.

  it("allows normal memory paths", () => {
    const r = validateDashboardPath(workDir, "Knowledgebase/article.md");
    assert.ok(!r.error, `unexpected error: ${r.error}`);
    assert.ok(r.relative.includes("Knowledgebase/article.md"));
  });

  it("blocks path traversal above memory/", () => {
    const r = validateDashboardPath(workDir, "../secrets.txt");
    assert.ok(r.error, "should block traversal");
    assert.match(r.error, /Access denied/);
  });

  it("blocks double-dot traversal to workDir root", () => {
    const r = validateDashboardPath(workDir, "../../etc/passwd");
    assert.ok(r.error, "should block deep traversal");
    assert.match(r.error, /Access denied/);
  });

  it("blocks absolute path outside memory/", () => {
    const r = validateDashboardPath(workDir, "C:\\Windows\\System32\\cmd.exe");
    assert.ok(r.error, "should block absolute path outside memory");
    assert.match(r.error, /Access denied/);
  });

  it("blocks writes to Dashboards/*.html", () => {
    const r = validateDashboardPath(workDir, "Dashboards/my-dash.html");
    assert.ok(r.error, "should block dashboard HTML writes");
    assert.match(r.error, /Cannot modify dashboard HTML/);
  });

  it("allows writes to Dashboards/*.json (non-html)", () => {
    const r = validateDashboardPath(workDir, "Dashboards/.debug-data.json");
    assert.ok(!r.error, `unexpected error: ${r.error}`);
  });

  it("allows writes to Dashboards/subdir/file.html (nested, not top-level)", () => {
    const r = validateDashboardPath(workDir, "Dashboards/archive/old.html");
    assert.ok(!r.error, `unexpected error: ${r.error}`);
  });
});

// ── 3. scanMemoryDirectory (extracted logic) ─────────────────────────────────

const DASHBOARD_TEXT_EXTS = new Set([".md", ".json", ".txt", ".csv", ".yaml", ".yml", ".toml", ".xml", ".html", ".htm"]);
const DASHBOARD_MAX_CONTENT = 30000;
const DASHBOARD_IGNORE = new Set(["Dashboards", ".git", "node_modules", "__pycache__"]);

function scanMemoryDirectory(memRoot) {
  const tree = {};
  if (!fs.existsSync(memRoot)) return tree;

  for (const entry of fs.readdirSync(memRoot, { withFileTypes: true })) {
    if (entry.name.startsWith(".") || DASHBOARD_IGNORE.has(entry.name)) continue;

    if (entry.isDirectory()) {
      const catDir = path.join(memRoot, entry.name);
      const files = [];
      const walk = (dir) => {
        let entries;
        try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
        for (const e of entries) {
          const full = path.join(dir, e.name);
          if (e.isDirectory()) {
            if (!e.name.startsWith(".") && !DASHBOARD_IGNORE.has(e.name)) walk(full);
            continue;
          }
          if (!e.isFile()) continue;
          const ext = path.extname(e.name).toLowerCase();
          if (!DASHBOARD_TEXT_EXTS.has(ext)) continue;
          try {
            const stat = fs.statSync(full);
            let content = "";
            let truncated = false;
            try {
              const raw = fs.readFileSync(full, "utf-8");
              if (raw.length > DASHBOARD_MAX_CONTENT) { content = raw.slice(0, DASHBOARD_MAX_CONTENT); truncated = true; }
              else content = raw;
            } catch {}
            files.push({
              name: path.basename(e.name, ext).replace(/[-_]/g, " "),
              filename: e.name,
              ext,
              path: path.relative(catDir, full).replace(/\\/g, "/"),
              absPath: full.replace(/\\/g, "/"),
              sizeKB: Math.round(stat.size / 1024 * 10) / 10,
              modifiedAt: stat.mtime.toISOString(),
              content,
              truncated,
            });
          } catch {}
        }
      };
      walk(catDir);
      const sorted = files.sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt));
      const newest = sorted.length ? sorted[0].modifiedAt : null;
      tree[entry.name] = { name: entry.name, count: files.length, newest, files: sorted };
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name).toLowerCase();
      if (!DASHBOARD_TEXT_EXTS.has(ext)) continue;
      try {
        const full = path.join(memRoot, entry.name);
        const stat = fs.statSync(full);
        let content = "";
        let truncated = false;
        try {
          const raw = fs.readFileSync(full, "utf-8");
          if (raw.length > DASHBOARD_MAX_CONTENT) { content = raw.slice(0, DASHBOARD_MAX_CONTENT); truncated = true; }
          else content = raw;
        } catch {}
        if (!tree["_root"]) tree["_root"] = { name: "_root", count: 0, newest: null, files: [] };
        tree["_root"].files.push({
          name: path.basename(entry.name, ext).replace(/[-_]/g, " "),
          filename: entry.name,
          ext,
          path: entry.name,
          absPath: full.replace(/\\/g, "/"),
          sizeKB: Math.round(stat.size / 1024 * 10) / 10,
          modifiedAt: stat.mtime.toISOString(),
          content,
          truncated,
        });
        tree["_root"].count++;
        if (!tree["_root"].newest || stat.mtime.toISOString() > tree["_root"].newest) {
          tree["_root"].newest = stat.mtime.toISOString();
        }
      } catch {}
    }
  }
  return tree;
}

describe("scanMemoryDirectory", () => {
  let tmpDir;

  before(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "dash-test-"));
    // Build a test memory/ tree
    const mem = path.join(tmpDir, "memory");
    fs.mkdirSync(path.join(mem, "Knowledgebase", "Workstreams"), { recursive: true });
    fs.mkdirSync(path.join(mem, "DailyLogs"), { recursive: true });
    fs.mkdirSync(path.join(mem, "Dashboards"), { recursive: true });
    fs.mkdirSync(path.join(mem, ".git"), { recursive: true });

    fs.writeFileSync(path.join(mem, "MEMORY.md"), "# Memory\nUser profile here");
    fs.writeFileSync(path.join(mem, "Knowledgebase", "article.md"), "# Article\nContent");
    fs.writeFileSync(path.join(mem, "Knowledgebase", "data.json"), '{"key":"value"}');
    fs.writeFileSync(path.join(mem, "Knowledgebase", "Workstreams", "ws1.md"), "# WS1");
    fs.writeFileSync(path.join(mem, "Knowledgebase", "photo.png"), "binary-data");
    fs.writeFileSync(path.join(mem, "DailyLogs", "2026-04-06.md"), "# Today");
    fs.writeFileSync(path.join(mem, "Dashboards", "my-dash.html"), "<html>hi</html>");
    fs.writeFileSync(path.join(mem, ".git", "HEAD"), "ref: refs/heads/main");
  });

  after(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns categories for top-level directories", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    assert.ok(tree["Knowledgebase"], "Knowledgebase category missing");
    assert.ok(tree["DailyLogs"], "DailyLogs category missing");
  });

  it("excludes Dashboards, .git, node_modules from categories", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    assert.equal(tree["Dashboards"], undefined, "Dashboards should be excluded");
    assert.equal(tree[".git"], undefined, ".git should be excluded");
  });

  it("puts root-level files into _root", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    assert.ok(tree["_root"], "_root missing");
    const rootFiles = tree["_root"].files.map(f => f.filename);
    assert.ok(rootFiles.includes("MEMORY.md"), "MEMORY.md should be in _root");
  });

  it("includes nested subdirectory files under parent category", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    const kb = tree["Knowledgebase"];
    const paths = kb.files.map(f => f.path);
    assert.ok(paths.includes("Workstreams/ws1.md"), "Workstream file should be under Knowledgebase");
  });

  it("excludes non-text files (e.g., .png)", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    const kb = tree["Knowledgebase"];
    const exts = kb.files.map(f => f.ext);
    assert.ok(!exts.includes(".png"), ".png should not be included");
  });

  it("counts files correctly", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    // article.md + data.json + Workstreams/ws1.md = 3
    assert.equal(tree["Knowledgebase"].count, 3);
    assert.equal(tree["DailyLogs"].count, 1);
    assert.equal(tree["_root"].count, 1);
  });

  it("reads file content inline", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    const article = tree["Knowledgebase"].files.find(f => f.filename === "article.md");
    assert.ok(article, "article.md not found");
    assert.ok(article.content.includes("# Article"), "content should be loaded");
    assert.equal(article.truncated, false);
  });

  it("truncates content exceeding 30KB and sets truncated flag", () => {
    // Write a large file
    const bigFile = path.join(tmpDir, "memory", "Knowledgebase", "big.txt");
    fs.writeFileSync(bigFile, "x".repeat(40000));

    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    const big = tree["Knowledgebase"].files.find(f => f.filename === "big.txt");
    assert.ok(big, "big.txt not found");
    assert.equal(big.truncated, true);
    assert.equal(big.content.length, DASHBOARD_MAX_CONTENT);

    // Cleanup
    fs.unlinkSync(bigFile);
  });

  it("name field strips extension and replaces hyphens/underscores with spaces", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "memory"));
    const dl = tree["DailyLogs"].files.find(f => f.filename === "2026-04-06.md");
    assert.equal(dl.name, "2026 04 06");
  });

  it("returns empty tree for non-existent memory/", () => {
    const tree = scanMemoryDirectory(path.join(tmpDir, "nope"));
    assert.deepEqual(tree, {});
  });
});

// ── 4. patchFrontmatter YAML logic (extracted) ──────────────────────────────

function patchFrontmatter(content, fields) {
  const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!fmMatch) {
    const lines = Object.entries(fields).map(([k, val]) => `${k}: ${JSON.stringify(val)}`);
    return `---\n${lines.join("\n")}\n---\n${content}`;
  }
  let fmBlock = fmMatch[1];
  for (const [key, val] of Object.entries(fields)) {
    const keyRegex = new RegExp(`^${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:.*$`, "m");
    const newLine = `${key}: ${JSON.stringify(val)}`;
    if (keyRegex.test(fmBlock)) {
      fmBlock = fmBlock.replace(keyRegex, newLine);
    } else {
      fmBlock = fmBlock.trimEnd() + "\n" + newLine;
    }
  }
  return content.replace(/^---\r?\n[\s\S]*?\r?\n---/, `---\n${fmBlock}\n---`);
}

describe("patchFrontmatter", () => {
  it("creates frontmatter when none exists", () => {
    const result = patchFrontmatter("# Hello\nBody", { status: "active" });
    assert.ok(result.startsWith("---\n"), "should start with ---");
    assert.ok(result.includes('status: "active"'));
    assert.ok(result.includes("# Hello\nBody"));
  });

  it("updates an existing field", () => {
    const input = '---\nstatus: "draft"\ntitle: "My Doc"\n---\n# Hello';
    const result = patchFrontmatter(input, { status: "complete" });
    assert.ok(result.includes('status: "complete"'));
    assert.ok(!result.includes('"draft"'));
    assert.ok(result.includes('title: "My Doc"'));
  });

  it("adds a new field to existing frontmatter", () => {
    const input = '---\nstatus: "draft"\n---\n# Hello';
    const result = patchFrontmatter(input, { priority: "high" });
    assert.ok(result.includes('status: "draft"'));
    assert.ok(result.includes('priority: "high"'));
  });

  it("handles multiple fields at once", () => {
    const input = '---\na: 1\n---\nBody';
    const result = patchFrontmatter(input, { a: 99, b: "new", c: true });
    assert.ok(result.includes("a: 99"));
    assert.ok(result.includes('b: "new"'));
    assert.ok(result.includes("c: true"));
  });
});

// ── 5. Template HTML correctness ─────────────────────────────────────────────

describe("Starter template", () => {
  let html;

  before(() => {
    html = fs.readFileSync(path.join(SKILL_ROOT, "templates", "dashboard.html"), "utf-8");
  });

  it("has postMessage bridge (dashboard-action channel)", () => {
    assert.ok(html.includes('"dashboard-action"'), "must post on dashboard-action channel");
  });

  it("has requestData function", () => {
    assert.ok(html.includes("function requestData"), "requestData() missing");
  });

  it("has startTask function", () => {
    assert.ok(html.includes("function startTask"), "startTask() missing");
  });

  it("has openFile function", () => {
    assert.ok(html.includes("function openFile"), "openFile() missing");
  });

  it("has saveFile function", () => {
    assert.ok(html.includes("function saveFile"), "saveFile() missing");
  });

  it("has deleteFile function", () => {
    assert.ok(html.includes("function deleteFile"), "deleteFile() missing");
  });

  it("has patchFrontmatter function", () => {
    assert.ok(html.includes("function patchFrontmatter"), "patchFrontmatter() missing");
  });

  it("has render function (called on data-payload)", () => {
    assert.ok(html.includes("function render"), "render() function missing");
  });

  it("listens for dashboard-data channel", () => {
    assert.ok(html.includes('"dashboard-data"'), "must listen on dashboard-data channel");
  });

  it("sends initial requestData on load", () => {
    assert.ok(html.includes("if (window.parent !== window) requestData()"), "auto-request on load missing");
  });

  it("handles data-payload message type", () => {
    assert.ok(html.includes('"data-payload"'), "data-payload handler missing");
  });

  it("handles data-changed message type", () => {
    assert.ok(html.includes('"data-changed"'), "data-changed handler missing");
  });

  it("has error boundary (try/catch around render)", () => {
    assert.ok(html.includes("catch") && html.includes("render"), "error boundary missing");
  });

  it("has console capture bridge (logToParent)", () => {
    assert.ok(html.includes("logToParent"), "console capture bridge missing");
  });

  it("supports dark mode (@media prefers-color-scheme)", () => {
    assert.ok(html.includes("prefers-color-scheme: dark"), "dark mode missing");
  });

  it("supports reduced-motion (@media prefers-reduced-motion)", () => {
    assert.ok(html.includes("prefers-reduced-motion"), "reduced-motion missing");
  });

  it("has CRUD result listeners (save-result, delete-result, patch-result)", () => {
    assert.ok(html.includes('"save-result"'), "save-result listener missing");
    assert.ok(html.includes('"delete-result"'), "delete-result listener missing");
    assert.ok(html.includes('"patch-result"'), "patch-result listener missing");
  });

  it("has timeout protection on CRUD promises (10s)", () => {
    assert.ok(html.includes("10000"), "10-second timeout missing");
  });
});

// ── 6. Preload API surface ───────────────────────────────────────────────────

describe("Preload exposes all dashboard APIs", () => {
  let preload;

  before(() => {
    preload = fs.readFileSync(path.join(REPO, "ui", "electron", "preload.js"), "utf-8");
  });

  const requiredAPIs = [
    "listDashboards", "getDashboard", "createDashboardFromTemplate",
    "saveDashboardOrder", "getDashboardData", "getDashboardFile",
    "saveDashboardFile", "deleteDashboardFile", "patchDashboardFrontmatter",
    "dumpDashboardData", "logDashboardConsole",
    "startDashboardWatcher", "stopDashboardWatcher", "onDashboardDataChanged",
  ];

  for (const api of requiredAPIs) {
    it(`exposes ${api}`, () => {
      assert.ok(preload.includes(api), `${api} missing from preload.js`);
    });
  }
});

// ── 7. IPC handlers registered in main.js ────────────────────────────────────

describe("main.js registers all dashboard IPC handlers", () => {
  let mainJs;

  before(() => {
    mainJs = fs.readFileSync(path.join(REPO, "ui", "electron", "main.js"), "utf-8");
  });

  const requiredHandlers = [
    "dashboard:getData", "dashboard:dumpData", "dashboard:logConsole",
    "dashboard:getFile", "dashboard:saveFile", "dashboard:deleteFile",
    "dashboard:patchFrontmatter", "dashboard:list", "dashboard:saveOrder",
    "dashboard:get", "dashboard:createFromTemplate",
    "dashboard:startWatcher", "dashboard:stopWatcher",
  ];

  for (const handler of requiredHandlers) {
    it(`registers ${handler}`, () => {
      assert.ok(mainJs.includes(`"${handler}"`), `${handler} handler missing from main.js`);
    });
  }
});
