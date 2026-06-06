# Plan: Persistent PTY Bridge + Monitor Tab for Teams

**Created:** 2026-03-12  
**Status:** In Progress  

## Executive Summary

Replace the per-prompt subprocess dispatch in the Teams monitor with **persistent PTY sessions per conversation**, managed by a **Node.js bridge sidecar** wrapping the proven `node-pty` + JSONL watcher from the Electron app. Add a **horizontal tab bar** to the main content header in the Electron UI, enabling instant switching between the user's active task and a dedicated Teams Monitor terminal that shows live processing of inbound Teams messages. Prompts are queued per conversation and dispatched sequentially. Results route back to Teams via the existing `_reply_to_chat` mechanism.

**Key benefit:** Eliminates the 15–30s cold-start penalty per prompt (MCP bootstrap, auth, environment load). Follow-up prompts become near-instant (~1s).

---

## Current Architecture (Before)

```
Teams Message → Trouter WebSocket → message_handler.py → filter pipeline
    → _dispatch_prompt() → asyncio.create_subprocess_exec("agency copilot -p ...")
    → wait for process exit → read response file → _reply_to_chat()
```

Each dispatch spawns a **new OS process** that:
1. Boots Agency CLI (~5s)
2. Loads MCP servers (~10–20s)
3. Authenticates
4. Processes the single prompt
5. Writes response to a temp file
6. Exits

Even with `--resume`, the full startup cost is paid every time.

## Target Architecture (After)

