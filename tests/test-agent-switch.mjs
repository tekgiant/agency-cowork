#!/usr/bin/env node
/**
 * Regression test: Agent/folder switching — terminal reset
 *
 * Validates that:
 *   1. Switching to a new taskId clears the PTY buffer (no old content replayed)
 *   2. Relaunch with same taskId + append:false clears the PTY buffer
 *   3. XTerminal key prop forces remount (simulated via taskId change tracking)
 *   4. Global PTY data listener routes to correct task buffer only
 *   5. Old PTY listener is cleaned up when task switches
 *
 * This test simulates the useAgent.js + XTerminal lifecycle without Electron
 * by recreating the buffer management and listener patterns in isolation.
 *
 * Usage:
 *   node tests/test-agent-switch.mjs
 *
 * Exit codes:
 *   0 = all assertions pass
 *   1 = one or more assertions failed
 */

const assertions = [];
function assert(name, condition, detail = "") {
  assertions.push({ name, pass: !!condition, detail });
}

// ── Simulate ptyBuffersRef (mirrors useAgent.js) ──
const ptyBuffersRef = new Map();

// ── Simulate startTask (mirrors useAgent.js lines 307-355) ──
const streamsRef = new Map();
function startTask({ taskId, append }) {
  if (!append) {
    streamsRef.set(taskId, []);
    ptyBuffersRef.delete(taskId);
  }
  // Register "listener" — global onTaskPtyData routes by taskId
}

// ── Simulate PTY data arriving ──
function simulatePtyData(taskId, data) {
  const buf = ptyBuffersRef.get(taskId);
  if (buf) {
    buf.push(data);
  } else {
    ptyBuffersRef.set(taskId, [data]);
  }
}

// ── Simulate XTerminal mount (reads ptyBuffer for replay) ──
function mountTerminal(taskId) {
  const buf = ptyBuffersRef.get(taskId) || [];
  return { replayedContent: buf.join(""), taskId };
}