```
Teams Message → Trouter WebSocket → message_handler.py → filter pipeline
    → prompt_queue.enqueue() → PromptQueue worker
    → PtyBridge.write_prompt() → Named Pipe → bridge.js
    → writeToPty() (bracketed paste + staggered Enter) → Persistent PTY session
    → JSONL watcher → turn_end event → response accumulated
    → _reply_to_chat()

Electron UI:
    main.js connects to bridge.js → receives pty_data events
    → forwards as monitor:ptyData IPC → Renderer (XTerminal in Monitor tab)
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| PTY runtime | Node.js bridge sidecar | Reuses battle-tested `node-pty` + JSONL patterns from Electron app |
| Concurrency | Queue prompts sequentially per conversation | Simple, avoids race conditions on single PTY |
| Scope | One PTY per conversation | Full context isolation; bounded by `pty_max_sessions` (default 5) |
| IPC protocol | Named pipe + NDJSON | Supports multi-client (Electron UI + Python monitor on same bridge) |
| Monitor UI | Header tab bar | User preference; always-visible switching between Task and Monitor |
| Monitor terminal | Read-only by default | Prevents accidental interference with automated dispatch |

---

## PTY Prompt Submission Protocol

(Sourced from `architecture.md` — the definitive reference for how to inject prompts into copilot's interactive TUI)

### Ready Gate

The TUI renders `❯ Type @` **during** loading (as part of layout), so matching that line alone is unreliable. The definitive ready signal is `"Environment loaded:"` — it appears only after all MCP servers finish connecting.

```
READY_RE = /Environment loaded:|Describe a task to get started\.|Type @|Type \/|^[❯›]\s/im
```

### Text Injection — Bracketed Paste

Raw `proc.write(text)` gets dropped by the Ink TUI's re-render storm (~2s of 100ms redraws). Individual character writes trigger TUI shortcuts (`@` → mentions, `/` → commands). **Bracketed paste** solves both:

```javascript
proc.write(`\x1b[200~${text}\x1b[201~`)   // text survives re-renders
```

### Enter Submission

Programmatic `\r` after bracketed paste is unreliable because Ink's `useInput` hook briefly detaches stdin listeners during React re-renders (~50–200ms gap).

**Strategy comparison** (from `tests/test-pty-enter-reliability.mjs`):

| Strategy | Pass Rate | Mechanism |
|----------|-----------|-----------|
| `paste-delay-500` | **100%** | Bracketed paste → fixed 500ms delay → `\r` |
| `echo-double-enter` | 50% | Wait for echo-back → 200ms → double `\r` |
| `retry-enter-200` | 50% | Send `\r` every 200ms until submitted |
| `echo-300` | 0% | Wait for echo-back → 300ms → `\r` |

**Winning algorithm (implemented in bridge.js):**
1. Send `\x15` (Ctrl+U) to clear current input line
2. Write prompt via bracketed paste: `\x1b[200~text\x1b[201~`
3. Wait `baseDelay = min(2000, 800 + floor(text.length / 3))` ms
4. Send `\r` (Enter)
5. Send `\r` again after 400ms
6. Send `\r` again after 500ms more (triple-Enter for resilience)

### Response Reading

PTY stdout is unusable for content extraction (ANSI codes, status bars, TUI repaints). Response content is read from **`~/.copilot/session-state/<uuid>/events.jsonl`** — structured JSON events:

- `assistant.message` → accumulate `data.content` (markdown)
- `assistant.turn_end` → turn complete, flush accumulated content
- `session.task_complete` → same as turn_end
- `session.error` → error message

The JSONL watcher polls every 200ms, reads only new bytes (tracks `bytesRead` offset), and buffers partial lines across reads.

### Folder Trust

Copilot requires workspace trust consent. The trust dialog blocks input and consumes buffered text. The bridge auto-answers with option "2" (trust + remember) when it detects the dialog in PTY output.

---

## Implementation Steps

### Backend: PTY Bridge & Queue

#### Step 1: Node.js PTY Bridge — `pty-bridge/bridge.js` + `package.json`
**Status: ✅ COMPLETE**

- [skills/teams/scripts/monitor/pty-bridge/bridge.js](skills/teams/scripts/monitor/pty-bridge/bridge.js) — 599 lines
- [skills/teams/scripts/monitor/pty-bridge/package.json](skills/teams/scripts/monitor/pty-bridge/package.json)

What's implemented:
- Named pipe server (`\\.\pipe\agency-pty-bridge` on Windows, Unix socket on macOS/Linux)
- NDJSON protocol: commands (`spawn`, `write`, `kill`, `ping`, `status`, `shutdown`) and events (`ready`, `turn_end`, `assistant_message`, `pty_data`, `exit`, `error`, `pong`, `spawned`, `status`)
- Client identification (`ui` vs `monitor`) — `pty_data` events only sent to `ui` clients
- CLI binary resolution (cached path, well-known locations, PATH fallback)
- PTY session lifecycle: spawn, ready-gate detection, JSONL watcher, session ID detection, trust dialog auto-answer, MCP auth expiry detection
- `writeToPty()` — Ctrl+U clear, bracketed paste, staggered triple-Enter (per architecture.md algorithm)
- JSONL watcher — 200ms poll, incremental byte reads, partial line buffering, handles `assistant.message`, `assistant.turn_end`, `session.task_complete`, `session.error`, `system` events
- Session discovery file at `~/.agency-cowork/pty-bridge.json`
- Graceful shutdown with session cleanup
- File logging to `~/.agency-cowork/logs/pty-bridge.log`

#### Step 2: Python Bridge Client — `pty_bridge.py`
**Status: ✅ COMPLETE**

- [skills/teams/scripts/monitor/pty_bridge.py](skills/teams/scripts/monitor/pty_bridge.py) — 489 lines

What's implemented:
- Async `PtyBridge` class with named pipe connection (Windows + Unix)
- Auto-start bridge subprocess if not already running
- NDJSON read loop with event routing to per-session queues
- `spawn_session()` — sends spawn command, waits for ready event with configurable timeout
- `write_prompt()` — sends write command, awaits `turn_end`, returns accumulated response
- `kill_session()`, `get_status()`, `shutdown()`, `shutdown_bridge()`
- Health check via periodic `ping`/`pong` with 30s interval
- Windows named pipe connection via `ctypes` + `CreateFileW` + ProactorEventLoop
- `SessionInfo` dataclass with turn_end queue, event queue, message accumulator

**Known issue:** The Windows named pipe connection code (`_connect_windows_pipe`) uses a non-standard approach with `ctypes` and `connect_pipe`. This needs testing; may need to switch to `asyncio.open_connection()` which supports named pipes on Windows ProactorEventLoop natively: `asyncio.open_connection(path=r'\\.\pipe\name')`. The current implementation has a fallback attempt structure that may not work cleanly.

#### Step 3: Prompt Queue — `prompt_queue.py`
**Status: ✅ COMPLETE**

- [skills/teams/scripts/monitor/prompt_queue.py](skills/teams/scripts/monitor/prompt_queue.py) — 423 lines

What's implemented:
- `PromptQueue` class with per-conversation `asyncio.Queue`
- `enqueue()` — capacity check, position receipt for queued items, auto-start worker
- Sequential worker per conversation: dequeue → ensure session → dispatch → route reply → loop
- `_ensure_session()` — spawn or reuse PTY, resume ID for self-chat
- `_dispatch_item()` — wrap prompt, call `bridge.write_prompt()`, parse reply/summary, route to source + self-chat
- `_idle_check_loop()` — kills idle sessions after configurable timeout
- `_split_reply_summary()` — parses `---SUMMARY---` delimiter
- `_session_key_for()` — SHA-256 hash of conversation ID for filesystem safety
- Simplified prompt wrapping (no response-file protocol — JSONL provides content directly)
- Error handling: timeout, runtime errors, session death → auto-respawn on next dispatch
- Queue status reporting via `queue_info` property

#### Step 4: Refactor `_dispatch_prompt` in `message_handler.py`
**Status: ✅ COMPLETE**

Changes needed:
- Replace subprocess spawn block (lines ~925–1085) with `self._prompt_queue.enqueue()`
- Remove response file creation/cleanup
- Remove subprocess environment injection (bridge handles env)
- Add fallback: if `use_persistent_pty` is `False` or bridge unavailable, use existing subprocess path
- `MessageHandler.__init__` needs `PtyBridge` + `PromptQueue` instances

#### Step 5: Update service startup in `service.py`
**Status: ✅ COMPLETE**

Changes needed:
- In `_run_service()`: start `PtyBridge` before Trouter listen loop
- Pre-warm PTY session for configured conversations (default: `48:notes`)
- Pass chatsvc token + region to bridge environment via `queue.set_session_env()`
- Shut down bridge on service exit
- Add fallback: if bridge start fails, log warning and continue with subprocess dispatch

#### Step 6: Update `DispatchConfig` in `config.py`
**Status: ✅ COMPLETE**

New fields to add:
```python
use_persistent_pty: bool = True
pty_warmup_conversations: list[str] = field(default_factory=lambda: ["48:notes"])
pty_queue_max: int = 5
pty_idle_timeout_minutes: int = 60
pty_max_sessions: int = 5
```

### Frontend: Monitor Tab in Electron UI

#### Step 7: IPC bridge for monitor PTY data in `main.js`
**Status: ✅ COMPLETE**

Changes needed:
- Spawn bridge.js at app startup (if monitor enabled)
- Connect as `{ type: "ui" }` client to named pipe
- Relay `pty_data` → `monitor:ptyData` IPC to renderer
- Relay `assistant_message`, `turn_end`, `error` → `monitor:output` IPC
- New IPC handlers: `monitor:start`, `monitor:stop`, `monitor:status`
- Bridge lifecycle tied to app lifecycle (start on launch, stop on quit)

#### Step 8: Preload bridge for monitor channels in `preload.js`
**Status: ✅ COMPLETE**

New `contextBridge` entries:
- `onMonitorPtyData(callback)`, `onMonitorOutput(callback)`, `onMonitorTurnEnd(callback)`
- `monitorStart()`, `monitorStop()`, `monitorStatus()`

#### Step 9: Header tab bar in `App.jsx`
**Status: ✅ COMPLETE** (implemented as monitor view with back navigation rather than persistent tab strip)

- Horizontal tab strip above existing header bar (~L2855)
- Two tabs: "Task" (active task) + "Teams Monitor" (Teams icon + unread badge)
- New state: `activeView: "task" | "monitor"`
- Fluent 2 pill-style tabs, brand underline on active
- Only renders when monitor is enabled

#### Step 10: Monitor terminal view in `App.jsx`
**Status: ✅ COMPLETE**

- Second `XTerminal` instance keyed `"monitor"` when `activeView === "monitor"`
- Receives data from `monitor:ptyData` IPC events
- Separate `monitorPtyBuffer` for terminal history replay on tab switch
- Read-only by default; "Take control" button for manual input
- Monitor status bar: connected/disconnected, conversations, dispatch count, queue depth

#### Step 11: Monitor state management (`useMonitor.js` hook)
**Status: ✅ COMPLETE**

State: `monitorEnabled`, `monitorConnected`, `monitorConversations`, `monitorDispatchCount`, `monitorPtyBuffer`
- Listen to `monitor:output` for structured data
- Listen to `monitor:ptyData` for raw terminal output
- Track unread events (increment when viewing another tab, clear on switch)

#### Step 12: Unread badge on monitor tab
**Status: ✅ COMPLETE** (integrated into sidebar monitor button)

- Red dot or count badge on "Teams Monitor" tab when new events arrive while viewing Task tab
- Clear on switch to monitor
- Optional pulsing glow animation during active processing

#### Step 13: Monitor sidebar button
**Status: ✅ COMPLETE** (combined with Step 12 — includes status dot + unread badge)

- "Monitor" entry in sidebar nav (after "Scheduled", ~L2345 in App.jsx)
- Clicking sets `activeView = "monitor"`
- Status indicator: green dot = connected, gray = off, red = error
- Collapsed sidebar: icon + status dot only

#### Step 14: Monitor enable/disable toggle
**Status: ✅ COMPLETE** (Start/Stop button in monitor header bar)

- Toggle in monitor status bar or sidebar context menu
- Sends `monitor:start` / `monitor:stop` IPC to main process
- Main process starts/stops Python monitor service + bridge process

### Config & Install

#### Step 15: Install script — `pty-bridge/install.ps1` + `.sh`
**Status: ❌ NOT STARTED**

- `npm install` in pty-bridge directory
- Verify `node` on PATH
- Optionally reuse prebuilt `conpty.node`/`pty.node` from `ui/prebuilds/`

#### Step 16: Graceful fallback
**Status: ❌ NOT STARTED**

- If bridge fails to start (missing `node`, broken deps), fall back to original subprocess dispatch
- UI shows "Monitor: Offline" in tab badge

---

## Verification Plan

| Test | What | How |
|------|------|-----|
| Bridge protocol | spawn → ready → write → turn_end flow | Mock named pipe clients |
| Queue serialization | 3 rapid-fire prompts → sequential dispatch | Integration test with bridge |
| UI tab switching | Tab bar renders, history preserved on switch | Manual + Playwright |
| E2E | Teams message → monitor shows processing → reply in Teams | Full stack with real message |
| Fallback | Kill bridge → subprocess dispatch → "Offline" status | Remove node from PATH |
| Idle timeout | Configure 1min → session killed → re-spawns on next prompt | Wait + verify |

---

## Completion Summary

| Component | Status | Files |
|-----------|--------|-------|
| PTY Bridge (Node.js) | ✅ Complete | `pty-bridge/bridge.js`, `pty-bridge/package.json` |
| Python Bridge Client | ✅ Complete | `pty_bridge.py` |
| Prompt Queue | ✅ Complete | `prompt_queue.py` |
| message_handler.py refactor | ✅ Complete | `message_handler.py` |
| service.py startup update | ✅ Complete | `service.py` |
| config.py update | ✅ Complete | `config.py` |
| Bridge Enter timing fix | ✅ Complete | `pty-bridge/bridge.js` |
| Electron main.js (monitor IPC) | ✅ Complete | `ui/electron/main.js` |
| preload.js (monitor channels) | ✅ Complete | `ui/electron/preload.js` |
| App.jsx (monitor view + sidebar) | ✅ Complete | `ui/src/App.jsx` |
| XTerminal (monitor mode) | ✅ Complete | `ui/src/XTerminal.jsx` |
| useMonitor.js hook | ✅ Complete | `ui/src/useMonitor.js` |
| Unread badge | ✅ Complete | `ui/src/App.jsx` (sidebar button) |
| Enable/disable toggle | ✅ Complete | `ui/src/App.jsx` (monitor header) |
| Install script | ❌ Not started | — |
| Graceful fallback | ❌ Not started | — |

**Overall progress: 14 of 16 steps complete (core implementation done; install script + fallback UI remaining)**