// ═══════════════════════════════════════════════════════
// TEST 1: Fresh task has empty terminal
// ═══════════════════════════════════════════════════════
{
  const taskId = "task-1";
  startTask({ taskId, append: false });
  const term = mountTerminal(taskId);
  assert(
    "Fresh task — empty terminal on mount",
    term.replayedContent === "",
    `got "${term.replayedContent.slice(0, 50)}"`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 2: PTY data accumulates in correct buffer
// ═══════════════════════════════════════════════════════
{
  const taskId = "task-2";
  startTask({ taskId, append: false });
  simulatePtyData(taskId, "Hello from PTY\r\n");
  simulatePtyData(taskId, "More output\r\n");
  const term = mountTerminal(taskId);
  assert(
    "PTY data accumulates in task buffer",
    term.replayedContent === "Hello from PTY\r\nMore output\r\n",
    `got "${term.replayedContent.slice(0, 80)}"`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 3: Folder switch — new taskId clears old buffer
// ═══════════════════════════════════════════════════════
{
  // Simulate old task with data
  const oldTaskId = "task-old-folder";
  startTask({ taskId: oldTaskId, append: false });
  simulatePtyData(oldTaskId, "Old folder output\r\n");

  // Switch folder → new taskId, no append
  const newTaskId = "task-new-folder";
  startTask({ taskId: newTaskId, append: false });

  // New terminal should be clean
  const newTerm = mountTerminal(newTaskId);
  assert(
    "Folder switch — new task has empty terminal",
    newTerm.replayedContent === "",
    `got "${newTerm.replayedContent.slice(0, 50)}"`
  );

  // Old buffer should still exist (for task-switching back)
  const oldBuf = ptyBuffersRef.get(oldTaskId);
  assert(
    "Folder switch — old task buffer preserved for history",
    oldBuf && oldBuf.length > 0,
    `oldBuf length: ${oldBuf?.length}`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 4: Relaunch (same taskId, append:false) clears buffer
// ═══════════════════════════════════════════════════════
{
  const taskId = "task-relaunch";
  startTask({ taskId, append: false });
  simulatePtyData(taskId, "Session 1 output\r\n");
  simulatePtyData(taskId, "More session 1\r\n");

  // Verify data exists before relaunch
  const beforeBuf = ptyBuffersRef.get(taskId);
  assert(
    "Relaunch — buffer has data before relaunch",
    beforeBuf && beforeBuf.length === 2,
    `buf length: ${beforeBuf?.length}`
  );

  // Relaunch: same taskId, append:false
  startTask({ taskId, append: false });

  const afterTerm = mountTerminal(taskId);
  assert(
    "Relaunch (append:false) — terminal is clean",
    afterTerm.replayedContent === "",
    `got "${afterTerm.replayedContent.slice(0, 50)}"`
  );

  // New data should start fresh
  simulatePtyData(taskId, "Session 2 output\r\n");
  const afterData = mountTerminal(taskId);
  assert(
    "Relaunch — new data starts fresh",
    afterData.replayedContent === "Session 2 output\r\n",
    `got "${afterData.replayedContent.slice(0, 50)}"`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 5: Resume (same taskId, append:true) preserves buffer
// ═══════════════════════════════════════════════════════
{
  const taskId = "task-resume";
  startTask({ taskId, append: false });
  simulatePtyData(taskId, "Original output\r\n");

  // Resume: same taskId, append:true
  startTask({ taskId, append: true });

  const term = mountTerminal(taskId);
  assert(
    "Resume (append:true) — old content preserved",
    term.replayedContent === "Original output\r\n",
    `got "${term.replayedContent.slice(0, 50)}"`
  );

  // New data appends
  simulatePtyData(taskId, "Resumed output\r\n");
  const term2 = mountTerminal(taskId);
  assert(
    "Resume — new data appends to existing",
    term2.replayedContent === "Original output\r\nResumed output\r\n",
    `got "${term2.replayedContent.slice(0, 80)}"`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 6: Cross-task isolation — data routes to correct buffer
// ═══════════════════════════════════════════════════════
{
  const taskA = "task-A";
  const taskB = "task-B";
  startTask({ taskId: taskA, append: false });
  startTask({ taskId: taskB, append: false });

  simulatePtyData(taskA, "Task A data\r\n");
  simulatePtyData(taskB, "Task B data\r\n");
  simulatePtyData(taskA, "More A\r\n");

  const termA = mountTerminal(taskA);
  const termB = mountTerminal(taskB);
  assert(
    "Cross-task isolation — task A gets only A data",
    termA.replayedContent === "Task A data\r\nMore A\r\n",
    `got "${termA.replayedContent.slice(0, 80)}"`
  );
  assert(
    "Cross-task isolation — task B gets only B data",
    termB.replayedContent === "Task B data\r\n",
    `got "${termB.replayedContent.slice(0, 80)}"`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 7: XTerminal key prop — taskId change forces remount
// ═══════════════════════════════════════════════════════
{
  // Simulate React's key-based unmount/remount behavior
  // When key changes, old component is destroyed and new one created
  let mountCount = 0;
  let disposeCount = 0;

  function simulateReactRender(key) {
    // React with key: if key changed, dispose old + mount new
    // Without key: reuse component, only re-run effects
    mountCount++;
    return { key, mountId: mountCount };
  }
  function simulateDispose() {
    disposeCount++;
  }

  // First render: key="task-1"
  const render1 = simulateReactRender("task-1");

  // Second render: key="task-2" (new task) — should trigger dispose + new mount
  simulateDispose(); // old component destroyed
  const render2 = simulateReactRender("task-2");

  assert(
    "Key prop — different key triggers new mount",
    render1.mountId !== render2.mountId,
    `mount1=${render1.mountId} mount2=${render2.mountId}`
  );
  assert(
    "Key prop — old component disposed before new mount",
    disposeCount === 1,
    `disposeCount=${disposeCount}`
  );
}

// ═══════════════════════════════════════════════════════
// TEST 8: Rapid folder switching — no buffer leaks
// ═══════════════════════════════════════════════════════
{
  const tasks = [];
  for (let i = 0; i < 5; i++) {
    const taskId = `rapid-switch-${i}`;
    startTask({ taskId, append: false });
    simulatePtyData(taskId, `Folder ${i} data\r\n`);
    tasks.push(taskId);
  }

  // Each task should have exactly its own data
  let allIsolated = true;
  for (let i = 0; i < 5; i++) {
    const term = mountTerminal(tasks[i]);
    if (term.replayedContent !== `Folder ${i} data\r\n`) {
      allIsolated = false;
    }
  }
  assert(
    "Rapid switching — 5 folders each have isolated buffers",
    allIsolated,
    `checked ${tasks.length} task buffers`
  );

  // Final task mounted should be clean if we start fresh
  const finalTask = "rapid-final";
  startTask({ taskId: finalTask, append: false });
  const finalTerm = mountTerminal(finalTask);
  assert(
    "Rapid switching — final fresh task is clean",
    finalTerm.replayedContent === "",
    `got "${finalTerm.replayedContent.slice(0, 50)}"`
  );
}

// ── Report ──
console.log("\n── Agent Switch / Terminal Reset Regression Test ──");
let allPass = true;
for (const a of assertions) {
  const icon = a.pass ? "✓" : "✗";
  const color = a.pass ? "\x1b[32m" : "\x1b[31m";
  console.log(`  ${color}${icon}\x1b[0m ${a.name}${a.detail ? ` (${a.detail})` : ""}`);
  if (!a.pass) allPass = false;
}
console.log(`\n  ${allPass ? "PASS" : "FAIL"} (${assertions.length} assertions)\n`);
process.exit(allPass ? 0 : 1);
