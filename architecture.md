# Architecture & Development Guide

> **Version 0.9.9** — See `README.md` for changelog.

## Lessons Learned

### Prompt Queue Must Drop Stale Bridge Sessions After Reconnect (2026-04-03)

**Root cause:** The monitor bridge reconnect path clears and recreates `SessionInfo`
objects, but `PromptQueue` can still hold a reference to the old object in
`cq.session_info`. If `_ensure_session()` only checks whether `cq.session_info is None`,
it can wait on the stale object's `event_queue` for up to 120 seconds even though the
bridge already has a fresh replacement session.

**What made it hard to find:** The queue looked healthy at a glance because the stale
object still had the right `session_key`, so logs and debugger state pointed at the
expected conversation. The break only appeared after a bridge reconnect, where the new
session warmed correctly but the queue silently kept listening to the abandoned object.

**Fix pattern:** Any queue or cache that stores bridge/session objects must re-check
object identity after reconnects. If the bridge's current session object for a key is
not the same instance, drop the stale reference immediately and adopt the replacement
or respawn without waiting on dead event queues.

### 1. Global Monitor Config Is Source of Truth (2026-03-15)

- The global config at `~/.agency-cowork/monitor-config.json` must remain the source of truth once a workspace entry exists. Letting legacy `agentconfig.json` override `monitor.enabled` can make Electron think the workspace is enabled while the Python service silently disables itself, surfacing as monitor start hanging on "Starting...". Fix: use `agentconfig.json` only to backfill a missing global workspace entry during migration, never to overwrite an existing one.
- Monitor autostart must emit the same full status payload as manual start. If `monitor:status` omits `running` or `bridgeConnected`, the renderer gets stuck in a yellow in-between state. Fix: every autostart/bridge-exit status update should send `connected`, `bridgeConnected`, and `running` together.
- Teams Monitor restart handling should include a short UI cooldown after Stop to prevent repeated Start clicks from racing bridge/service teardown.
- For shipping macOS installers, prefer the stock electron-builder DMG flow without a custom DMG background. Keep the manual DMG scripts as an emergency fallback only.

### 2. Packaged Monitor Must Validate Bridge Ownership (2026-03-15)

**Root cause:** The monitor bridge socket path is global (`/tmp/agency-pty-bridge.sock`). On packaged macOS, the bridge runs in-process inside `Agency Cowork.app`, so a stale latent app instance can still own that socket even after a new DMG-installed app launches.

**What made it hard to find:** The new app could start successfully and still connect to the old bridge, making the runtime look half-correct. Logs showed a healthy bridge connection, but the UI and monitor state could belong to the wrong process tree.

**Fix pattern:** Always validate the bridge discovery file PID before attaching the UI or Python monitor. If discovery points to a dead process, clean up the socket and discovery file. If it points to an older `Agency Cowork` or `bridge.js` owner, kill or reject that stale owner before connecting.

### 3. Monitor Restart Logic Must Use the Real Python PID File (2026-03-15)

**Root cause:** The Electron monitor restart path checked `skills/teams/scripts/monitor/monitor.pid`, but the Python service writes to `skills/teams/monitor/monitor.pid`.

**Fix pattern:** Treat `skills/teams/monitor/monitor.pid` as the canonical monitor PID file, with the old scripts path only as a compatibility fallback.

### 4. macOS DMG Release Helper Must Recover From `dmgbuild` Detach Failures (2026-03-16)

**Root cause:** On macOS 15.3, the stock Electron Builder DMG step can fail after successful app signing and app notarization with `Unable to detach device cleanly: hdiutil couldn't unmount diskX - Resource busy`.

**What made it hard to find:** The important work had already succeeded. The `.app` bundles were signed and notarized, but the final DMG step failed late, left temporary images or mounted volumes behind, and looked like a total release failure unless the build log was read carefully.

**Fix pattern:** Keep the stock `electron-builder --mac dmg --<arch>` path as the first attempt, but automatically fall back to `ui/scripts/create-dmg-manual.sh` when the failure signature is the known detach bug. Reuse the already signed `.app`, keep the standard drag-to-Applications Finder layout, then sign and notarize the DMG container separately with `ui/scripts/notarize-dmg.sh`. Also keep x64 paths aligned with Electron Builder's real output layout: app in `release/mac`, DMG at `release/Agency Cowork-<version>.dmg`.

### 5. Electron Debug and Process Helpers Must Avoid Shell Interpolation (2026-03-17)

**Root cause:** Several Electron helpers were building shell commands with string interpolation (`taskkill /pid ${pid}`, `"${azCmd}" ...`, `${pythonCmd} -m ...`). Even when current callers pass expected values, this pattern leaves future call sites vulnerable and makes review harder. The dev PTY debug server also exposed write endpoints on localhost with no session token.

**What made it hard to find:** Most paths were "developer-only" or "local-only," so they looked harmless in isolation. But they still crossed trust boundaries: localhost is shared with every local process, and interpolated shells turn innocent plumbing code into policy exceptions.

**Fix pattern:** Use `execFileSync`/argument arrays for every user-influenced or variable executable invocation, validate PIDs before taskkill, and scope file reads to the configured workspace only. For local debug HTTP endpoints, require a per-process token even in dev mode so write access is explicit.

### 6. Terminal Focus State Controls Ink Input Acceptance (2026-03-13)

**Root cause:** Ink's `TextInput` silently ignores all input (including `\r`) when the
terminal reports focus-out (`ESC[O`). xterm.js sends `ESC[O` whenever the user clicks
outside the terminal component (e.g., on the send textbox).

**What made it hard to find:** The same `meta.proc.write("\r")` call, on the same
object, with the same byte (0x0D), produced different results depending on whether
a focus-out event had been sent. No errors, no warnings — input was silently dropped.
Debug logging showed writes succeeding at the PTY level, but the CLI never processed them.

**Fix pattern:** Always send `ESC[I` (focus-in) before injecting text or Enter into a
Copilot CLI PTY session. For follow-up prompts in Electron, use the IPC roundtrip
(`injectPtyInput`) to ensure writes go through the same handler context as keyboard input.

**Applies to:** Any PTY integration with Ink-based TUI apps where the hosting terminal
supports focus tracking (xterm.js, Windows Terminal, etc.).

### 7. Electron IPC Context Affects PTY Write Delivery (2026-03-13)

**Root cause:** On Windows with ConPTY, `meta.proc.write()` from `setTimeout` or HTTP
server callbacks in the Electron main process does not reliably deliver input to the
child process. Only writes from Electron IPC handler context (triggered by renderer
via `ipcMain.handle`) work consistently.

**Fix pattern:** Route delayed writes through the renderer via IPC roundtrip:
`main → pty:injectInput → renderer → task:ptyWrite IPC → main → meta.proc.write()`.

### 8. Initial Prompt Needs Hybrid Write Strategy (2026-03-13)

**Root cause:** On a fresh PTY spawn, the XTerminal React component may not be mounted
yet when `writePromptOnce` fires. The IPC roundtrip (`pty:injectInput`) has no listener
in the renderer — the text is lost.

**Fix pattern:** Use direct `meta.proc.write()` for the initial text (synchronous, before
xterm.js mounts and before any focus-out events). Use IPC roundtrip only for the delayed
Enter (by the time the 500ms delay fires, XTerminal is mounted and may have sent focus-out).

### 9. Chatsvc Wrong-Region 200 Silently Drops Messages (2026-03-15)

**Root cause:** The Teams chatsvc API returns HTTP **200** (not 404) when a message is
POSTed to the wrong region. The 200 body contains a `"messages"` array (conversation
echo) instead of a delivery confirmation. The correct region returns **201** with
`{"OriginalArrivalTime": ...}`. The code treated all 200/201/202 as success.

**What made it hard to find:** Logs showed "Reply sent" with HTTP 200 — every indicator
said success. Only comparing 200 vs 201 response bodies revealed the difference. The
existing region auto-discovery only triggered on 404, never on 200.

**Fix pattern:** Only treat HTTP 201/202 as confirmed delivery. On 200, parse the
response body: if it contains a `"messages"` array, it's a wrong-region echo — extract
the correct region from `conversationLink` in the body, auto-correct via
`set_chatsvc_region()`, persist to config, and retry the POST.

**Applies to:** Any chatsvc API integration. Region slug is tenant-specific (e.g.,
`amer`, `noam-pilot2`, `emea`) and NOT inferable from user location alone.

### 10. Reply Prefix Must Be Explicitly Propagated (2026-03-15)

**Root cause:** `set_reply_prefix()` was imported in `service.py` but never called. The
module-level `_reply_prefix` defaulted to `"Agency Cowork: "` and was never updated with
the per-workspace config value. The config value was only used for self-loop detection.

**Fix pattern:** When module-level state is set via setter functions (not constructor
args), always verify the setter is actually called during initialization. A comment
saying "Apply X" is not the same as actually calling the function.

### 11. Electron PATH Isolation Breaks Fresh Installs (2026-03-15)

**Root cause:** Electron inherits `PATH` from its launch-time environment. Tools
installed during setup (Azure CLI, Agency CLI) update the Windows registry PATH but
not the running Electron process. Subsequent `execSync("az.cmd ...")` calls fail with
"not recognized".

**Fix pattern:** Before calling any CLI tool from Electron that may have been
freshly installed, refresh `process.env.PATH` from the Windows registry
(`HKLM\...\Environment` + `HKCU\Environment`). Also check well-known install paths
as fallback (e.g., `Program Files\Microsoft SDKs\Azure\CLI2\wbin\`).

### 12. AzureAuth Incomplete Extraction Causes MCP Failures (2026-03-15)

**Root cause:** AzureAuth 0.9.5 zip extraction was incomplete — `MSALWrapper.dll`
missing from the version directory. This caused a .NET CLR exception (`0xe0434352`)
whenever `agency mcp calendar|mail|teams` spawned azureauth, silently breaking all
local STDIO MCP servers.

**Fix pattern:** After any tool installation that involves zip extraction, verify
critical files exist (not just the main executable). Run a smoke test
(`azureauth --version`) to catch load-time failures. Auto-repair by re-extracting
from the retained source zip if available.

### 13. PTY Enter/Text Lost — Missing Focus-In Before Text Paste (2026-03-15)

**Root cause:** `writePromptOnce()` (initial prompt path) did not send `ESC[I`
(focus-in) before injecting text — only before the delayed Enter. By the time
`writePromptOnce` fires (2s after ready-detect), XTerminal has mounted and
xterm.js has sent `ESC[O` (focus-out) because the user's cursor is in the chat
textbox. Ink's `TextInput` ignores ALL input (paste + Enter) when unfocused,
so both the text and Enter are silently dropped.

**What made it hard to find:** The textbox send path (`writeToPty`) works reliably
because it sends `ESC[I` **before the text paste** (line 1: focus-in → Ctrl+U →
paste → delay → focus-in → Enter). The initial prompt path was missing step 1.
The assumption "no focus-out has occurred yet" was correct at PTY spawn time but
wrong by the time `writePromptOnce` fires 7–9s later.

**Fix pattern:** Always send `ESC[I` before text, not just before Enter. Both
`writePromptOnce` and `writeToPty` now follow the same pattern:
`ESC[I → Ctrl+U → bracketed paste → delay → ESC[I → Enter`.

**Applies to:** Any PTY integration with Ink-based TUI apps. Focus-in must
precede EVERY write sequence, not just Enter — Ink drops all input when unfocused.

### 14. PTY Slash Commands Must Use Bracketed Paste + Delayed Enter (2026-03-15)

**Root cause:** The PTY bridge sent `/yolo` as a single write (`"/yolo\r"` — text
and Enter concatenated). Ink's TUI needs time to process the paste before Enter
arrives. When text+Enter are in one write, the `\r` fires before the text is
committed to the input buffer, resulting in either an empty Enter or the `/yolo`
text appearing but never submitting.

**What made it hard to find:** Regular prompts (from `writeToPty` and the bridge's
`writePrompt`) used the correct `ESC[I → Ctrl+U → bracketed paste → delay →
ESC[I → Enter` pattern. Only the `/yolo` command sends (initial and retroactive)
used the shortcut single-write pattern.

**Fix pattern:** ALL text-then-Enter writes to a Copilot CLI PTY must follow the
full injection pattern — no exceptions for short commands like `/yolo`. Even a
5-character command needs bracketed paste + 500ms delay before Enter.

**Applies to:** Any PTY command injection. Never combine text and `\r` in one
`proc.write()` call — always separate with a delay.

### 15. Auto-Accept "Enable Autopilot Mode" Permissions Dialog (2026-03-15)

**Root cause:** When `/yolo` or a mode switch activates autopilot, Copilot CLI
shows an "Enable autopilot mode" dialog with three options (Enable all permissions,
Continue with limited, Cancel). Option 1 is pre-selected with `›`. The PTY bridge
already handled this dialog, but the Electron main process did not — so when
`/yolo` was sent from the UI (not the monitor), the dialog appeared and blocked
execution until the user manually pressed Enter.

**Fix pattern:** Detect `Enable autopilot mode` or `enable.*all permissions` in
PTY output and auto-send `ESC[I` + `\r` after 300ms. The short delay lets the
TUI render the dialog fully. Guard with a `sent` flag to avoid duplicate sends.

**Applies to:** Any interactive CLI dialog that appears in the PTY stream with a
pre-selected default option. Add a regex + auto-answer pattern for each known
dialog type.

### 16. `--exclude-standard` Hides Gitignored Runtime State From Backup (2026-03-15)

**Root cause:** `update.ps1` Step 3.7 used `git ls-files --others --directory
--exclude-standard` to find untracked runtime directories for backup. The
`--exclude-standard` flag respects `.gitignore`, which explicitly excludes
`skills/qmd-memory/cache/` (embedding cache), `skills/task-scheduler/logs/`,
and `skills/teams/logs/`. These are the exact directories the backup should
protect — but the flag made them invisible to the scan.

**What made it hard to find:** The command output looked correct (it listed *some*
untracked dirs). The missing dirs only appeared when running without the flag.
Bisecting the `.gitignore` patterns confirmed `cache/` was excluded at line 33.

**Fix pattern:** Remove `--exclude-standard` from runtime backup scans. Instead,
filter out known non-essential patterns (e.g., `__pycache__`, `node_modules`)
in application code. Runtime state backup must see ALL untracked content, not
just non-gitignored content.

**Applies to:** Any git-based backup or migration tool. If the goal is to find
runtime state, `--exclude-standard` is the wrong flag — it's designed for
*tracking* decisions, not *backup* decisions.

### 17. `--allow-all-tools` Only Works With `-p` (Non-Interactive) Mode (2026-03-15)

**Root cause:** The Copilot CLI `--allow-all-tools` flag is silently ignored in
interactive PTY mode. It only takes effect when combined with `-p` (piped/prompt
mode). In PTY mode, switching to autopilot ALWAYS shows the "Enable autopilot mode"
permissions dialog regardless of CLI flags.

**What made it hard to find:** The bridge spawned sessions with `--allow-all-tools`
and assumed the permissions dialog would be suppressed. Logs showed the flag was
passed. The dialog appeared anyway, and the proactive Enter handler was gated on
`!yoloMode` (assuming `--allow-all` prevented the dialog when yolo was off).

**Fix pattern:** In PTY interactive mode, NEVER rely on `--allow-all-tools` to
suppress the permissions dialog. Always handle it via PTY input injection:
option 1 (Enter) for full permissions, or option 2 (Down+Enter) for limited.
Gate the handler on `autoApprovePermissions` setting, not on CLI flags.

**Applies to:** Any PTY automation of Copilot CLI. CLI flags for tool permissions
only work in non-interactive (`-p`) mode.

### 18. Bridge Settings Race — Env Vars vs Pipe Commands (2026-03-15)

**Root cause:** The PTY bridge initialized autonomy flags (autopilot, auto-approve,
yolo) to `false` at startup, then waited for pipe commands from Electron to set
the correct values. But the Python service could spawn a session before those pipe
commands arrived, using the stale default `false` values.

**What made it hard to find:** In normal startup, the pipe commands arrive within
~100ms. But under load or during config save/restart cycles, the race window widens.
The flags appeared correct in bridge debug output because the query happened after
the pipe commands arrived — but the session had already been created with stale values.

**Fix pattern:** Pass critical startup configuration as environment variables
(`BRIDGE_YOLO`, `BRIDGE_AUTOPILOT`, `BRIDGE_AUTO_APPROVE`) at spawn time, not as
post-spawn pipe commands. The bridge reads `process.env` during initialization,
before any sessions can be created. Pipe commands remain for runtime changes.

**Applies to:** Any parent-child process pattern where the child needs config before
handling requests. Env vars are atomic at spawn; IPC commands have a race window.

### 19. Windows Orphan Process Cleanup — WINDOWTITLE vs Command-Line Match (2026-03-15)

**Root cause:** `killOrphanedMonitorProcesses()` on Windows used
`taskkill /FI "WINDOWTITLE eq monitor*"` to find stale Python monitor processes.
Headless Python processes spawned by Electron have no window title — the filter
never matched, leaving old processes alive across app restarts.

**What made it hard to find:** The orphan killed no processes, but raised no errors
either (`taskkill` exits cleanly when no matches found). The duplicate bot replies
(one from old process, one from new) were the only symptom, and could be mistaken
for a message handler bug.

**Fix pattern:** On Windows, use PowerShell `Get-CimInstance` with command-line filtering:
`Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*scripts.monitor.service*' }`.
Avoid `wmic.exe` which is deprecated and removed from Windows 11 22H2+ by default.
The macOS/Linux path already used `pgrep -af` (command-line match) correctly.

**Applies to:** Any Windows process cleanup. Never use `WINDOWTITLE` for headless
or child processes. Prefer `Get-CimInstance` over deprecated `wmic.exe`.

### 20. Packaged Teams Monitor PTY — Use Electron Main Runtime, Not Electron-as-Node Child (2026-03-15)

**Root cause:** The regular chat PTY worked because it ran inside Electron main,
but the Teams monitor PTY bridge ran as a separate child process using Electron in
`ELECTRON_RUN_AS_NODE=1` mode. In the packaged macOS app, `node-pty` could load but
could not reliably spawn children there, producing `posix_spawnp failed` only for
the monitor path.

**What made it hard to find:** Dev mode and the normal "new task" PTY both worked,
so the bug looked like a Teams-only or path-resolution issue. The packaged bridge
also appeared partially healthy: the pipe server started, clients connected, and the
failure only appeared when the first PTY session spawn happened.

**Fix pattern:** In packaged macOS builds, run the monitor bridge in-process inside
Electron main and share the already-working `node-pty` instance with the bridge.
Then teach the prompt queue to adopt pre-warmed ready sessions so the first real
Teams message is not delayed behind startup automation.

**Applies to:** Any packaged Electron feature using `node-pty`. If PTY works in main
process but fails in a helper child, prefer reusing the main-process runtime instead
of spawning Electron in hidden Node mode.

### 21. Manual DMG Release Path — Notarize the App and the DMG Separately (2026-03-15)

**Root cause:** `electron-builder` successfully signed and notarized the `.app`, but
its DMG builder failed at detach time with `hdiutil: couldn't unmount ... Resource busy`.
The manual DMG fallback created a valid container, but that DMG itself was not notarized,
so `stapler` on the DMG failed with `Insufficient Context` even though the app inside was
already notarized.

**What made it hard to find:** The notarization log said success, which was true for the
app bundle, but the final customer-facing artifact was the DMG. That made it easy to think
the remaining problem was signing, when it was actually a container-notarization step plus
an unreliable DMG builder.

**Fix pattern:** Treat the app and DMG as separate notarization targets. If `electron-builder`
DMG creation flakes, staple the notarized app, create the DMG manually, then submit the DMG
to `notarytool`, staple it, and assess it separately. Keep the manual DMG window styling plain
so Finder falls back to the system appearance.

**Applies to:** Any macOS release flow that uses a manual DMG fallback. Notarizing the app
bundle is not sufficient when customers download a DMG container.

### 22. macOS Close Behavior — Quit by Default, Stay Alive Only for Real Background Work (2026-03-15)

**Root cause:** The app previously hid to the tray or menu bar on every window close.
That matched a power-user background-service model, but it was hostile to the normal macOS
install and upgrade flow because users thought the app was closed while the process was still
running, which then blocked drag-replace updates in `/Applications`.

**What made it hard to find:** The behavior was internally consistent and the tray menu already
exposed `Quit`, so it did not look broken during development. The problem only becomes obvious
on the customer path: install from DMG, close the app, then try to replace it with a newer build.

**Fix pattern:** On macOS, close the app completely by default. Only keep it alive in the menu bar
when there is a live user-visible background service, currently the Teams monitor bridge. Passive cron
schedules should not keep the app resident by themselves because that makes install and upgrade behavior
surprising. If the monitor keeps the process alive, show a one-time explanation so the user knows the
app is still running and must be fully quit before reinstalling.

**Applies to:** Any future macOS background feature. Do not hide-on-close by default just because a
tray icon exists or a schedule is configured. Gate background persistence on explicit live work and
explain the behavior once.

### 23. PTY Ready Detection — Resumed Sessions May Skip `Environment loaded:` (2026-03-15)

**Root cause:** The monitor PTY bridge initially treated `Environment loaded:` as the primary ready signal.
That works for full cold starts, but resumed Copilot sessions can land directly on the interactive prompt and
footer without replaying the bootstrap banner. In that case the session is usable, but the bridge never flips
it to `ready`, so the first queued Teams prompt waits 120 seconds and everything behind it only gets queue receipts.

**What made it hard to find:** The installed app still streamed live PTY output, which made it look like the
pipeline was working. The actual failure was narrower: prompt queue startup waited on a bridge `ready` event that
never fired even though the terminal had already reached the interactive footer.

**Fix pattern:** Accept both bootstrap and prompt/footer readiness. Keep `Environment loaded:` as the strong signal,
but after a short grace period also treat the real CLI prompt and footer text, such as `Type @`, the prompt glyph,
or `shift+tab switch mode`, as proof that a resumed session is ready for input.

**Applies to:** Any persistent PTY or TUI automation that resumes existing sessions. Do not assume the same startup
banner appears on every launch path.

### 24. Monitor IPC Must Never Send Directly To A Possibly-Destroyed Renderer (2026-03-15)

**Root cause:** The Teams monitor bridge event path still used direct `mainWindow?.webContents.send(...)` calls for
`monitor:ptyData`, `monitor:output`, and `monitor:turnEnd`. Optional chaining only protects `mainWindow`; it does not
prevent `webContents.send()` from throwing once the window or its webContents has already been destroyed.

**What made it hard to find:** The bridge can connect and start streaming during app startup or shutdown races, so the
error surfaces intermittently as `TypeError: Object has been destroyed` even though monitor startup, signing, and
notarization all look healthy.

**Fix pattern:** Route all monitor renderer IPC through the shared `sendToRenderer()` guard so both `mainWindow` and
`webContents` are checked before sending. Add a regression guard that fails if raw `monitor:*` sends are reintroduced
in `ui/electron/main.js`.

**Applies to:** Any Electron async callback that can outlive the renderer, especially socket, PTY, scheduler, or child
process event handlers.

### 25. update.ps1 Must Self-Update Before Running Migrations (2026-03-17)

**Root cause:** New migration features (OneDrive migration, service stop/restart, zombie cleanup) only exist in the new `update.ps1`, but the running script is the old version. Users upgrading from 0.9.8 to 0.9.9 ran the old script, which lacked the new migration steps.

**What made it hard to find:** The upgrade appeared to complete successfully -- old script steps all passed. The missing migrations only became apparent when features relying on them (OneDrive sync, service restarts) failed silently.

**Fix pattern:** Step 0 of `update.ps1` fetches `upstream/main:scripts/update.ps1`, compares SHA256 hashes. If different, writes the new script to a temp file and re-executes via `pwsh` with the original parameters, using `AGENCY_UPDATE_SELF_UPDATED` env var as a re-entry guard to prevent infinite recursion.

### 26. NTFS Junctions Break Relative Git Submodule Pointers (2026-03-17)

**Root cause:** After creating an NTFS junction `memory/ -> OneDrive/.../memory/`, a git submodule's `.git` pointer file contains a relative path (`gitdir: ../.git/modules/memory`). The junction target resolves to the OneDrive real path, so the relative `..` lands in the wrong directory.

**What made it hard to find:** `git status` in the repo root worked fine (git resolves the junction). But operations inside `memory/` (where the junction points) failed because the `.git` file's relative path resolved against the OneDrive real path, not the repo root.

**Fix pattern:** After creating a junction/symlink for a git submodule, detect relative `gitdir:` in the `.git` pointer file, resolve it to an absolute path against the original repo location, and rewrite the file.

### 27. PowerShell Copy-Item Treats Brackets as Glob Wildcards (2026-03-17)

**Root cause:** `Copy-Item` interprets `[` and `]` in file paths as wildcard character class delimiters. Files like `[EXT---MS]-spec.md` are silently skipped because the bracket pattern matches nothing.

**Fix pattern:** Always use `-LiteralPath` instead of `-Path` for file operations on user content that may contain brackets, parentheses, or other glob metacharacters. This applies to `Copy-Item`, `Move-Item`, `Remove-Item`, `Get-Content`, and `Test-Path`.

### 28. execFileSync With shell:true and Spaces in Path (2026-03-17)

**Root cause:** `execFileSync(azCmd, args, { shell: true })` where `azCmd` is an absolute path like `C:\Program Files (x86)\...\az.cmd` fails because `cmd.exe /s /c` strips the outer quotes, splitting `C:\Program` and `Files` into separate tokens.

**What made it hard to find:** The code had `shell: true` specifically to handle `.cmd` files (which need shell interpretation), and the PATH included the directory. But `azCmd` was set to the full absolute path with spaces, bypassing PATH resolution entirely.

**Fix pattern:** When using `shell: true` with `execFileSync`, never pass an absolute path containing spaces as the command. Instead, add the directory to `process.env.PATH` and use just the filename (`az.cmd`). PATH resolution handles the rest without quoting issues. This also applies to any `.cmd` or `.bat` file in `Program Files`.

### 29. Tray Quit Does Not Trigger Renderer State Save (2026-03-17)

**Root cause:** Task persistence only triggered on `isDone` (process exited). When the user quit from the system tray, `app.quit()` killed all processes without giving the renderer time to save the active conversation. The current conversation was lost from recents.

**What made it hard to find:** Normal task completion saved correctly. The bug only appeared when quitting mid-conversation from the tray -- a common user workflow but not covered by the completion-only save trigger.

**Fix pattern:** Two-pronged: (1) Save task after every turn completion (`isWaiting`), not just `isDone` -- conversations are incrementally persisted as they progress. (2) In `before-quit`, use `e.preventDefault()` to delay quit by 500ms, send `app:before-quit` signal to renderer, let it do one final save, then re-trigger `app.quit()` with a `pendingQuitSave` guard to prevent infinite recursion.

**Applies to:** Any Electron app with unsaved renderer state. Never rely on process exit to trigger saves -- save incrementally and add a before-quit grace period.

### 30. Monitor Config Migration Must Preserve User Settings (2026-03-17)

**Root cause:** `setup.ps1` migration (legacy -> global monitor config) had three bugs: (1) missing top-level `enabled` field, (2) pulling keyword from legacy config (which had stale `@maia-agent`) instead of `agentconfig.json` (which had the user's actual keyword), (3) unconditionally overwriting existing global workspace entries on re-run.

**What made it hard to find:** The migration ran once and appeared successful. The config revert only surfaced on restart, when the Python service read the global config with the wrong keyword and `enabled` state.

**Fix pattern:** Migration must: (a) always include top-level `enabled` field, (b) prefer `agentconfig.json` keyword over legacy config, (c) skip workspace migration if a global entry already exists and is enabled. Also validate `working_directory` on save -- reject or warn if the path doesn't exist on disk.

### 31. OneDrive Migration: Backup-Validate-Delete Pattern (2026-03-17)

**Root cause:** `Invoke-OneDriveMigration` in `update.ps1` deleted the local `memory/` directory with `Remove-Item -Recurse -Force` before verifying the NTFS junction worked. When junction creation failed (OneDrive target was empty because the copy tool had silently failed), 658 files were lost. The script also used `$LASTEXITCODE` from a stale prior command to check success of `robocopy`, which was not on PATH in the bundled environment.

**What made it hard to find:** The copy appeared to succeed because the error was caught silently and `$LASTEXITCODE` was 0 from a prior command, not from `robocopy`. The `Remove-Item` on the next line was unconditional -- no validation that the destination actually contained the files.

**Fix pattern:** All directory migrations that involve delete-and-replace-with-junction MUST follow this sequence: (1) Pre-flight checks: verify source is non-empty, target is writable, no stale junctions exist. (2) Copy files to destination. (3) Validate file counts: `dest >= source`. Abort if mismatch. (4) Create full timestamped backup (`.onedrive-migration-backup-*`). (5) Delete source. (6) Create junction. (7) Verify junction: list files through it and check count > 0. (8) If any step 5-7 fails, restore from backup. (9) Clean up backup only after everything succeeds. For directory copy/delete/junction operations, avoid `robocopy`, `xcopy`, or `cmd /c` and use only PowerShell-native `Copy-Item`, `Move-Item`, `Remove-Item` with `-LiteralPath` (external tools have different error semantics that defeat validation logic). Other scripts may legitimately invoke `git`, `python`, `npm`, etc.

### 32. Installer Has Three Separate File Lists That Must Stay in Sync (2026-03-17)

**Root cause:** When `docs/` was added to the installer bundle, it was added to `extraResources` in `package.json` (production builds) and `optionalItems` in the `setup:extractFiles` handler (dev-mode fresh installs), but missed in `UPDATE_ITEMS` in the `setup:updateProject` handler (upgrade path). Users upgrading from a previous version never received the `docs/` directory, causing the agent to fail with "Path does not exist" when trying to read `docs/POST_SETUP_GUIDE.md`.

**What made it hard to find:** Fresh installs worked fine (the production path copies everything in `bundled-project/`). The bug only appeared on upgrades, which use an explicit allowlist (`UPDATE_ITEMS`) rather than copying everything. Testing the installer on a clean machine would not reproduce it.

**Fix pattern:** The installer has three file lists that MUST stay in sync when adding new bundled directories or files: (1) `extraResources` in `ui/package.json` -- controls what electron-builder bundles into `resources/bundled-project/`. (2) `optionalItems` in the `setup:extractFiles` IPC handler -- controls what gets copied during dev-mode fresh installs. (3) `UPDATE_ITEMS` in the `setup:updateProject` IPC handler -- controls what gets copied during upgrades. Missing any one of these causes a silent gap for that code path. Consider refactoring to a single shared constant.

### 33. "Use Existing Project" Stamps Version Without Updating Files (2026-03-18)

**Root cause:** The OOBE "Use Existing Project" flow (`handleUseExistingProject`) set `isExistingProject=true` and jumped to step 3, completely skipping the extract step. The extract step was explicitly hidden: `if (isExistingProject && s.id === "extract") return null`. Meanwhile, `setup:complete` wrote a new version number to `agencycowork.json` — so the folder was stamped as current but contained stale scripts and skills from the original install date.

**What made it hard to find:** The folder appeared up-to-date because `agencycowork.json` showed the latest version. The staleness was only visible when comparing file modification dates or running updated features that were absent. Working folders could be weeks behind while reporting the current version.

**Fix pattern:** Before allowing "Use Existing Project", always compare the app's bundled version (`package.json`) against the installed version (`agencycowork.json`). If they differ, present an explicit update dialog with backup. Reuse the existing `setup:updateProject` handler (which handles backup, user-data preservation, and file sync) rather than duplicating logic. Never stamp a version without actually delivering the files for that version.

### 34. Windows OOBE Reinstalls Optional Dependencies Despite Existing Install (2026-03-18)

**Root cause:** The macOS OOBE passed `--install-deps none` to skip Phase 7 optional dependencies, but the Windows OOBE was missing this flag. Without it, `$depsToInstall` defaulted to empty and `Read-YesNo` returned `$true` in headless mode, so Phase 7 ran unconditionally. The detection checks (`Get-Command qmd`, `pip show markitdown`) failed in Electron's spawned PowerShell because `process.env.PATH` differs from the user's interactive shell — QMD's `C:\ProgramData\global-npm` and Python's `Scripts` directory were not on the spawned process PATH.

**What made it hard to find:** The detection checks work correctly in a normal terminal. The failure only occurs inside Electron-spawned processes where the PATH is minimal. The tools were already installed and functional, but the detection said they weren't.

**Fix pattern:** (1) Pass `-InstallDeps none` on Windows to match macOS (Phase 7 deps are not needed during OOBE). (2) Harden detection with multi-strategy fallbacks: PATH check → npm global prefix + filesystem locations → `pip show 2>&1 | Out-String` → `python -c "import ..."`. Never rely solely on PATH-based detection in Electron-spawned contexts.

### 36. xterm.js Scroll Wheel & Scrollbar — Full Requirements Checklist (2026-04-06, updated 2026-04-07)

This lesson consolidates all known requirements for mouse wheel scrolling and the overlay scrollbar
to work correctly in the xterm.js v6 terminal. Multiple bugs have been filed against these
requirements across PRs #204, #228, #232.

#### Requirement 1 — Never use `display: none` on xterm internal elements; use `opacity: 1 !important`

**Root cause (original):** `display: none` on `.xterm .xterm-scrollable-element > .scrollbar` removes
the element from the browser's layout AND pointer-event dispatch tree. xterm.js v6 routes ALL mouse
input (wheel, selection drag, click-to-scroll) through this overlay layer. With it hidden via
`display: none`, wheel events fired over the terminal are silently discarded before reaching
xterm's `MouseService` — keyboard input still works, making the bug invisible without a debug wheel listener.

**Root cause (regression, 2026-04-07):** Replacing `display: none` with `opacity: 1` (without
`!important`) is insufficient. xterm's own `.invisible` class rule
(`.xterm .xterm-scrollable-element > .invisible { opacity: 0; pointer-events: none }`) has the same
CSS specificity (0,3,0) as our rule but appears **later** in the Vite-built CSS bundle (`xterm.css`
is imported from `XTerminal.jsx`, processed after `index.css`). Same specificity + later position =
xterm's rule wins whenever it toggles `.invisible`, hiding the scrollbar and killing `pointer-events`.

**Fix:** Use `opacity: 1 !important` and `pointer-events: auto !important` so our rule wins
regardless of bundle ordering:
```css
/* !important required — xterm's .invisible rule is later in the bundle at equal specificity */
.xterm .xterm-scrollable-element > .scrollbar {
  opacity: 1 !important;
  pointer-events: auto !important;
}
.xterm .xterm-viewport { scrollbar-width: none; }   /* hide native, keep overlay */
```
**Never** add `display: none !important` to `.scrollbar`, `.xterm-viewport`, or any other xterm
internal element. Always use `!important` when overriding xterm's `.visible`/`.invisible` rules.

#### Requirement 2 — Follow-up textarea must have `overflow: hidden`

**Root cause:** The follow-up textarea in `App.jsx` (the "Ask me anything..." input below the
terminal) must have `overflow: "hidden"`. If set to `overflow: "auto"` or `overflow: "scroll"`,
Chromium treats it as a scrollable container and delivers wheel events to it instead of
propagating to xterm — even though the textarea has no overflowing content to scroll.

**Fix:** The textarea style must include `overflow: "hidden"` (not `auto`, not `scroll`).
Auto-resize is handled via `onInput` height adjustment; overflow:hidden does not break that.
```jsx
style={{ ..., overflow: "hidden", overflowX: "hidden" }}
```
**Regression risk:** This value is reset to `overflow: "auto"` by any merge that includes
an older version of `App.jsx`. Always verify after merging branches that predate PR #228.

#### Requirement 3 — Wheel events must not bubble out of the terminal container

**Root cause:** Even when xterm processes a wheel event internally, DOM bubbling still propagates
it up to ancestor elements. If a scrollable parent (e.g., the input textarea) is encountered,
Chromium delivers the event there too — causing the input box to scroll instead of the terminal.
`attachCustomWheelEventHandler` returning `true` does not stop DOM bubbling.

**Fix:** Add `event.stopPropagation()` in the wheel handler on the container:
```js
containerRef.current.addEventListener("wheel", (e) => {
  e.stopPropagation();  // safe with passive:true — only preventDefault is blocked
}, { passive: true });
```

#### Requirement 4 — `overscroll-behavior: contain` on `.xterm-viewport`

Prevents scroll chaining: when the terminal buffer is fully scrolled (top or bottom), wheel
events would otherwise bubble to the parent container (sidebar, page) and scroll it instead.
```css
.xterm .xterm-viewport { overscroll-behavior: contain; }
```

#### Requirement 5 — Do not install a custom capture-phase wheel handler on the terminal container

**Root cause:** A custom wheel handler registered as `{ capture: true }` on the xterm container
intercepts events before xterm's own handlers run. Any handler that calls `event.preventDefault()`
or manually calls `term.scrollLines()` will compete with xterm's native scroll handling, producing
erratic behavior (double-scroll, wrong scroll direction, broken text-selection-drag-to-scroll).

**Fix:** Remove all capture-phase wheel handlers from the xterm container. xterm.js v6 handles
wheel events correctly via its internal `MouseService` when Requirements 1–4 are satisfied.
A passive debug-only listener (`{ passive: true }`) is acceptable for diagnostics but must
never call `preventDefault()` or `term.scrollLines()`.

#### Summary — what breaks scroll wheel

| Symptom | Root cause | Requirement |
|---|---|---|
| Wheel does nothing in terminal | `display: none` on `.scrollbar` | Req 1 |
| Scrollbar disappears / wheel stops working after inactivity | `opacity:1` without `!important` | Req 1 |
| Wheel scrolls the text input instead (machine-specific) | `pointer-events: none` on `.scrollbar` causes wheel events to fall through to the canvas. On some Windows/Electron builds (GPU compositing interactions) that escapes the xterm stacking context and events reach the textarea. **`pointer-events: auto` is always correct**: events bubble `.scrollbar` → `.xterm-scrollable-element` → containerRef.current → our `stopPropagation()`. xterm's `alwaysConsumeMouseWheel` defaults to `false` so it doesn't consume events in alt-screen; they just bubble to our container and stop there, never reaching the textarea. The `.slider` thumb does NOT need a separate rule. | Req 1 |
| Wheel scrolls the text input instead | `overflow: auto` on textarea | Req 2 |
| Wheel bubbles to input box even with correct textarea overflow | Missing `stopPropagation` in wheel handler | Req 3 |
| Wheel scrolls sidebar instead of terminal | Missing `overscroll-behavior: contain` | Req 4 |
| Double-scroll or wrong direction | Custom capture-phase wheel handler | Req 5 |
| Scrollbar thumb stays at 100% | Post-replay fit timing (see Lesson #9) | Lesson #9 |

**Files to check after any merge touching xterm/App.jsx:**
- `ui/src/index.css` — `.scrollbar` must use `opacity: 1 !important; pointer-events: auto !important`
- `ui/src/App.jsx` — follow-up textarea must have `overflow: "hidden"`
- `ui/src/XTerminal.jsx` — wheel handler must call `stopPropagation()`; no capture-phase handler



**Root cause:** The skills panel in `App.jsx` rendered skills in the order returned by the skills loader, which depended on filesystem enumeration order — non-deterministic across platforms and runs.

**Fix pattern:** Sort skill lists alphabetically before rendering: `[...skills].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))`. Apply to any user-facing list where a stable order improves usability.

## Build & Run

```powershell
# Desktop app — development
cd ui
npm install                  # Also runs postinstall (patches node-pty)
npx electron-rebuild -m . -o @homebridge/node-pty-prebuilt-multiarch  # Compile native PTY
npm run dev                  # Vite + Electron (concurrently)

# Desktop app — production build
npm run build:win            # Windows NSIS installer → ui/release/

# Python scripts
pip install -r requirements.txt
pytest                       # Run tests
```

## Desktop App Architecture

### Dual Execution Model

The Electron main process (`ui/electron/main.js`) supports two execution paths for Agency CLI, with automatic preference for PTY when available:

| Path | When Used | How It Works |
|------|-----------|--------------|
| **PTY (preferred)** | node-pty compiled + agency detected | `agency copilot` in pseudo-terminal, interactive TUI mode |
| **Piped stdio (fallback)** | node-pty unavailable | `agency copilot -p "..."` with piped stdin/stdout |

### PTY Mode — Agency-in-PTY

The primary execution model spawns `agency.exe copilot` (without `-p`) inside a node-pty pseudo-terminal. This gives copilot.exe a real TTY, enabling its interactive TUI mode.

**Process flow:**
1. `pty.spawn("agency.exe", ["copilot", "--resume=<id>", ...])` — agency starts, bootstraps MCP servers, authenticates, loads CLAUDE.md/AGENTS.md
2. Agency internally spawns `copilot.exe` with `.status()` (inherited stdio) — copilot's TUI attaches to the PTY
3. After the interactive prompt becomes visible (e.g. `❯ Type @`), the first prompt is injected via bracketed paste then `\r` after 500ms (see "PTY Prompt Injection" section below)
4. Follow-up prompts go via `pty.write()` — the process stays alive between prompts (instant follow-ups)
5. Response content is read from copilot's **session JSONL log** (not the PTY stream)

**Why agency, not copilot directly:**
- Agency handles MCP server bootstrap, authentication, and custom instruction injection automatically
- Session resume via `--resume` works naturally (agency manages session lifecycle)
- Single process tree — no dual-process orchestration needed
- Without `-p`, agency launches copilot in true interactive mode (not autopilot)

**Key implementation details:**
- node-pty is a **lazy optional import** — if the native binary isn't available, PTY mode is disabled and the app falls back to piped stdio
- The `@homebridge/node-pty-prebuilt-multiarch` package requires a Spectre mitigation patch on Windows (see `ui/scripts/patch-node-pty.js`) — the postinstall script handles this automatically
- Text and Enter (`\r`) are sent as **separate writes** with a 500ms delay — see "PTY Prompt Injection" for full details on focus-in, bracketed paste, and IPC roundtrip
- **Mode switches** use Shift+Tab (`\x1b[Z`) keypresses to cycle the TUI mode selector (default → plan → autopilot). This works even while the agent is busy. Modes outside the cycle (yolo) fall back to slash commands.
- **Model switching** requires kill + respawn with `--resume` (no in-session `/model` command exists)
- Agency can continue booting while some MCP servers are still slow or warning (for example `workiq`/`qmd`). The PTY wrapper should not wait for every MCP server to finish connecting before sending the first prompt.
- A `"Loading environment:.*skills"` heuristic is too early and unreliable: it can appear while Copilot is still repainting/loading MCP state, causing the first injected prompt to be dropped. The safer readiness gate is a **real interactive prompt/TUI-ready line**.

### Output Architecture — JSONL Session Watcher

Copilot's interactive TUI re-renders the entire screen on every state change (loading progress, thinking spinner, response streaming). This makes PTY stdout unusable for extracting response content — it's a mix of ANSI codes, status bars, box-drawing borders, and duplicated lines.

**Solution:** The PTY stream is used only for input and lifecycle. Response content is read from copilot's structured session log at `~/.copilot/session-state/<uuid>/events.jsonl`.

| Data Source | Used For |
|-------------|----------|
| **PTY onData** | Diagnostic logging, agency bootstrap messages (🤖📦✅), interactive-prompt readiness detection, silence timer |
| **events.jsonl** | Assistant responses, tool calls, errors, warnings — all clean structured JSON |

**JSONL event types handled:**

| Event Type | Action |
|------------|--------|
| `assistant.message` | Forward `data.content` (markdown) to renderer |
| `tool.execution_start` | Show tool name notification |
| `tool.execution_complete` | Reset silence timer |
| `assistant.turn_end` | Signal turn complete |
| `session.error` | Forward error message |
| `session.warning` | Forward warning message |

**JSONL watcher implementation:**
- Polls the file every 200ms (`fs.watch` is unreliable on Windows for rapidly-appended files)
- Reads only new bytes since last check (tracks `bytesRead` offset)
- Buffers a trailing partial JSON line between polling reads so split append writes do not drop `assistant.message` / `assistant.turn_end` events
- On resume (`--resume`), starts reading from current file size (skips historical events)
- Session ID detected by scanning `~/.copilot/session-state/` for directories created after PTY spawn time
- Watcher is cleaned up on PTY exit

**Startup timing findings:**
- The first PTY startup delay is usually dominated by Agency/Copilot initialization and MCP startup, not by the PTY output filter itself.
- In observed traces, the old first-prompt heuristic fired before the TUI was actually ready to accept input; the prompt was written, but no `user.message` ever appeared in `events.jsonl`, confirming the submission was dropped.
- A targeted repro script (`ui/test-startup-gate.mjs`) exists to compare readiness gates and verify whether prompt injection produces `user.message` / `assistant.message` events in `events.jsonl`.

### Folder Trust Auto-Seeding

Copilot CLI requires workspace trust before processing prompts. The trust dialog is a
blocking modal that consumes any text already written to the TUI input. The app
pre-seeds trust before spawning the PTY so the dialog never appears.

**Mechanism:** `ensureFolderTrust(cwd)` adds the working directory to the
`trusted_folders` array in `~/.copilot/config.json` — the same entry the
dialog creates when the user selects "This and future sessions."

Reference: https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/configure-copilot-cli#editing-trusted-directories

### Interactive Dialog Handling (ask_user / Trust / EULA)

The Copilot model can invoke the `ask_user` tool to present questions with optional
multiple-choice answers. Additionally, CLI-level dialogs (folder trust, EULA
acceptance) may appear in the PTY stream. All of these are surfaced in the chat UI.

**Detection paths:**

| Dialog Type | Detection Source | Data |
|-------------|-----------------|------|
| `ask_user` tool call | JSONL `tool.execution_start` with `toolName === "ask_user"` | `{question, choices}` in arguments |
| Folder trust | PTY output matching `/not trusted\|Confirm folder trust/i` | — |
| EULA / user agreement | PTY output matching `/accept.*eula\|user agreement\|terms of service/i` | — |
| Autopilot permissions | PTY output matching `/Enable autopilot mode\|enable.*all permissions/i` | Auto-accepted (ESC[I + Enter after 300ms); option 1 "Enable all permissions" is pre-selected |

**IPC flow:**

1. Main process detects dialog → sends `task:prompt` to renderer with `{taskId, question, choices, toolCallId, source}`
2. Renderer shows `PromptBubble` component (choice buttons + optional freeform input)
3. User responds → renderer sends `task:respondToPrompt` back to main
4. Main writes to PTY: choices → `{down}` × index + `\r`; freeform → text + `\r`
5. JSONL `tool.execution_complete` fires → main sends `task:prompt-resolved` to renderer

**JSONL event types (27 total, 8 handled):**

`assistant.message`, `tool.execution_start`, `tool.execution_complete`,
`assistant.turn_start`, `assistant.turn_end`, `session.start`, `session.resume`,
`session.shutdown`, `session.task_complete`, `session.error`, `session.warning`,
`session.info`, `session.mode_changed`, `session.model_change`,
`session.plan_changed`, `session.context_changed`, `session.compaction_start`,
`session.compaction_complete`, `session.truncation`, `subagent.started`,
`subagent.completed`, `subagent.failed`, `user.message`, `abort`

### PTY Prompt Injection

The first user prompt and all follow-up prompts are injected into the Copilot CLI's
Ink-based TUI. This requires careful handling of terminal focus state, write context,
and timing.

#### Root Cause: Terminal Focus State (ESC[I / ESC[O)

Ink's `TextInput` component ignores all input when the hosting terminal reports
**focus-out** (`ESC[O`). xterm.js sends `ESC[O` whenever the user clicks outside the
terminal (e.g., on the send textbox or sidebar). It sends `ESC[I` (focus-in) when
the user clicks back into the terminal.

This means programmatic PTY writes are silently dropped unless the CLI believes the
terminal has focus. The fix: send `ESC[I` before injecting text or Enter.

#### Two Write Paths

| Context | Method | Why |
|---------|--------|-----|
| **Initial prompt** (new task spawn) | Direct `meta.proc.write()` | XTerminal component may not be mounted yet; IPC roundtrip would be lost |
| **Follow-up prompts** (existing session) | `injectPtyInput()` IPC roundtrip | XTerminal is mounted; IPC ensures consistent write context |
| **Enter key** (both paths) | `injectPtyInput()` with `ESC[I` | By the time the delayed Enter fires, xterm.js may have sent focus-out |

**IPC roundtrip** (`injectPtyInput`): `main.js` → `pty:injectInput` IPC → renderer
`XTerminal.jsx` listener → `task:ptyWrite` IPC → `main.js` handler → `meta.proc.write()`.
This ensures every write goes through the same handler context as keyboard input.

#### Ready Gate

```js
READY_RE = /Type @|Type \/|Describe a task|^[❯›]\s/im
```

The interactive prompt (`❯ Type @`) appears during MCP loading — the CLI accepts
input at this point. A 2-second delay after the match lets the TUI layout settle.
Safety fallback at 15s in case ready is never detected.

#### Injection Pattern

**Initial prompt** (`writePromptOnce` in `spawnPtyProcess`):
```
1. ESC[I                                   — focus-in (XTerminal may have sent ESC[O)
2. Ctrl+U (\x15)                           — clear input line
3. Bracketed paste: ESC[200~ text ESC[201~ — atomic text delivery
4. Wait 500ms + proportional delay         — let TUI process paste
5. ESC[I + \r  (direct write)              — focus-in then Enter
6. Retry \r after 3s if no JSONL activity  — safety net (IPC roundtrip)
```

**Follow-up prompt** (`writeToPty`):
```
1. ESC[I                                   — focus-in (via injectPtyInput)
2. Ctrl+U (\x15)                           — clear input line
3. Bracketed paste: ESC[200~ text ESC[201~ — atomic text delivery
4. Wait 500ms + proportional delay         — let TUI process paste
5. ESC[I + \r  (via injectPtyInput)        — focus-in then Enter
6. Retry \r after 3s if no JSONL activity  — safety net (direct write)
```

Both paths now follow the same `ESC[I → Ctrl+U → paste → delay → ESC[I → Enter`
pattern. The critical insight: focus-in must precede **text**, not just Enter —
Ink's TextInput drops all input (including bracketed paste) when unfocused.

#### Why Bracketed Paste

- **Atomic delivery**: Ink buffers the entire paste as one unit, preventing partial input
- **No shortcut triggers**: Raw `@` triggers mentions, `/` triggers commands — paste mode bypasses these
- **Re-render safe**: Text survives Ink's re-render storm (the TUI repaints ~every 100ms during loading)

#### Why IPC Roundtrip (Electron-specific)

On Windows with ConPTY, `meta.proc.write()` from `setTimeout` or HTTP server callbacks
does not reliably reach Ink's input handler — only writes from Electron IPC handler
context (same as keyboard input via xterm.js `onData`) work consistently. The IPC
roundtrip (`main → renderer → ptyWrite IPC → main`) guarantees the correct execution context.

#### PTY Bridge (Teams Monitor)

The PTY bridge (`skills/teams/scripts/monitor/pty-bridge/bridge.js`) uses the same
pattern but with direct `proc.write()` since it runs in a single Node.js process
(no Electron multi-context issues):
```
ESC[I → Ctrl+U → bracketed paste → delay → ESC[I → \r
```

#### Timing Summary

| Phase | Typical Timing |
|-------|---------------|
| PTY spawn → Agency banner | ~0.2s |
| Agency banner → "Loading environment" | ~1.6s |
| "Loading environment" → `❯ Type @` prompt | ~5-7s |
| Ready detection + 2s delay → text injection | ~7-9s |
| Text injection → Enter (500ms + proportional) | ~0.5-2s |
| "Environment loaded" (all MCP servers) | ~13-23s |

**Session detection caveat:** The CLI auto-resumes existing sessions when the same
working directory is used, so new runs may not create a new `workspace.yaml`. Tests
must detect sessions by monitoring ALL `events.jsonl` files for new events with
recent timestamps (broadcast watcher pattern), not by scanning for new workspace files.

#### Key Files

| File | Role |
|------|------|
| `ui/electron/main.js` | `injectPtyInput()`, `writeToPty()`, `writePromptOnce()`, debug HTTP API |
| `ui/src/XTerminal.jsx` | `onPtyInjectInput` listener (IPC roundtrip receiver) |
| `ui/electron/preload.js` | `onPtyInjectInput` bridge between main ↔ renderer |
| `skills/teams/scripts/monitor/pty-bridge/bridge.js` | Standalone bridge with same injection pattern |

#### Debug HTTP API (dev-only, port 9876)

Available when `NODE_ENV !== "production"`. Provides ring buffer of PTY I/O, state
inspection, and manual write/enter endpoints for debugging injection issues.

| Endpoint | Purpose |
|----------|---------|
| `GET /state` | Current PTY meta state (ready, promptSubmitted, etc.) |
| `GET /buffer?last=200&dir=in` | Ring buffer of recent PTY I/O with timestamps |
| `POST /write {taskId, text}` | Write arbitrary text to PTY (supports `\r`, `\x15`, etc.) |
| `POST /enter {taskId}` | Send focus-in + Enter via `injectPtyInput` |
| `POST /clear-booting {taskId}` | Force-send `pty-ready` event to renderer |


### PTY Commands (Mode / Model / File)

When the user selects a mode, model, or file from the UI pickers during an active
PTY session, the corresponding action is sent to the terminal:

| Action | IPC | Behavior |
|--------|-----|----------|
| **Mode change** | `setMode` | Shift+Tab (`\x1b[Z`) keypresses to cycle TUI mode selector: default(0) → plan(1) → autopilot(2). Falls back to slash commands for modes outside the cycle (e.g. yolo). |
| **Model change** | `ptyPrompt` | Ctrl+U clears input → bracketed paste `/model gpt-5.4` |
| **File attach** | `ptyPaste` | Bracketed paste `@filename` (no clear, no submit -- appends) |

Mode switching uses Shift+Tab because it operates on the TUI footer selector rather
than the input buffer, which means it works even while the agent is busy processing.
The process meta tracks `ptyMode` to calculate the number of Shift+Tab presses needed.

`writeToPty(taskId, text, { clearFirst, submit })` is still used for model changes and prompts:
- `clearFirst: true` -- sends Ctrl+U (`\x15`) before paste to discard existing input
- `submit: false` -- pastes text without sending Enter (for file mentions)

### Piped Stdio Mode — Fallback

When node-pty isn't available, the app falls back to spawning agency with piped stdio:

```
spawn("agency", ["copilot", "-p", prompt, "--resume=<id>", ...])
```

**Critical difference:** With `-p` present, Agency auto-adds `--autopilot`, `--no-ask-user`, and `--allow-all-tools` to copilot.exe. This runs copilot in one-shot mode — it processes the prompt and exits. Each prompt spawns a new process (no session persistence within a process).

### Terminal Interactions (Clipboard / Links)

XTerminal.jsx implements keyboard, mouse, and clipboard interactions that bypass SGR mouse tracking (enabled by the Copilot CLI for TUI navigation). All clipboard reads use the `app:clipboardReadText` IPC channel for secure Electron clipboard access.

**Paste (three paths):**
| Method | Mechanism | Detail |
|--------|-----------|--------|
| Ctrl-V / Cmd-V | `attachCustomKeyEventHandler` | Intercepts keydown, reads clipboard via IPC, writes to PTY. `preventDefault()` blocks native paste. Returns `false` to suppress `^V` control code. |
| Right-click | `contextmenu` listener on `term.element` (capture phase) | Reads clipboard via IPC, writes to PTY. `preventDefault()` suppresses browser context menu. |
| Bracketed paste (internal) | `writeToPty()` in main.js | Used by prompt injection for initial/follow-up prompts. Wraps text in `ESC[200~`…`ESC[201~`. |

**Copy:** Ctrl-C / Cmd-C with active selection → `navigator.clipboard.writeText(term.getSelection())`. Without selection, Ctrl-C falls through to xterm (sends `^C` / SIGINT to PTY).

**Clickable links:**
- **URLs** — `WebLinksAddon` detects and highlights `http://` / `https://` links. Normal clicks are intercepted by SGR mouse tracking, so activation uses **Ctrl+click** (Cmd+click on Mac) via a DOM `mouseup` handler that checks for the modifier key.
- **File paths** — `term.registerLinkProvider()` matches Windows (`C:\...\file.ext:line`) and Unix (`/path/file.ext:line`) patterns. Same Ctrl+click activation.
- **Tooltip** — A fixed-position `<div>` shows "Ctrl+click to open" (or "⌘+click") on hover over any detected link. Tracks `hoveredUri` / `hoveredFilePath` via addon `hover` / `leave` callbacks. Cleaned up on component unmount.
- **IPC chain** — URL clicks → `openExternalUrl` → `shell.openExternal()`. File clicks → `openFileExternal` → `shell.openPath()`.

### Process Lifecycle

Both PTY and piped modes share the same lifecycle management via a unified `processes` Map:

- **Fast path reuse**: If a process for the same `taskId` is still alive and the model matches, the prompt is written to stdin/PTY (no respawn)
- **Model change**: If the requested model differs, the old process is killed and a new one spawned with `--resume`
- **Orphan detection**: On startup with `--resume`, checks for stale agency processes holding the session and prompts the user before killing them
- **Graceful stop**: Ctrl+C (`\x03` to stdin on Windows, `SIGINT` on Unix), with 3s timeout before force kill
- **Idle timeout**: 5 minutes of no activity → auto-kill

### Session Management

Sessions are identified by UUID and persisted to `~/.copilot/session-state/<uuid>/`. The app:
1. Captures the session ID from new sessions by monitoring the session-state directory
2. Sends the ID to the renderer via `task:sessionId` IPC event
3. Reuses the ID for `--resume` on subsequent prompts
4. Stores it on the process metadata for model-change respawn

### IPC Channel Reference

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `task:start` | Renderer → Main | Start or continue a task |
| `task:stop` | Renderer → Main | Graceful stop (Ctrl+C) |
| `task:input` | Renderer → Main | Send follow-up prompt to alive PTY/pipe process |
| `task:setMode` | Renderer → Main | Switch execution mode (`/defaults`, `/plan`, `/autopilot`, `/yolo`) |
| `task:respondToPrompt` | Renderer → Main | User response to ask_user/trust/EULA dialog |
| `task:output` | Main → Renderer | Structured output events (see Output Event Types below) |
| `task:done` | Main → Renderer | Process exited (with exit code) |
| `task:debug` | Main → Renderer | Spawn info, PTY events, diagnostics |
| `task:sessionId` | Main → Renderer | Captured session ID for resume |
| `task:prompt` | Main → Renderer | Interactive dialog (ask_user, trust, EULA) |
| `task:prompt-resolved` | Main → Renderer | Dialog resolved (tool.execution_complete) |
| `task:orphanDetected` | Main → Renderer | Stale process warning |
| `task:killOrphans` | Renderer → Main | User confirmed orphan kill |
| `app:clipboardReadText` | Renderer → Main | Read system clipboard text (for Ctrl-V / right-click paste) |
| `app:openExternalUrl` | Renderer → Main | Open URL in system browser (`https://` only) |
| `file:openExternal` | Renderer → Main | Open file path in OS default app |

### Output Event Types (`task:output`)

The `type` field in `task:output` events determines how the renderer processes the data:

| Type | Source | Renderer Handling |
|------|--------|-------------------|
| `stdout` | PTY bootstrap filter | Line-buffered, parsed by `parseCLIOutput()` for TUI markers |
| `assistant` | JSONL `assistant.message` | Direct to output bubble (bypasses TUI parser) — markdown content |
| `tool-status` | JSONL `tool.execution_start` | Rendered as tool badge |
| `turn-complete` | JSONL `assistant.turn_end` | Transitions UI from "Running" → "Ready" (waiting for next prompt) |
| `error` | JSONL `session.error/warning` | Rendered as error line |
| `prompt` | JSONL `tool.execution_start` (ask_user) / PTY (trust, EULA) | Rendered as PromptBubble with choice buttons + freeform input |

### UI State Machine (PTY Mode)

```
[Booting] → first output → [Running] → turn_end → [Waiting/Ready]
                                                        │
                                                  follow-up prompt
                                                        │
                                                        ▼
                                                   [Running] → turn_end → [Waiting/Ready]
                                                   
[Waiting/Ready] → process exit → [Done]
[Running] → process exit → [Done]
```

- **Booting**: PTY spawned, agency loading MCP servers. Shows bootstrap messages.
- **Running**: Prompt submitted, copilot processing. Shows "Working" animation.
- **Waiting/Ready**: Turn complete, process alive. Shows "● Ready", accepts follow-up input.
- **Done**: Process exited. Shows final state.

### Agent / Folder Switching and Terminal Lifecycle

When the user switches context folders (Change Context Folder) or relaunches a
stopped session, the terminal must fully reset. Two mechanisms enforce this:

**1. XTerminal `key` prop** — `<XTerminal key={activeTask.id} .../>` forces React
to fully unmount the old terminal instance and mount a fresh one when the task ID
changes. Without `key`, React reuses the component and the `useEffect` cleanup +
re-init may leave stale content in the DOM container.

**2. PTY buffer clearing** — `ptyBuffersRef.current.delete(taskId)` in `startTask()`
when `append` is false. Without this, the XTerminal would replay old PTY data on
mount via `ptyBuffer.current.join("")`.

**When `append: true` is appropriate:**
- `restartForAuth()` — MCP token refresh preserves session history
- Follow-up prompts via `sendInput` (same process, same terminal)

**When `append: false` (default):**
- New task creation (`dispatchTask`)
- Folder switch (`handleSwitchAgent`) — new taskId, fresh terminal
- Relaunch after stop — same taskId but clean terminal

**Common pitfall:** React batches state updates. During a folder switch,
`stopTask()` and `setActiveTask(freshTask)` may execute in the same render cycle.
If `isPty` stays truthy throughout (old task → new task), XTerminal never
unmounts. The `key` prop prevents this by forcing a DOM-level remount regardless
of React batching.

## Agency CLI Integration

### Flag Behavior

| Flag | Effect |
|------|--------|
| `-p "prompt"` | Non-interactive: auto-adds `--autopilot`, `--no-ask-user`, `--allow-all-tools` |
| No `-p` | Interactive TUI mode (needs real TTY — PTY provides this) |
| `--resume=<id>` | Resume existing session |
| `--model <name>` | Override AI model |
| `--add-dir <path>` | Grant read access to additional directory |

### Graceful Stop

Agency CLI treats **SIGINT** (Ctrl+C, exit code 130) as graceful user cancellation — not an error. Rust's `Drop` trait automatically cleans up sessions, flushes logs, archives artifacts, and tears down MCP proxies.

- **Windows**: Write `\x03` (Ctrl+C character) to the process's stdin
- **Unix**: Send `SIGINT` to the process group (`process.kill(-pid, 'SIGINT')`)
- **Fallback**: Force kill (`taskkill /T /F` or `SIGKILL`) after a 3-second timeout

### CLAUDE.md/AGENTS.md Loading

Both agency and copilot CLI contribute to custom instruction loading:

1. **Copilot CLI (native)**: Reads `CLAUDE.md` and `AGENTS.md` from the git root of any `--add-dir` path. Has `--no-custom-instructions` flag to disable.
2. **Agency CLI (additional)**: Injects instructions as the first `user.message` in session JSONL, and sets `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` env var.
3. **PTY mode**: Native support is sufficient — `--add-dir <project-root>` ensures auto-loading.

### Key Source References

| File | Lines | What |
|------|-------|------|
| `copilot.rs:432-461` | Engine spawn | `Command::new(copilot_path)` with inherited stdio |
| `copilot.rs:571-584` | Flag injection | Auto-adds `--autopilot --no-ask-user` when `-p` present |
| `copilot.rs:705` | Execution | `.status()` blocks until copilot exits |
| `copilot.rs:735-746` | Exit handling | Non-zero exit → `launch_engine` error |

> **Source**: `~/.agency/source/<version>/content/client/agency/src/copilot.rs` (Agency CLI Rust source, version 2026.3.7.5)

## Setup Wizard Architecture

The `SetupWizard.jsx` component handles both fresh installs (OOBE) and upgrades with distinct step sequences:

### Install Steps (OOBE)

| Step | ID | Purpose |
|------|----|---------|
| 0 | `welcome` | Welcome screen, version display |
| 1 | `folder` | Choose or browse target folder; "Use Existing Project" option |
| 2 | `extract` | Copy bundled-project files to target folder |
| 3 | `setup` | Run `setup.ps1` / `setup.sh` (MCP config, git, deps) |
| 4 | `org` | Organization repo sync (CLAUDE.md/AGENTS.md from org repo) |
| 5 | `services` | Start task scheduler, Teams monitor |
| 6 | `cli` | CLI instructions |
| 7 | `done` | Summary and launch |

### Update Steps (Upgrade Wizard)

| Step | ID | Purpose |
|------|----|---------|
| 0 | `welcome` | Show what's new, version comparison |
| 1 | `update` | Run `setup:updateProject` (backup + file sync) |
| 2 | `org` | Re-sync org repo |
| 3 | `memory` | Memory migration (local/git → OneDrive) |
| 4 | `services` | Restart scheduler/monitor |
| 5 | `done` | Summary |

### "Use Existing Project" Flow

When a user points to an existing Agency Cowork folder (step 1), the wizard detects `agencycowork.json` and offers "Use Existing Project". This flow now checks for stale files:

1. **Version check** — `setup:checkExistingProject` compares the app's `package.json` version against `agencycowork.json` in the target folder
2. **If versions match** — skip extraction, jump directly to step 3 (setup script)
3. **If versions differ** — show a confirmation dialog with installed vs bundled versions
   - **"Update Files →"** — calls `setup:updateProject` which creates a timestamped backup, syncs all scripts/skills/docs while preserving user data (CLAUDE.md, memory/), then advances to step 3
   - **"Skip — Use As-Is"** — proceed without updating, jump to step 3

**Key design decision:** The update uses the same `setup:updateProject` handler as the upgrade wizard, avoiding code duplication. The handler emits `setup:progress` events that the existing progress listener captures.

### Setup IPC Channels

| Channel | Direction | Purpose |
|---------|-----------|---------|
| `setup:getDefaults` | R → M | Get default folder path, detected OneDrive path |
| `setup:checkFolder` | R → M | Check if target folder already has an install |
| `setup:checkExistingProject` | R → M | Compare bundled version vs installed version |
| `setup:extractFiles` | R → M | Copy bundled-project to target (fresh install) |
| `setup:updateProject` | R → M | Backup + sync files (upgrade and existing-project update) |
| `setup:runSetup` | R → M | Execute setup.ps1/setup.sh with flags |
| `setup:installDep` | R → M | Install individual optional dependency |
| `setup:complete` | R → M | Write agencycowork.json + default-folder.json |
| `setup:verifyAuth` | R → M | Check `az account show` for Azure CLI auth |
| `setup:progress` | M → R | Progress/log/done events from extract, update, and setup |
| `setup:detectOneDrive` | R → M | Find OneDrive path and existing memory setups |
| `setup:configureMemory` | R → M | Set up OneDrive junction/local/git for memory |

### Phase 7 Optional Dependencies (setup.ps1)

Phase 7 installs optional tools (QMD, MarkItDown, sentence-transformers) that enhance skills. During OOBE, this phase is skipped entirely via `-InstallDeps none`. The UI's `setup:installDep` handler lets users install them individually later from Settings.

**Detection hardening (Windows):** Electron-spawned PowerShell has a different PATH than the user's shell. Detection uses multi-strategy fallbacks:
- **QMD:** `Get-Command qmd` → npm global prefix lookup (`npm prefix -g`) → filesystem scan of known locations
- **MarkItDown:** `pip show markitdown 2>&1 | Out-String` → `python -c "import markitdown"`
- **sentence-transformers:** `pip show sentence-transformers 2>&1 | Out-String` → `python -c "import sentence_transformers"`

## node-pty Build Notes

The `@homebridge/node-pty-prebuilt-multiarch` package ships Linux prebuilts but requires compilation from source on Windows. Build requirements:

- **Visual Studio 2022 Build Tools** with VCTools workload
- **electron-rebuild** to compile for Electron's Node ABI (Electron 35 = ABI 133)
- **Spectre patch**: The upstream `binding.gyp` requires Spectre-mitigated libraries (`SpectreMitigation: 'Spectre'`). The postinstall script (`ui/scripts/patch-node-pty.js`) changes this to `'false'` so standard VS Build Tools suffice.

Produces three native binaries: `conpty.node`, `pty.node`, `conpty_console_list.node` — unpacked from ASAR in production builds via `asarUnpack` config.

## OneDrive Cloud-Synced Memory

The setup wizard (step 3) offers three memory storage modes:

| Mode | How It Works | Best For |
|------|-------------|----------|
| **OneDrive** (recommended) | Creates `<OneDrive>/Agency Cowork/<folder>/memory/` and links via NTFS junction (Windows) or symlink (macOS). Also links `output/`. | Cross-device sync, automatic cloud backup |
| **Local** | Direct `memory/` directory inside working folder | Simple, no external deps |
| **Remote Git** | Clones a private Git repo into `memory/` | Version-controlled, shareable between agents |

### OneDrive Detection Priority

**Windows:** `%OneDriveCommercial%` → `%OneDrive%` → `~/OneDrive - Microsoft` → `~/OneDrive`

**macOS:** `$ONEDRIVE_COMMERCIAL_MAC` → `~/Library/CloudStorage/OneDrive-Microsoft` → glob `OneDrive-*` → legacy paths

### Key Implementation Details

- **`detectOneDrivePath()`** — returns first existing candidate directory
- **`isInsideOneDrive(dirPath)`** — case-insensitive path prefix check; skips junction/symlink creation when working folder is already inside OneDrive
- **Junction vs symlink:** Windows uses `fs.symlinkSync(target, link, 'junction')` (no admin/Dev Mode needed); macOS uses `'dir'` type
- **New-machine reuse:** `setup:detectOneDrive` scans `<OneDrive>/Agency Cowork/*/memory/MEMORY.md` for existing setups; wizard shows them with file counts
- **Folder dedup:** If the folder name already exists in OneDrive, auto-suffixes (`-2`, `-3`, etc.)
- **Upgrade restoration:** `migrateAgentConfig()` checks `config.memory.location === "onedrive"` and re-creates junctions if they were replaced by plain directories during upgrade file restore
- **Locked folder handling:** `EBUSY`/`EPERM`/`EACCES` on `rmSync` returns `{ locked: true }` → wizard shows retry/skip modal
- **Smart merge:** `mergeDirectories(srcDir, destDir, backupDir)` compares each file by `mtime` — source newer copies over (backs up dest), dest newer keeps (backs up source), same mtime skips. Backup at `<project>/memory-backup-<timestamp>/` (auto-removed if empty). Applied to both memory/ and output/ migration.

### Config Schema (`agentconfig.json`)

```json
{
  "memory": {
    "location": "onedrive",
    "onedrivePath": "C:\\Users\\user\\OneDrive - Microsoft\\Agency Cowork\\MyProject\\memory",
    "onedriveOutputPath": "C:\\Users\\user\\OneDrive - Microsoft\\Agency Cowork\\MyProject\\output"
  }
}
```

## Configurable Reply Prefix

All Teams outbound messages use a single configurable prefix (default: `"Agency Cowork: "`).

- **Monitor path:** `config.py` loads → `service.py` calls `set_reply_prefix()` → `message_handler.py` uses module-level `_reply_prefix`
- **Skill path:** `scripts/api/messages.py` reads via `_get_reply_prefix()` on each send call
- **Self-loop filter:** `message_handler.py` uses `config.reply_prefix.rstrip()` to skip messages the agent itself sent
- **UI:** Editable in Settings → Teams → Reply Prefix; preserved on upgrade via `migrateAgentConfig()`
- **Storage:** Per-workspace in `~/.agency-cowork/monitor-config.json → workspaces.<path>.reply_prefix`

## Global Monitor Configuration

Monitor configuration is stored **globally** at `~/.agency-cowork/monitor-config.json`, not inside the repo. This prevents collaborator pushes from overwriting identity/config, and enables a single monitor service to dispatch to multiple workspace agents.

### Config structure

```json
{
  "enabled": false,                      // Global — master service on/off toggle
  "identity": {                         // Global — one Teams identity per user
    "mri": "8:orgid:<GUID>",
    "displayName": "Your Name",
    "upn": "user@contoso.com"
  },
  "connection": { ... },                // Global — Trouter/registrar settings
  "workspaces": {
    "c:\\projects\\agency-cowork": {     // Per-workspace (keyed by normalised path)
      "enabled": false,                 // Safe default: off
      "keyword": "@agent",
      "reply_prefix": "Agency Cowork: ",
      "monitored_conversations": [...],
      "dispatch": {
        "command": "agency copilot",    // No -p flag — PTY mode requires interactive
        "working_directory": "C:\\Projects\\agency-cowork",
        "timeout_minutes": 15,
        "use_persistent_pty": true,
        ...
      }
    }
  }
}
```

### Architecture

```
  Trouter (Teams WebSocket)
       │
  Monitor Service (singleton process)
       │  reads ~/.agency-cowork/monitor-config.json
       │  starts only if top-level enabled=true
       │  one identity, one connection, global dedup + sender check
       │
       ├── WorkspaceHandler("C:\Projects\project-a")
       │     keyword: @agent, conversations: [48:notes]
       │     dispatch → agency copilot (cwd: project-a)
       │
       └── WorkspaceHandler("C:\Projects\project-b")
             keyword: @helper, conversations: [*]
             dispatch → agency copilot (cwd: project-b)
```

### Message routing

1. Trouter delivers message to the single monitor service
2. **Global dedup** — skip already-processed message IDs
3. **Global sender check** — `identity.mri` must match sender; rejects all others
4. **Per-workspace matching** — iterate enabled workspaces, check keyword + conversation
5. **First match wins** — no double-dispatch across workspaces

### Migration from legacy per-repo config

On first load, `config.py` checks for a legacy `skills/teams/monitor/monitor-config.json`. If found, it migrates identity/connection to global and workspace settings to the correct workspace key, then renames the old file to `.json.migrated`. The old path is also `.gitignore`d to prevent future conflicts.

Migration rules:
- **Top-level `enabled`** is always set (defaults to `false` if missing)
- **Keyword** is pulled from `agentconfig.json` first (user's actual keyword), then falls back to legacy config
- **Identity** is only migrated if the current global identity is a placeholder (all-zero GUID)
- **Connection** is only migrated if the legacy config has a non-default `chatsvc_region`
- **Existing workspace entries** are never overwritten if they are already enabled — prevents re-migration from clobbering user-configured values

### Config precedence

```
load_config() precedence:
  1. Global config workspace entry exists?
     YES -> Use global config values. enabled = workspace.enabled
            Do NOT apply agentconfig.json overrides.
     NO  -> Fall through to legacy path.

  2. Legacy per-repo monitor-config.json exists?
     YES -> Load it, migrate to global, override enabled/keyword from agentconfig.json
     NO  -> Create default MonitorConfig, save it, backfill from agentconfig.json
```

`agentconfig.json` is a local convenience mirror for the Settings UI. It is NOT authoritative once a global workspace entry exists.

### Key files

| File | Role |
|------|------|
| `~/.agency-cowork/monitor-config.json` | Global config (identity, connection, workspaces) |
| `skills/teams/scripts/monitor/config.py` | `GlobalConfig`, `WorkspaceConfig`, `MonitorConfig`; load/save/migrate |
| `skills/teams/scripts/monitor/service.py` | Singleton service; multi-workspace message router |
| `skills/teams/scripts/monitor/message_handler.py` | Per-workspace `MessageHandler` (keyword, dispatch, reply) |

## Smart Permission Mode

**Smart Permission** is an optional execution mode between "AFK" (autopilot) and "YOLO". Instead of blanket approval (YOLO) or manual confirmation (Default), it uses the `smart-permission` Copilot CLI plugin (v3.3.1) to make intelligent 4-tier permission decisions:

1. **Fast rules** (<100ms) — pattern-matched allow/deny for common operations (file reads, git status, `rm -rf`)
2. **Command analysis** — deeper inspection of shell commands, paths, and arguments
3. **AI classification** (~2.5–4.5s) — uses Copilot CLI's LSP for genuinely ambiguous edge cases
4. **Defer** — falls back to the built-in permission system for unrecognized tools

### Architecture

The plugin is a `preToolUse` hook installed via the Copilot CLI plugin marketplace:
- **Source**: `agency-microsoft/playground` → `plugins/smart-permission/`
- **Runtime**: Perl 5.14+ (ships with Git Bash on Windows at `C:\Program Files\Git\usr\bin\perl.exe`)
- **Hook**: `.claude-plugin/hooks.json` → `PreToolUse` event → `scripts/smart-permission.pl`
- **Decision output**: `{ permissionDecision: "allow"|"deny", permissionDecisionReason: "..." }` or `{}` (defer)

### Integration Points

| Layer | File | What it does |
|-------|------|-------------|
| Config | `agentconfig.json` | `smartPermission` section: enabled, model, debug, timeout, MCP safe/ask tool lists |
| Backend | `ui/electron/main.js` | `monitorSmartPermission` var, `buildBridgeEnv()` forwards env vars, `plugin:ensureSmartPermission` IPC auto-installs plugin, `getConfig`/`saveConfig` handle persistence |
| Bridge | `skills/teams/scripts/monitor/pty-bridge/bridge.js` | `smartPermissionMode` flag, guards `/yolo` injection, `set_smart_permission` pipe command, mutual exclusion with yolo |
| UI | `ui/src/App.jsx` | "Smart" execution mode (purple, `ShieldCheck` icon), toggle in SettingsPanel, mutual exclusion with YOLO toggle |
| Preload | `ui/electron/preload.js` | `ensureSmartPermission` IPC bridge |

### Mutual Exclusion (Smart ↔ YOLO)

Enforced at three layers to prevent conflicts:
1. **UI**: Toggle disables the other; `effectiveYolo = smartPermission ? false : yoloMode`
2. **Main process**: `saveConfig` forces `monitorYoloMode = false` when `smartPermission && monitorYoloMode`
3. **Bridge**: `set_smart_permission` sets `yoloMode = false`; `set_yolo` sets `smartPermissionMode = false`

### Environment Variables

| Variable | Source | Purpose |
|----------|--------|---------|
| `BRIDGE_SMART_PERMISSION` | main.js → bridge | "0" or "1" — activates smart permission mode in bridge |
| `SMART_PERMISSION_MODEL` | agentconfig.json | AI model for classification (default: `claude-haiku-4.5`) |
| `SMART_PERMISSION_DEBUG` | agentconfig.json | "1" enables debug logging to `$TEMP/smart_permission_debug.log` |
| `SMART_PERMISSION_TIMEOUT` | agentconfig.json | Timeout in seconds for AI classification (default: 30) |
| `CLAUDE_MCP_SAFE` | agentconfig.json | Space-separated MCP tool names to auto-approve |
| `CLAUDE_MCP_ASK` | agentconfig.json | Space-separated MCP tool names requiring confirmation |

### Known Limitations

1. **Format compatibility**: Plugin was designed for Claude Code's input format (`tool_name`, `tool_input`). Copilot CLI uses camelCase (`toolName`, `toolArgs`). The plugin marketplace install may provide a compat layer — needs live verification.
2. **Piped mode**: In Teams Monitor (piped, no interactive user), "ask"/deferred items are auto-approved since there's no user to prompt. The deny tier still blocks dangerous commands.
3. **Perl dependency**: Requires Perl 5.14+. Windows users need Git Bash installed (ships Perl at `C:\Program Files\Git\usr\bin\perl.exe`).

## Handy (Speech-to-Text) Integration

Agency Cowork integrates with [Handy](https://github.com/cjpais/handy), a free, open-source, offline speech-to-text application. Handy runs as a standalone desktop app using Whisper/Parakeet models — all transcription happens locally, no cloud.

### How It Works

1. **Voice mode** — Click the mic button (or future configurable shortcut) to enter voice mode
2. **Push-to-talk** — Press Space bar (while not focused on a text input) to toggle recording
3. **Transcription** — Handy processes speech locally and pastes the text into the focused field
4. **Exit** — Click mic again or press Escape to leave voice mode

### Architecture

Handy is a system-level tool, not an MCP server. Agency Cowork manages it via CLI flags:

| IPC Channel | Action | CLI |
|-------------|--------|-----|
| `handy:check` | Detect installation | `where handy` + well-known paths |
| `handy:launch` | Start hidden in background | `handy --start-hidden` |
| `handy:toggle` | Toggle transcription on/off | `handy --toggle-transcription` |
| `handy:status` | Check if process is running | `tasklist` / `pgrep` |

### Installation

- **Windows**: `winget install cjpais.Handy`
- **macOS**: `brew install --cask handy`
- **Linux**: Download from [releases](https://github.com/cjpais/handy/releases)

Setup scripts (`setup.ps1` / `setup.sh`) offer Handy as an optional dependency.

### Configuration

`agentconfig.json` contains a `handy` section:

```json
{
  "handy": {
    "enabled": false,
    "autoStart": false,
    "startHidden": true,
    "shortcutKey": "Space"
  }
}
```
## Skill Customization & Upgrade Behavior

### `skill.json` Manifest

Each bundled skill has a `skill.json` at its root:
```json
{
  "name": "task-scheduler",
  "version": "1.0.3",
  "description": "Schedule one-time and recurring tasks",
  "userDataPaths": ["tasks", "logs"],
  "userConfigPaths": ["monitor/monitor-config.json"]
}
```

- **`version`** — semver, compared during upgrades. Skill is only replaced when the bundled version is newer.
- **`userDataPaths`** — directories preserved during upgrade (runtime data).
- **`userConfigPaths`** — files preserved during upgrade (user configuration).

### Customizing Skills — Best Practices

**Rename when customizing.** If you want to modify a bundled skill, **copy it to a new name** rather than editing in-place:
```
skills/weekly-report/    ← bundled, will be updated on upgrade
skills/my-weekly-report/ ← your custom copy, never touched by upgrade
```

Update the skill table in `AGENTS.md` to reference your renamed skill. Upgrades will add the new bundled version alongside your custom one.

**Why:** The upgrade process replaces bundled skills by name when a newer version is available. User-created skills (names not matching any bundled skill) are always preserved.

### Upgrade Merge Logic

During `setup:updateProject` (upgrade wizard):
1. Each bundled skill's `skill.json` version is compared to the installed version
2. **Same or newer installed** → skill is skipped entirely (no files touched)
3. **Older installed** → skill is replaced, but `userDataPaths` and `userConfigPaths` are preserved
4. **User-created skills** (not in bundle) → kept as-is, never deleted

The entire `skills/` directory is backed up before any changes.

## Task Scheduler Architecture

The task scheduler uses a **dual-engine** design for maximum reliability — tasks execute even when the desktop app is closed.

### Engine 1: Electron node-cron (in-process)

- **Library:** `node-cron` — creates in-process cron jobs via `startCronJob()`
- **Trigger chain:** `initializeScheduler()` → `startCronJob()` → `handleScheduleTrigger()` → `executeScheduledTask()` → spawns `agency copilot -p <prompt>`
- **Data store:** `~/.agency-cowork/schedules.json` (global, JSON array)
- **Lifetime:** Runs only while the Electron app is open
- **Startup:** `initializeScheduler()` called 2 seconds after app ready

### Engine 2: PowerShell daemon (background service)

- **Entry point:** `skills/task-scheduler/scripts/scheduler-service.ps1`
- **Management:** `task-manager.ps1 ensure-running | stop | status`
- **Polling:** Reads `tasks/*.json` every 60 seconds; if `task.next_run` is past-due, spawns `run-task.ps1`
- **Sync:** Bi-directional sync with `~/.agency-cowork/schedules.json` every 5 polls (~5 min)
- **Lifetime:** Survives app close — runs as a detached PowerShell process
- **Launch directory:** Workspace directory (e.g., `C:\Users\X\Documents\Agency-Cowork`), same as Teams monitor

### Mutual Exclusion (Double-Execution Prevention)

Both engines independently evaluate whether a task is due. Without coordination, the same task fires twice. The fix:

1. **At trigger time**, `advanceWorkspaceTaskNextRun()` writes `last_run` + advances `next_run` by 61 seconds directly in the workspace `task-{id}.json` file (the daemon's source of truth).
2. The PS daemon's next 60-second poll sees the updated `next_run` and skips re-execution.
3. The 61-second buffer exceeds the daemon's poll interval, closing the race window.

### Startup Paths (5 paths, all covered)

| Path | When | What Happens |
|------|------|-------------|
| Cold start | App launch | `initializeScheduler()` → registers cron jobs + catch-up + `ensure-running` |
| Update/upgrade | After `updateProject` | `ensureSchedulerDaemon()` → restarts PS daemon only (no duplicate catch-up) |
| Panel open | User opens scheduler panel | Auto-start `useEffect` → checks status, calls `ensureRunning` if enabled but stopped |
| Watchdog | Every 5 minutes | Verifies PID is alive + is PowerShell; restarts if dead (circuit breaker: 3 failures → stop) |
| Manual | User clicks "Start" in panel | `scheduler:ensureRunning` IPC handler |

### Key File Locations

| File | Purpose |
|------|---------|
| `~/.agency-cowork/schedules.json` | Global schedule definitions + run history |
| `{workDir}/skills/task-scheduler/tasks/task-{id}.json` | Workspace task files (daemon's source of truth) |
| `{workDir}/skills/task-scheduler/scheduler.pid` | Daemon PID file |
| `~/.agency-cowork/task-logs/{scheduleId}_{taskId}.log` | Per-run output logs (5MB cap, 20 retained per schedule) |
| `{workDir}/agentconfig.json` → `scheduler.enabled` | Master enable/disable flag |

### Task Preservation During Upgrade

- `skill.json` declares `"userDataPaths": ["tasks", "logs"]` — preserved during skill merge
- `initializeScheduler()` calls `ensure-running` unconditionally (no task count gate)
- PS daemon sync recovers tasks from `schedules.json` even if `tasks/` is temporarily empty after upgrade

## Lessons Learned

### 5. Global Monitor Config Is Source of Truth (2026-03-15)

- The global config at `~/.agency-cowork/monitor-config.json` must remain the source of truth once a workspace entry exists. Letting legacy `agentconfig.json` override `monitor.enabled` can make Electron think the workspace is enabled while the Python service silently disables itself, surfacing as monitor start hanging on "Starting...". Fix: use `agentconfig.json` only to backfill a missing global workspace entry during migration, never to overwrite an existing one.
- Monitor autostart must emit the same full status payload as manual start. If `monitor:status` omits `running` or `bridgeConnected`, the renderer gets stuck in a yellow in-between state. Fix: every autostart/bridge-exit status update should send `connected`, `bridgeConnected`, and `running` together.
- Teams Monitor restart handling should include a short UI cooldown after Stop to prevent repeated Start clicks from racing bridge/service teardown.
- For shipping macOS installers, prefer the stock electron-builder DMG flow without a custom DMG background. Keep the manual DMG scripts as an emergency fallback only.

### 6. Packaged Monitor Must Validate Bridge Ownership (2026-03-15)

**Root cause:** The monitor bridge socket path is global (`/tmp/agency-pty-bridge.sock`). On packaged macOS, the bridge runs in-process inside `Agency Cowork.app`, so a stale latent app instance can still own that socket even after a new DMG-installed app launches.

**What made it hard to find:** The new app could start successfully and still connect to the old bridge, making the runtime look half-correct. Logs showed a healthy bridge connection, but the UI and monitor state could belong to the wrong process tree.

**Fix pattern:** Always validate the bridge discovery file PID before attaching the UI or Python monitor. If discovery points to a dead process, clean up the socket and discovery file. If it points to an older `Agency Cowork` or `bridge.js` owner, kill or reject that stale owner before connecting.

### 7. Monitor Restart Logic Must Use the Real Python PID File (2026-03-15)

**Root cause:** The Electron monitor restart path checked `skills/teams/scripts/monitor/monitor.pid`, but the Python service writes to `skills/teams/monitor/monitor.pid`.

**Fix pattern:** Treat `skills/teams/monitor/monitor.pid` as the canonical monitor PID file, with the old scripts path only as a compatibility fallback.

### 8. macOS DMG Release Helper Must Recover From `dmgbuild` Detach Failures (2026-03-16)

**Root cause:** On macOS 15.3, the stock Electron Builder DMG step can fail after successful app signing and app notarization with `Unable to detach device cleanly: hdiutil couldn't unmount diskX - Resource busy`.

**What made it hard to find:** The important work had already succeeded. The `.app` bundles were signed and notarized, but the final DMG step failed late, left temporary images or mounted volumes behind, and looked like a total release failure unless the build log was read carefully.

### 9. xterm.js v6 Overlay Scrollbar Requires Post-Replay Fit (2026-04-02)

**Root cause:** xterm.js v6 replaced the native viewport scrollbar with a `SmoothScrollableElement` overlay (VS Code-style). The overlay scrollbar thumb size is driven by `_sync()` calling `setScrollDimensions({height, scrollHeight})` where `height` = canvas height and `scrollHeight` = `cell.height × buffer.lines.length`. During task TUI mount, `XTerminal.jsx` replays buffered PTY data via `term.write(bigBatch)`, but `term.write()` is internally async in xterm.js — data is queued and processed in microtasks. The double-fit (`requestAnimationFrame` + `setTimeout(150ms)`) fires and triggers `_sync()` before the write is fully processed, so `buffer.lines.length` still reflects the pre-replay count. Result: `height ≈ scrollHeight` → scrollbar thumb = 100% (full track height). Mouse wheel scrolling still works because xterm handles `wheel` events internally independent of the scrollbar state.

**What made it hard to find:** The monitor terminal didn't exhibit the bug because its data arrives incrementally via live callbacks AFTER mount — each `term.write()` chunk triggers `_sync()` with correct buffer state. The task TUI only shows the bug when remounting with a large buffer replay (e.g., switching between tasks). The scrollbar track was visible and mouse wheel worked, making it look like a CSS styling issue rather than a dimension sync timing issue.

**Fix pattern:** Use `term.write(data, callback)` to re-fit AFTER xterm finishes processing the replayed buffer: `term.write(ptyBuffer.current.join(""), () => { fit.fit(); term.scrollToBottom(); })`. The callback fires only after all queued data is parsed and committed to the buffer, ensuring `_sync()` sees the correct `buffer.lines.length`.

**Applies to:** Any xterm.js v6 usage where a large batch of data is written at mount time (buffer replay, session restore, log replay). Always use the write callback for post-write scroll/fit synchronization.

### 10. Flex Column Containers Need minHeight: 0 for Proper Terminal Sizing (2026-04-02)

**Root cause:** The monitor view's two flex column containers (`overflow: hidden` wrapper and inner panel) were missing `minHeight: 0`. In CSS flexbox, a flex item's minimum size defaults to `min-content` — meaning the item won't shrink below the intrinsic size of its children. Without `minHeight: 0`, the XTerminal container couldn't shrink when the window was resized smaller or when sibling elements (banner, guidance panel, status bar) consumed space. The `FitAddon.fit()` call reads the container's computed height to calculate terminal rows, but the container reported its min-content height rather than its actual flex-allocated height.

**What made it hard to find:** The task panel already had `minHeight: 0` and worked correctly. The monitor panel was added later without this property, and the bug only manifested on window resize or when conditional siblings (update banner, guidance panel) appeared above the terminal. During initial render at the default window size, the layout often looked fine.

**Fix pattern:** Every flex column container in the ancestor chain of an xterm.js terminal MUST have `minHeight: 0`. This allows the flex algorithm to shrink the container below its content's intrinsic minimum, enabling `FitAddon.fit()` to read the correct available height. Apply this as a checklist item when adding new terminal containers.
**Fix pattern:** Keep the stock `electron-builder --mac dmg --<arch>` path as the first attempt, but automatically fall back to `ui/scripts/create-dmg-manual.sh` when the failure signature is the known detach bug. Reuse the already signed `.app`, keep the standard drag-to-Applications Finder layout, then sign and notarize the DMG container separately with `ui/scripts/notarize-dmg.sh`. Also keep x64 paths aligned with Electron Builder's real output layout: app in `release/mac`, DMG at `release/Agency Cowork-<version>.dmg`.

### 9. Electron Debug and Process Helpers Must Avoid Shell Interpolation (2026-03-17)

**Root cause:** Several Electron helpers were building shell commands with string interpolation (`taskkill /pid ${pid}`, `"${azCmd}" ...`, `${pythonCmd} -m ...`). Even when current callers pass expected values, this pattern leaves future call sites vulnerable and makes review harder. The dev PTY debug server also exposed write endpoints on localhost with no session token.

**What made it hard to find:** Most paths were "developer-only" or "local-only," so they looked harmless in isolation. But they still crossed trust boundaries: localhost is shared with every local process, and interpolated shells turn innocent plumbing code into policy exceptions.

**Fix pattern:** Use `execFileSync`/argument arrays for every user-influenced or variable executable invocation, validate PIDs before taskkill, and scope file reads to the configured workspace only. For local debug HTTP endpoints, require a per-process token even in dev mode so write access is explicit.

### 1. Terminal Focus State Controls Ink Input Acceptance (2026-03-13)

**Root cause:** Ink's `TextInput` silently ignores all input (including `\r`) when the
terminal reports focus-out (`ESC[O`). xterm.js sends `ESC[O` whenever the user clicks
outside the terminal component (e.g., on the send textbox).

**What made it hard to find:** The same `meta.proc.write("\r")` call, on the same
object, with the same byte (0x0D), produced different results depending on whether
a focus-out event had been sent. No errors, no warnings — input was silently dropped.
Debug logging showed writes succeeding at the PTY level, but the CLI never processed them.

**Fix pattern:** Always send `ESC[I` (focus-in) before injecting text or Enter into a
Copilot CLI PTY session. For follow-up prompts in Electron, use the IPC roundtrip
(`injectPtyInput`) to ensure writes go through the same handler context as keyboard input.

**Applies to:** Any PTY integration with Ink-based TUI apps where the hosting terminal
supports focus tracking (xterm.js, Windows Terminal, etc.).

### 2. Electron IPC Context Affects PTY Write Delivery (2026-03-13)

**Root cause:** On Windows with ConPTY, `meta.proc.write()` from `setTimeout` or HTTP
server callbacks in the Electron main process does not reliably deliver input to the
child process. Only writes from Electron IPC handler context (triggered by renderer
via `ipcMain.handle`) work consistently.

**Fix pattern:** Route delayed writes through the renderer via IPC roundtrip:
`main → pty:injectInput → renderer → task:ptyWrite IPC → main → meta.proc.write()`.

### 3. Initial Prompt Needs Hybrid Write Strategy (2026-03-13)

**Root cause:** On a fresh PTY spawn, the XTerminal React component may not be mounted
yet when `writePromptOnce` fires. The IPC roundtrip (`pty:injectInput`) has no listener
in the renderer — the text is lost.

**Fix pattern:** Use direct `meta.proc.write()` for the initial text (synchronous, before
xterm.js mounts and before any focus-out events). Use IPC roundtrip only for the delayed
Enter (by the time the 500ms delay fires, XTerminal is mounted and may have sent focus-out).

### 4. Chatsvc Wrong-Region 200 Silently Drops Messages (2026-03-15)

**Root cause:** The Teams chatsvc API returns HTTP **200** (not 404) when a message is
POSTed to the wrong region. The 200 body contains a `"messages"` array (conversation
echo) instead of a delivery confirmation. The correct region returns **201** with
`{"OriginalArrivalTime": ...}`. The code treated all 200/201/202 as success.

**What made it hard to find:** Logs showed "Reply sent" with HTTP 200 — every indicator
said success. Only comparing 200 vs 201 response bodies revealed the difference. The
existing region auto-discovery only triggered on 404, never on 200.

**Fix pattern:** Only treat HTTP 201/202 as confirmed delivery. On 200, parse the
response body: if it contains a `"messages"` array, it's a wrong-region echo — extract
the correct region from `conversationLink` in the body, auto-correct via
`set_chatsvc_region()`, persist to config, and retry the POST.

**Applies to:** Any chatsvc API integration. Region slug is tenant-specific (e.g.,
`amer`, `noam-pilot2`, `emea`) and NOT inferable from user location alone.

### 5. Reply Prefix Must Be Explicitly Propagated (2026-03-15)

**Root cause:** `set_reply_prefix()` was imported in `service.py` but never called. The
module-level `_reply_prefix` defaulted to `"Agency Cowork: "` and was never updated with
the per-workspace config value. The config value was only used for self-loop detection.

**Fix pattern:** When module-level state is set via setter functions (not constructor
args), always verify the setter is actually called during initialization. A comment
saying "Apply X" is not the same as actually calling the function.

### 6. Electron PATH Isolation Breaks Fresh Installs (2026-03-15)

**Root cause:** Electron inherits `PATH` from its launch-time environment. Tools
installed during setup (Azure CLI, Agency CLI) update the Windows registry PATH but
not the running Electron process. Subsequent `execSync("az.cmd ...")` calls fail with
"not recognized".

**Fix pattern:** Before calling any CLI tool from Electron that may have been
freshly installed, refresh `process.env.PATH` from the Windows registry
(`HKLM\...\Environment` + `HKCU\Environment`). Also check well-known install paths
as fallback (e.g., `Program Files\Microsoft SDKs\Azure\CLI2\wbin\`).

### 7. AzureAuth Incomplete Extraction Causes MCP Failures (2026-03-15)

**Root cause:** AzureAuth 0.9.5 zip extraction was incomplete — `MSALWrapper.dll`
missing from the version directory. This caused a .NET CLR exception (`0xe0434352`)
whenever `agency mcp calendar|mail|teams` spawned azureauth, silently breaking all
local STDIO MCP servers.

**Fix pattern:** After any tool installation that involves zip extraction, verify
critical files exist (not just the main executable). Run a smoke test
(`azureauth --version`) to catch load-time failures. Auto-repair by re-extracting
from the retained source zip if available.

### 8. PTY Enter/Text Lost — Missing Focus-In Before Text Paste (2026-03-15)

**Root cause:** `writePromptOnce()` (initial prompt path) did not send `ESC[I`
(focus-in) before injecting text — only before the delayed Enter. By the time
`writePromptOnce` fires (2s after ready-detect), XTerminal has mounted and
xterm.js has sent `ESC[O` (focus-out) because the user's cursor is in the chat
textbox. Ink's `TextInput` ignores ALL input (paste + Enter) when unfocused,
so both the text and Enter are silently dropped.

**What made it hard to find:** The textbox send path (`writeToPty`) works reliably
because it sends `ESC[I` **before the text paste** (line 1: focus-in → Ctrl+U →
paste → delay → focus-in → Enter). The initial prompt path was missing step 1.
The assumption "no focus-out has occurred yet" was correct at PTY spawn time but
wrong by the time `writePromptOnce` fires 7–9s later.

**Fix pattern:** Always send `ESC[I` before text, not just before Enter. Both
`writePromptOnce` and `writeToPty` now follow the same pattern:
`ESC[I → Ctrl+U → bracketed paste → delay → ESC[I → Enter`.

**Applies to:** Any PTY integration with Ink-based TUI apps. Focus-in must
precede EVERY write sequence, not just Enter — Ink drops all input when unfocused.

### 9. PTY Slash Commands Must Use Bracketed Paste + Delayed Enter (2026-03-15)

**Root cause:** The PTY bridge sent `/yolo` as a single write (`"/yolo\r"` — text
and Enter concatenated). Ink's TUI needs time to process the paste before Enter
arrives. When text+Enter are in one write, the `\r` fires before the text is
committed to the input buffer, resulting in either an empty Enter or the `/yolo`
text appearing but never submitting.

**What made it hard to find:** Regular prompts (from `writeToPty` and the bridge's
`writePrompt`) used the correct `ESC[I → Ctrl+U → bracketed paste → delay →
ESC[I → Enter` pattern. Only the `/yolo` command sends (initial and retroactive)
used the shortcut single-write pattern.

**Fix pattern:** ALL text-then-Enter writes to a Copilot CLI PTY must follow the
full injection pattern — no exceptions for short commands like `/yolo`. Even a
5-character command needs bracketed paste + 500ms delay before Enter.

**Applies to:** Any PTY command injection. Never combine text and `\r` in one
`proc.write()` call — always separate with a delay.

### 10. Auto-Accept "Enable Autopilot Mode" Permissions Dialog (2026-03-15)

**Root cause:** When `/yolo` or a mode switch activates autopilot, Copilot CLI
shows an "Enable autopilot mode" dialog with three options (Enable all permissions,
Continue with limited, Cancel). Option 1 is pre-selected with `›`. The PTY bridge
already handled this dialog, but the Electron main process did not — so when
`/yolo` was sent from the UI (not the monitor), the dialog appeared and blocked
execution until the user manually pressed Enter.

**Fix pattern:** Detect `Enable autopilot mode` or `enable.*all permissions` in
PTY output and auto-send `ESC[I` + `\r` after 300ms. The short delay lets the
TUI render the dialog fully. Guard with a `sent` flag to avoid duplicate sends.

**Applies to:** Any interactive CLI dialog that appears in the PTY stream with a
pre-selected default option. Add a regex + auto-answer pattern for each known
dialog type.

### 11. `--exclude-standard` Hides Gitignored Runtime State From Backup (2026-03-15)

**Root cause:** `update.ps1` Step 3.7 used `git ls-files --others --directory
--exclude-standard` to find untracked runtime directories for backup. The
`--exclude-standard` flag respects `.gitignore`, which explicitly excludes
`skills/qmd-memory/cache/` (embedding cache), `skills/task-scheduler/logs/`,
and `skills/teams/logs/`. These are the exact directories the backup should
protect — but the flag made them invisible to the scan.

**What made it hard to find:** The command output looked correct (it listed *some*
untracked dirs). The missing dirs only appeared when running without the flag.
Bisecting the `.gitignore` patterns confirmed `cache/` was excluded at line 33.

**Fix pattern:** Remove `--exclude-standard` from runtime backup scans. Instead,
filter out known non-essential patterns (e.g., `__pycache__`, `node_modules`)
in application code. Runtime state backup must see ALL untracked content, not
just non-gitignored content.

**Applies to:** Any git-based backup or migration tool. If the goal is to find
runtime state, `--exclude-standard` is the wrong flag — it's designed for
*tracking* decisions, not *backup* decisions.

### 12. `--allow-all-tools` Only Works With `-p` (Non-Interactive) Mode (2026-03-15)

**Root cause:** The Copilot CLI `--allow-all-tools` flag is silently ignored in
interactive PTY mode. It only takes effect when combined with `-p` (piped/prompt
mode). In PTY mode, switching to autopilot ALWAYS shows the "Enable autopilot mode"
permissions dialog regardless of CLI flags.

**What made it hard to find:** The bridge spawned sessions with `--allow-all-tools`
and assumed the permissions dialog would be suppressed. Logs showed the flag was
passed. The dialog appeared anyway, and the proactive Enter handler was gated on
`!yoloMode` (assuming `--allow-all` prevented the dialog when yolo was off).

**Fix pattern:** In PTY interactive mode, NEVER rely on `--allow-all-tools` to
suppress the permissions dialog. Always handle it via PTY input injection:
option 1 (Enter) for full permissions, or option 2 (Down+Enter) for limited.
Gate the handler on `autoApprovePermissions` setting, not on CLI flags.

**Applies to:** Any PTY automation of Copilot CLI. CLI flags for tool permissions
only work in non-interactive (`-p`) mode.

### 13. Bridge Settings Race — Env Vars vs Pipe Commands (2026-03-15)

**Root cause:** The PTY bridge initialized autonomy flags (autopilot, auto-approve,
yolo) to `false` at startup, then waited for pipe commands from Electron to set
the correct values. But the Python service could spawn a session before those pipe
commands arrived, using the stale default `false` values.

**What made it hard to find:** In normal startup, the pipe commands arrive within
~100ms. But under load or during config save/restart cycles, the race window widens.
The flags appeared correct in bridge debug output because the query happened after
the pipe commands arrived — but the session had already been created with stale values.

**Fix pattern:** Pass critical startup configuration as environment variables
(`BRIDGE_YOLO`, `BRIDGE_AUTOPILOT`, `BRIDGE_AUTO_APPROVE`) at spawn time, not as
post-spawn pipe commands. The bridge reads `process.env` during initialization,
before any sessions can be created. Pipe commands remain for runtime changes.

**Applies to:** Any parent-child process pattern where the child needs config before
handling requests. Env vars are atomic at spawn; IPC commands have a race window.

### 14. Windows Orphan Process Cleanup — WINDOWTITLE vs Command-Line Match (2026-03-15)

**Root cause:** `killOrphanedMonitorProcesses()` on Windows used
`taskkill /FI "WINDOWTITLE eq monitor*"` to find stale Python monitor processes.
Headless Python processes spawned by Electron have no window title — the filter
never matched, leaving old processes alive across app restarts.

**What made it hard to find:** The orphan killed no processes, but raised no errors
either (`taskkill` exits cleanly when no matches found). The duplicate bot replies
(one from old process, one from new) were the only symptom, and could be mistaken
for a message handler bug.

**Fix pattern:** On Windows, use PowerShell `Get-CimInstance` with command-line filtering:
`Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*scripts.monitor.service*' }`.
Avoid `wmic.exe` which is deprecated and removed from Windows 11 22H2+ by default.
The macOS/Linux path already used `pgrep -af` (command-line match) correctly.

**Applies to:** Any Windows process cleanup. Never use `WINDOWTITLE` for headless
or child processes. Prefer `Get-CimInstance` over deprecated `wmic.exe`.

### 15. Packaged Teams Monitor PTY — Use Electron Main Runtime, Not Electron-as-Node Child (2026-03-15)

**Root cause:** The regular chat PTY worked because it ran inside Electron main,
but the Teams monitor PTY bridge ran as a separate child process using Electron in
`ELECTRON_RUN_AS_NODE=1` mode. In the packaged macOS app, `node-pty` could load but
could not reliably spawn children there, producing `posix_spawnp failed` only for
the monitor path.

**What made it hard to find:** Dev mode and the normal "new task" PTY both worked,
so the bug looked like a Teams-only or path-resolution issue. The packaged bridge
also appeared partially healthy: the pipe server started, clients connected, and the
failure only appeared when the first PTY session spawn happened.

**Fix pattern:** In packaged macOS builds, run the monitor bridge in-process inside
Electron main and share the already-working `node-pty` instance with the bridge.
Then teach the prompt queue to adopt pre-warmed ready sessions so the first real
Teams message is not delayed behind startup automation.

**Applies to:** Any packaged Electron feature using `node-pty`. If PTY works in main
process but fails in a helper child, prefer reusing the main-process runtime instead
of spawning Electron in hidden Node mode.

### 16. Manual DMG Release Path — Notarize the App and the DMG Separately (2026-03-15)

**Root cause:** `electron-builder` successfully signed and notarized the `.app`, but
its DMG builder failed at detach time with `hdiutil: couldn't unmount ... Resource busy`.
The manual DMG fallback created a valid container, but that DMG itself was not notarized,
so `stapler` on the DMG failed with `Insufficient Context` even though the app inside was
already notarized.

**What made it hard to find:** The notarization log said success, which was true for the
app bundle, but the final customer-facing artifact was the DMG. That made it easy to think
the remaining problem was signing, when it was actually a container-notarization step plus
an unreliable DMG builder.

**Fix pattern:** Treat the app and DMG as separate notarization targets. If `electron-builder`
DMG creation flakes, staple the notarized app, create the DMG manually, then submit the DMG
to `notarytool`, staple it, and assess it separately. Keep the manual DMG window styling plain
so Finder falls back to the system appearance.

**Applies to:** Any macOS release flow that uses a manual DMG fallback. Notarizing the app
bundle is not sufficient when customers download a DMG container.

### 17. macOS Close Behavior — Quit by Default, Stay Alive Only for Real Background Work (2026-03-15)

**Root cause:** The app previously hid to the tray or menu bar on every window close.
That matched a power-user background-service model, but it was hostile to the normal macOS
install and upgrade flow because users thought the app was closed while the process was still
running, which then blocked drag-replace updates in `/Applications`.

**What made it hard to find:** The behavior was internally consistent and the tray menu already
exposed `Quit`, so it did not look broken during development. The problem only becomes obvious
on the customer path: install from DMG, close the app, then try to replace it with a newer build.

**Fix pattern:** On macOS, close the app completely by default. Only keep it alive in the menu bar
when there is a live user-visible background service, currently the Teams monitor bridge. Passive cron
schedules should not keep the app resident by themselves because that makes install and upgrade behavior
surprising. If the monitor keeps the process alive, show a one-time explanation so the user knows the
app is still running and must be fully quit before reinstalling.

**Applies to:** Any future macOS background feature. Do not hide-on-close by default just because a
tray icon exists or a schedule is configured. Gate background persistence on explicit live work and
explain the behavior once.

### 18. PTY Ready Detection — Resumed Sessions May Skip `Environment loaded:` (2026-03-15)

**Root cause:** The monitor PTY bridge initially treated `Environment loaded:` as the primary ready signal.
That works for full cold starts, but resumed Copilot sessions can land directly on the interactive prompt and
footer without replaying the bootstrap banner. In that case the session is usable, but the bridge never flips
it to `ready`, so the first queued Teams prompt waits 120 seconds and everything behind it only gets queue receipts.

**What made it hard to find:** The installed app still streamed live PTY output, which made it look like the
pipeline was working. The actual failure was narrower: prompt queue startup waited on a bridge `ready` event that
never fired even though the terminal had already reached the interactive footer.

**Fix pattern:** Accept both bootstrap and prompt/footer readiness. Keep `Environment loaded:` as the strong signal,
but after a short grace period also treat the real CLI prompt and footer text, such as `Type @`, the prompt glyph,
or `shift+tab switch mode`, as proof that a resumed session is ready for input.

**Applies to:** Any persistent PTY or TUI automation that resumes existing sessions. Do not assume the same startup
banner appears on every launch path.

### 19. Monitor IPC Must Never Send Directly To A Possibly-Destroyed Renderer (2026-03-15)

**Root cause:** The Teams monitor bridge event path still used direct `mainWindow?.webContents.send(...)` calls for
`monitor:ptyData`, `monitor:output`, and `monitor:turnEnd`. Optional chaining only protects `mainWindow`; it does not
prevent `webContents.send()` from throwing once the window or its webContents has already been destroyed.

**What made it hard to find:** The bridge can connect and start streaming during app startup or shutdown races, so the
error surfaces intermittently as `TypeError: Object has been destroyed` even though monitor startup, signing, and
notarization all look healthy.

**Fix pattern:** Route all monitor renderer IPC through the shared `sendToRenderer()` guard so both `mainWindow` and
`webContents` are checked before sending. Add a regression guard that fails if raw `monitor:*` sends are reintroduced
in `ui/electron/main.js`.

**Applies to:** Any Electron async callback that can outlive the renderer, especially socket, PTY, scheduler, or child
process event handlers.

### 20. update.ps1 Must Self-Update Before Running Migrations (2026-03-17)

**Root cause:** New migration features (OneDrive migration, service stop/restart, zombie cleanup) only exist in the new `update.ps1`, but the running script is the old version. Users upgrading from 0.9.8 to 0.9.9 ran the old script, which lacked the new migration steps.

**What made it hard to find:** The upgrade appeared to complete successfully -- old script steps all passed. The missing migrations only became apparent when features relying on them (OneDrive sync, service restarts) failed silently.

**Fix pattern:** Step 0 of `update.ps1` fetches `upstream/main:scripts/update.ps1`, compares SHA256 hashes. If different, writes the new script to a temp file and re-executes via `pwsh` with the original parameters, using `AGENCY_UPDATE_SELF_UPDATED` env var as a re-entry guard to prevent infinite recursion.

### 21. NTFS Junctions Break Relative Git Submodule Pointers (2026-03-17)

**Root cause:** After creating an NTFS junction `memory/ -> OneDrive/.../memory/`, a git submodule's `.git` pointer file contains a relative path (`gitdir: ../.git/modules/memory`). The junction target resolves to the OneDrive real path, so the relative `..` lands in the wrong directory.

**What made it hard to find:** `git status` in the repo root worked fine (git resolves the junction). But operations inside `memory/` (where the junction points) failed because the `.git` file's relative path resolved against the OneDrive real path, not the repo root.

**Fix pattern:** After creating a junction/symlink for a git submodule, detect relative `gitdir:` in the `.git` pointer file, resolve it to an absolute path against the original repo location, and rewrite the file.

### 22. PowerShell Copy-Item Treats Brackets as Glob Wildcards (2026-03-17)

**Root cause:** `Copy-Item` interprets `[` and `]` in file paths as wildcard character class delimiters. Files like `[EXT---MS]-spec.md` are silently skipped because the bracket pattern matches nothing.

**Fix pattern:** Always use `-LiteralPath` instead of `-Path` for file operations on user content that may contain brackets, parentheses, or other glob metacharacters. This applies to `Copy-Item`, `Move-Item`, `Remove-Item`, `Get-Content`, and `Test-Path`.

### 23. execFileSync With shell:true and Spaces in Path (2026-03-17)

**Root cause:** `execFileSync(azCmd, args, { shell: true })` where `azCmd` is an absolute path like `C:\Program Files (x86)\...\az.cmd` fails because `cmd.exe /s /c` strips the outer quotes, splitting `C:\Program` and `Files` into separate tokens.

**What made it hard to find:** The code had `shell: true` specifically to handle `.cmd` files (which need shell interpretation), and the PATH included the directory. But `azCmd` was set to the full absolute path with spaces, bypassing PATH resolution entirely.

**Fix pattern:** When using `shell: true` with `execFileSync`, never pass an absolute path containing spaces as the command. Instead, add the directory to `process.env.PATH` and use just the filename (`az.cmd`). PATH resolution handles the rest without quoting issues. This also applies to any `.cmd` or `.bat` file in `Program Files`.

### 24. Tray Quit Does Not Trigger Renderer State Save (2026-03-17)

**Root cause:** Task persistence only triggered on `isDone` (process exited). When the user quit from the system tray, `app.quit()` killed all processes without giving the renderer time to save the active conversation. The current conversation was lost from recents.

**What made it hard to find:** Normal task completion saved correctly. The bug only appeared when quitting mid-conversation from the tray -- a common user workflow but not covered by the completion-only save trigger.

**Fix pattern:** Two-pronged: (1) Save task after every turn completion (`isWaiting`), not just `isDone` -- conversations are incrementally persisted as they progress. (2) In `before-quit`, use `e.preventDefault()` to delay quit by 500ms, send `app:before-quit` signal to renderer, let it do one final save, then re-trigger `app.quit()` with a `pendingQuitSave` guard to prevent infinite recursion.

**Applies to:** Any Electron app with unsaved renderer state. Never rely on process exit to trigger saves -- save incrementally and add a before-quit grace period.

### 25. Monitor Config Migration Must Preserve User Settings (2026-03-17)

**Root cause:** `setup.ps1` migration (legacy -> global monitor config) had three bugs: (1) missing top-level `enabled` field, (2) pulling keyword from legacy config (which had stale `@maia-agent`) instead of `agentconfig.json` (which had the user's actual keyword), (3) unconditionally overwriting existing global workspace entries on re-run.

**What made it hard to find:** The migration ran once and appeared successful. The config revert only surfaced on restart, when the Python service read the global config with the wrong keyword and `enabled` state.

**Fix pattern:** Migration must: (a) always include top-level `enabled` field, (b) prefer `agentconfig.json` keyword over legacy config, (c) skip workspace migration if a global entry already exists and is enabled. Also validate `working_directory` on save -- reject or warn if the path doesn't exist on disk.

### 26. OneDrive Migration: Backup-Validate-Delete Pattern (2026-03-17)

**Root cause:** `Invoke-OneDriveMigration` in `update.ps1` deleted the local `memory/` directory with `Remove-Item -Recurse -Force` before verifying the NTFS junction worked. When junction creation failed (OneDrive target was empty because the copy tool had silently failed), 658 files were lost. The script also used `$LASTEXITCODE` from a stale prior command to check success of `robocopy`, which was not on PATH in the bundled environment.

**What made it hard to find:** The copy appeared to succeed because the error was caught silently and `$LASTEXITCODE` was 0 from a prior command, not from `robocopy`. The `Remove-Item` on the next line was unconditional -- no validation that the destination actually contained the files.

**Fix pattern:** All directory migrations that involve delete-and-replace-with-junction MUST follow this sequence: (1) Pre-flight checks: verify source is non-empty, target is writable, no stale junctions exist. (2) Copy files to destination. (3) Validate file counts: `dest >= source`. Abort if mismatch. (4) Create full timestamped backup (`.onedrive-migration-backup-*`). (5) Delete source. (6) Create junction. (7) Verify junction: list files through it and check count > 0. (8) If any step 5-7 fails, restore from backup. (9) Clean up backup only after everything succeeds. For directory copy/delete/junction operations, avoid `robocopy`, `xcopy`, or `cmd /c` and use only PowerShell-native `Copy-Item`, `Move-Item`, `Remove-Item` with `-LiteralPath` (external tools have different error semantics that defeat validation logic). Other scripts may legitimately invoke `git`, `python`, `npm`, etc.

### 27. Installer Has Three Separate File Lists That Must Stay in Sync (2026-03-17)

**Root cause:** When `docs/` was added to the installer bundle, it was added to `extraResources` in `package.json` (production builds) and `optionalItems` in the `setup:extractFiles` handler (dev-mode fresh installs), but missed in `UPDATE_ITEMS` in the `setup:updateProject` handler (upgrade path). Users upgrading from a previous version never received the `docs/` directory, causing the agent to fail with "Path does not exist" when trying to read `docs/POST_SETUP_GUIDE.md`.

**What made it hard to find:** Fresh installs worked fine (the production path copies everything in `bundled-project/`). The bug only appeared on upgrades, which use an explicit allowlist (`UPDATE_ITEMS`) rather than copying everything. Testing the installer on a clean machine would not reproduce it.

**Fix pattern:** The installer has three file lists that MUST stay in sync when adding new bundled directories or files: (1) `extraResources` in `ui/package.json` -- controls what electron-builder bundles into `resources/bundled-project/`. (2) `optionalItems` in the `setup:extractFiles` IPC handler -- controls what gets copied during dev-mode fresh installs. (3) `UPDATE_ITEMS` in the `setup:updateProject` IPC handler -- controls what gets copied during upgrades. Missing any one of these causes a silent gap for that code path. Consider refactoring to a single shared constant.

### 28. "Use Existing Project" Stamps Version Without Updating Files (2026-03-18)

**Root cause:** The OOBE "Use Existing Project" flow (`handleUseExistingProject`) set `isExistingProject=true` and jumped to step 3, completely skipping the extract step. The extract step was explicitly hidden: `if (isExistingProject && s.id === "extract") return null`. Meanwhile, `setup:complete` wrote a new version number to `agencycowork.json` — so the folder was stamped as current but contained stale scripts and skills from the original install date.

**What made it hard to find:** The folder appeared up-to-date because `agencycowork.json` showed the latest version. The staleness was only visible when comparing file modification dates or running updated features that were absent. Working folders could be weeks behind while reporting the current version.

**Fix pattern:** Before allowing "Use Existing Project", always compare the app's bundled version (`package.json`) against the installed version (`agencycowork.json`). If they differ, present an explicit update dialog with backup. Reuse the existing `setup:updateProject` handler (which handles backup, user-data preservation, and file sync) rather than duplicating logic. Never stamp a version without actually delivering the files for that version.

### 29. Windows OOBE Reinstalls Optional Dependencies Despite Existing Install (2026-03-18)

**Root cause:** The macOS OOBE passed `--install-deps none` to skip Phase 7 optional dependencies, but the Windows OOBE was missing this flag. Without it, `$depsToInstall` defaulted to empty and `Read-YesNo` returned `$true` in headless mode, so Phase 7 ran unconditionally. The detection checks (`Get-Command qmd`, `pip show markitdown`) failed in Electron's spawned PowerShell because `process.env.PATH` differs from the user's interactive shell — QMD's `C:\ProgramData\global-npm` and Python's `Scripts` directory were not on the spawned process PATH.

**What made it hard to find:** The detection checks work correctly in a normal terminal. The failure only occurs inside Electron-spawned processes where the PATH is minimal. The tools were already installed and functional, but the detection said they weren't.

**Fix pattern:** (1) Pass `-InstallDeps none` on Windows to match macOS (Phase 7 deps are not needed during OOBE). (2) Harden detection with multi-strategy fallbacks: PATH check → npm global prefix + filesystem locations → `pip show 2>&1 | Out-String` → `python -c "import ..."`. Never rely solely on PATH-based detection in Electron-spawned contexts.

### 30. Skills Panel Ordering Is Non-Deterministic (2026-03-18)

**Root cause:** The skills panel in `App.jsx` rendered skills in the order returned by the skills loader, which depended on filesystem enumeration order — non-deterministic across platforms and runs.

**Fix pattern:** Sort skill lists alphabetically before rendering: `[...skills].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))`. Apply to any user-facing list where a stable order improves usability.

### 31. Dual Execution Engines Require Mutual Exclusion at the Data Layer (2026-03-20)

**Root cause:** Electron node-cron and the PowerShell daemon both independently evaluate `next_run` to decide whether to fire a task. Neither engine locks or signals the other, so both fire within seconds of each other.

**What made it hard to find:** Each engine works correctly in isolation. The bug only manifests when both are running simultaneously (normal production state). Test environments often run only one engine.

**Fix pattern:** Write to the slower engine's source-of-truth (`tasks/*.json`) at trigger time, not after execution completes. The 61-second `next_run` advance exceeds the daemon's 60-second poll interval. This is a poor-man's distributed lock — sufficient because both engines run on the same machine with shared filesystem.

### 32. Watchdog Restart Loops Need Circuit Breakers (2026-03-20)

**Root cause:** The watchdog unconditionally called `runTaskManager("ensure-running")` every 5 minutes with no failure memory. If the daemon crashes on startup (bad config, missing dep), the watchdog restarts it forever.

**Fix pattern:** Track consecutive failure count + first failure timestamp. Stop after N failures within a time window. Reset on success or window expiry. Log an error-level message when the breaker trips — silence is worse than noise for operational issues.

### 33. In-Process Buffering of Child Process Output Causes OOM (2026-03-20)

**Root cause:** `executeScheduledTask()` accumulated the full stdout+stderr of the child process in a `fullOutput` string variable, then wrote it to disk on process close. A long-running task producing megabytes of output would grow this buffer without bound.

**Fix pattern:** Stream output directly to disk via `fs.createWriteStream()` opened before spawning the child. Cap the write stream at a size limit (5MB) with a truncation marker. Keep only a small in-memory summary buffer (500 chars) for the UI. Never buffer unbounded child process output in the Electron main process.

### 34. IPC Payload Size Must Be Bounded at Read Time (2026-03-20)

**Root cause:** `scheduler:getRunLog` used `fs.readFileSync()` to load the entire log file, then sent it over IPC to the renderer. If log files are unbounded (see lesson 33), this doubles the memory hit (file buffer + IPC serialization).

**Fix pattern:** Check `fs.statSync().size` before reading. For oversized files, read head + tail portions and return a truncation indicator. Set a reasonable IPC payload limit (2MB) separate from the write-side limit (5MB).

### 35. PID Files Are Unreliable for Process Identity on Windows (2026-03-20)

**Root cause:** `process.kill(pid, 0)` checks if *any* process with that PID is alive, not specifically the scheduler daemon. Windows recycles PIDs aggressively — a stale PID file can match an unrelated process, causing the watchdog to skip restarting a dead daemon.

**Fix pattern:** After confirming the PID is alive, verify process identity via `Get-Process -Id <pid>` and check the process name is `powershell` or `pwsh`. This adds ~50ms per watchdog cycle but prevents false-positives that leave the daemon dead.

### 36. Theme Tokens Must Exist Before Use in JSX (2026-03-20)

**Root cause:** `FeedbackModal` used `T.bgPrimary` as a background color, but the theme object defined `bgApp`, `bgSidebar`, `bgSurface`, `bgSurfaceHover`, `bgElevated`, `bgOverlay` — no `bgPrimary`. The undefined value resolved to a transparent background, making the modal invisible against the dark overlay.

**What made it hard to find:** No runtime error or console warning. React silently renders `background: undefined` as no background. The modal's text was visible but its container was transparent, which looked like a CSS layering bug rather than a missing token.

**Fix pattern:** When adding UI components, verify theme tokens against the actual theme object definition. A grep for the token name across the theme definition file is sufficient. Use `bgElevated` for modal/popover surfaces, `bgSurface` for inline cards, `bgOverlay` for backdrop dimming.

### 37. Inferring Task Liveness From Absence of Running Is Unsound (2026-03-20)

**Root cause:** `loadSavedTask()` inferred `isDone = !isRunning && !isBooting` to decide whether to show a "Session ended" dialog. Tasks waiting for user input have `{isRunning: false, isWaiting: true, isDone: false}` — alive but idle. The inference marked them as dead, triggering a false "Session ended" dialog on every task switch.

**What made it hard to find:** The dialog only appeared when switching between tasks, not during normal use. The state model has four boolean flags (`isRunning`, `isBooting`, `isWaiting`, `isDone`) and only `isDone` reliably indicates termination. Negative inference from any single flag misses valid intermediate states.

**Fix pattern:** Only check `liveState?.isDone === true` to determine task completion. Never infer death from `!isRunning` — the process may be in a waiting, paused, or transitional state. Task state models with multiple boolean flags require checking the explicit terminal flag.

### 38. PTY Slash Commands Must Never Combine Text and Enter in One Write (2026-03-20)

**Root cause:** The `/yolo` command was injected as `meta.proc.write("/yolo\r")` — text and Enter concatenated in a single write with zero delay. Ink's `TextInput` needs time to process pasted text before Enter arrives. When combined, the `\r` fires before the text is committed to the input buffer, causing `/yolo` to either not submit or submit an empty command. The prompt (sent 6s later via `writePromptOnce` with the full bracketed-paste + 500ms-delay pattern) worked fine.

**What made it hard to find:** The regression appeared after merging several PRs, but none of them touched the yolo injection code. The most likely cause was a timing shift — other changes (monitor watchdog, MCP status updates) added work at startup that pushed the READY_RE match earlier relative to TextInput readiness. The `/yolo` write had always been fragile; the timing change just exposed it.

**Fix pattern:** ALL text injection into Copilot CLI PTY must follow the full pattern: `ESC[I` (focus-in) → bracketed paste (`ESC[200~` text `ESC[201~`) → 500ms delay → `ESC[I` → `\r`. No exceptions for "short" commands. This applies to both new-task and session-resume yolo injection paths.

**Applies to:** This is a restatement of Lesson #9 with a concrete regression example. The temptation to use "quick" single-write injection for short commands will recur — resist it every time.

### 39. Windows Mic Button Must Use shell.openPath for Foreground Activation (2026-03-20)

**Root cause:** On Windows, clicking the mic button when Handy was already running (e.g., in system tray) did nothing. The `handy:launch` handler detected `isHandyRunning()` and returned `{ ok: true, alreadyRunning: true }` without bringing the window to foreground. Only macOS had foreground logic (`open -a Handy`).

**Fix pattern:** On Windows, use Electron's `shell.openPath(exePath)` which both launches Handy if not running AND activates/foregrounds it if already running. This is more reliable than `spawn()` + manual foreground logic. macOS/Linux paths retain their existing behavior.

### 40. update.ps1 Must Flag Service Restart on PID File Existence, Not Process State (2026-03-20)

**Root cause:** `update.ps1` set `$schedulerWasRunning = $true` only inside a `if ($proc)` block — if the PID file existed but the process had died (stale PID), the flag stayed `$false` and the post-update restart was skipped. The service silently remained dead after upgrades.

**What made it hard to find:** The code path looked correct — "check if running, remember state, restart." The subtle bug was that `$proc` being `$null` (dead process) caused the flag to never set, even though the PID file proved the service was *configured* to run.

**Fix pattern:** Set restart flags based on PID file existence (service was configured to run), not on current process state. Clean up stale PID files explicitly. Log a warning when a stale PID is found. Apply to both scheduler and monitor services — the same pattern existed in both.

### 41. Scheduler Singleton Must Be System-Wide, Not Per-Directory (2026-03-20)

**Root cause:** Five concurrent `scheduler-service.ps1` instances ran simultaneously from different repo clones (`maia-agent`, `agency-cowork`, `agency-cowork-1`). The PID-file singleton check only prevented duplicates within the same directory — each clone had its own `scheduler.pid` path and couldn't see the others. All 5 polled the same `tasks/` directory every 60 seconds, racing to dispatch the same tasks.

**What made it hard to find:** Each individual scheduler appeared healthy — PID file valid, logs clean. The race manifested as corrupted task JSON: multiple `run-task.ps1` instances simultaneously read→modify→wrote the same file, clobbering each other's changes. `run_count` stuck at 0, `next_run` never advanced, and the 3-error auto-pause threshold was never reached, causing an infinite re-dispatch loop (30+ dispatches in one day).

**Fix pattern:** (1) System-wide singleton via `Get-CimInstance Win32_Process` scanning for ANY `scheduler-service.ps1` process regardless of working directory, with PID-file as secondary check. (2) Task-level dispatch lock using atomic `FileMode.CreateNew` — if the lock file exists, another scheduler already dispatched the task. Stale locks (>30 min) are auto-cleaned. (3) Exclusive file locking in `run-task.ps1` JSON updates using `FileStream` with `FileShare.None` + retry with exponential backoff. (4) `Join-Path` with 3 arguments (PS7-only) fixed to nested calls for PS 5.1 compatibility.

### 42. Prompt Injection Needs Confirmation, Not Just Ready-Detection (2026-03-20)

**Root cause:** The CLI TUI renders the prompt (`❯`, "Type @", "Describe a task") and splash box during MCP loading — BEFORE the CLI is truly ready to process input. On warm starts, Ink's input handler is wired early enough that injected text + Enter succeeds. On cold/first starts (MCP servers downloading, first-time model loading), Enter is swallowed because the input handler isn't ready yet. The prompt injection silently fails with no indication.

**What made it hard to find:** Warm-start testing (most developer sessions) always succeeded. The bug only manifested on cold starts or after clearing MCP caches. The PTY debug ring buffer showed text appearing in the CLI's input field (paste works), but "Thinking" never followed — Enter was accepted by the terminal but not processed by Ink's `useInput` hook. Without confirmation detection, there was no way to distinguish success from silent failure.

**Fix pattern:** Confirmation-based injection with retry:
1. **Early detection** (`EARLY_RE`): triggers first injection attempt on TUI splash box (~2s delay). Also clears the "booting" spinner in the UI.
2. **Confirmation signals**: Watch PTY output for `Thinking (Esc to cancel)` (prompt accepted) and `All permissions are now enabled` (/yolo accepted).
3. **Retry on `Environment loaded:`**: If the prompt was injected but not confirmed, the `Environment loaded:` signal (past tense, CLI fully ready) triggers a retry — clear input (Ctrl+U), re-paste, re-send Enter. Max 3 attempts.
4. **Safety fallback**: 45s timeout for edge cases (hung MCP server, old CLI).

Key insight: "Loading environment:" (present tense) means bootstrap is in progress. "Environment loaded:" (past tense with 'd') is the only reliable signal that the CLI is truly ready. The early injection is an optimization for warm starts; the retry-on-loaded path guarantees reliability on cold starts.

### 43. StreamWriter with UTF8 Encoding Writes BOM — Use UTF8Encoding($false) (2026-03-20)

**Root cause:** `[System.IO.StreamWriter]::new($stream, [System.Text.Encoding]::UTF8)` writes a 3-byte UTF-8 BOM (EF BB BF) at the start of the output. When `run-task.ps1` reads a task JSON, truncates the file, and rewrites it under the same FileStream lock, each write cycle adds a BOM. After a few cycles, the file starts with `﻿{` which fails `JSON.parse()` and `ConvertFrom-Json` with "Unexpected token" errors.

**What made it hard to find:** The BOM is invisible in most text editors. The error message (`Unexpected token '﻿'`) shows the BOM as a zero-width character, making it look like a blank line or encoding issue. Task files worked initially (no BOM from original creation) and only broke after the first `run-task.ps1` update cycle.

**Fix pattern:** (1) Use `[System.Text.UTF8Encoding]::new($false)` (no BOM) for all `StreamWriter` instances. (2) Create `StreamReader` with `leaveOpen=$true` and dispose explicitly after reading. (3) Add `Read-TaskJson` helper (PS) and `readTaskJson` helper (JS) that strip BOM on read and auto-repair the file. All task JSON readers go through these helpers.

### 44. Scheduler Needs Diagnostics Layer: Heartbeat, Audit Log, Atomic Writes (2026-03-20)

**Root cause:** Several diagnostic blind spots made scheduler issues hard to debug: (1) no way to verify the scheduler was alive and polling without manually checking PIDs, (2) no structured record of task dispatches (mixed into verbose service log), (3) non-atomic JSON writes via `Set-Content` could corrupt files on crash mid-write, (4) watchdog restarted too aggressively on failures, and (5) `Start-Process -Wait` blocked the entire scheduler forever if a task runner hung.

**What made it hard to find:** The scheduler appeared to work fine in normal operation. Issues only surfaced under edge conditions: process crashes mid-write, hung Agency CLI sessions, rapid restart loops after system sleep/wake. Without a heartbeat or dispatch audit trail, diagnosing these required reading scattered log files and correlating timestamps manually.

**Fix pattern:** (1) `Write-JsonAtomically` helper: write to `.tmp`, validate JSON roundtrip, rename to target, keep `.bak` for rollback. (2) `scheduler.heartbeat.json` updated every poll cycle with PID, timestamp, poll count, task counts — watchdog checks freshness. (3) `dispatch.jsonl` JSONL audit log with one structured entry per dispatch (timestamp, taskId, PID, status, exitCode, duration). (4) Service-level dispatch timeout via `-PassThru` + `WaitForExit(timeout)` instead of `-Wait`. (5) Process tree kill via `Get-CimInstance Win32_Process -Filter ParentProcessId=` on timeout. (6) Stream read timeout: `$task.Wait(5000)` instead of bare `.Result` after kill. (7) Watchdog exponential backoff `[2, 5, 10, 30, 60]s`. (8) `task-manager.ps1 diagnose` command for one-shot health check.

### 45. SGR Mouse Tracking Blocks xterm.js Link Clicks (2026-03-20)

**Root cause:** The Copilot CLI enables SGR mouse tracking (sends `CSI ?1003h`) for TUI navigation (arrow keys, tab selection). When active, xterm.js routes all mouse click events to the application instead of activating link handlers. `WebLinksAddon` highlights links on hover (hover uses `mousemove`, unaffected by tracking), but `activate()` callbacks never fire on click because the mousedown/mouseup events are consumed by the mouse tracking protocol.

**What made it hard to find:** Links appeared to work — they highlighted on hover. The click silently sent a mouse coordinate escape sequence to the PTY instead of triggering the link handler. No error, no visual feedback. xterm.js native paste via the hidden textarea also doesn't work in Electron's context-isolated renderer, so clipboard operations required explicit IPC.

**Fix pattern:** (1) Track hovered link URL/path via `WebLinksAddon` `hover`/`leave` callbacks and `registerLinkProvider` `hover()`/`leave()` on link objects. (2) Add a DOM-level `mouseup` listener on the terminal container that checks for Ctrl/Cmd modifier key — when held, opens the tracked link via IPC (`openExternalUrl` for URLs, `openFileExternal` for file paths). (3) Show a tooltip ("Ctrl+click to open") on link hover to communicate the interaction. (4) For clipboard: Ctrl-V via `attachCustomKeyEventHandler` + `app:clipboardReadText` IPC; right-click via `contextmenu` listener on `term.element` (capture phase). (5) `preventDefault()` on Ctrl-V keydown to block any native paste path.

### 46. Mode Switch Loop Must Be Serialized Per Task (2026-04-06)

**Root cause:** `task:setMode` runs an async loop that sends one Shift+Tab at a time and reads `meta.ptyMode` between each tab. The handler had no mutex — if two mode-switch requests arrived concurrently (e.g., rapid UI dropdown changes, or a test calling `/setmode` before the previous call finished), their loops would interleave: concurrent Shift+Tabs firing at the same time, and concurrent reads of `meta.ptyMode` producing inconsistent state. The result was chaotic cycling — the PTY received 6+ tabs in under a second and landed on an arbitrary mode.

**What made it hard to find:** Manual single-click mode switching appeared to work. The bug only surfaced under rapid/concurrent switches: a debug test firing 6 setMode calls with 3s spacing (while each call took up to 7.5s), or a user clicking the dropdown multiple times quickly. The timeline showed interleaved `mode-switch-tab` and `mode-switch-step` events from two concurrent loops, making the shared `meta.ptyMode` state unpredictable.

**Fix pattern:** Guard `task:setMode` with a per-task async mutex (a `Promise` chain stored on `meta._modeSwitchChain`). Each call appends to the chain:
```js
meta._modeSwitchChain = (meta._modeSwitchChain || Promise.resolve()).then(() => doSwitch());
return meta._modeSwitchChain;
```
This serializes all switch requests for the same task — a second call waits for the first to complete before sending any Shift+Tabs. Also set `MODE_STEP_DELAY_MS = 2500` to give JSONL `session.mode_changed` events time to arrive before reading `meta.ptyMode`.

**Applies to:** Any IPC handler that drives async PTY state and reads back shared mutable state mid-loop. If re-entrant invocation can corrupt shared state, serialize with a per-resource promise chain.

### 47. _pendingModeSwitch Causes False Positives From Agent Output (2026-04-06)

**Root cause:** `_pendingModeSwitch = true` enables PTY text detection — it scans every PTY output chunk for mode keywords (`"copilot"`, `"plan"`, `"autopilot"`) and immediately updates `meta.ptyMode`. This was added to read the TUI status bar (~100ms after a Shift+Tab), but agent LLM output routinely contains these same words ("...in autopilot mode...", "...plan for..."). When `_pendingModeSwitch` is left on during an active switch, any LLM output token containing a mode word corrupts `meta.ptyMode` before the JSONL confirms the real state.

**What made it hard to find:** The false positives only occurred when the task was actively generating LLM output during the 1200ms delay window. In a quiet idle session, PTY text detection worked correctly. Under load (task thinking while mode switch happens), spurious mode words in the stream caused the loop to take extra tabs.

**Fix pattern:** Do NOT set `_pendingModeSwitch = true` inside the mode switch loop. Rely exclusively on JSONL `session.mode_changed` events (updated via the JSONL watcher) for `meta.ptyMode` state during mode switching. Increase `MODE_STEP_DELAY_MS` to `2500` to give JSONL enough time to arrive. PTY text detection (`_pendingModeSwitch`) is only safe in a truly quiet PTY context — the initial session start is fine; an active task is not.

**Applies to:** Any PTY state detection that uses keyword scanning on live output. Always prefer structured protocol events (JSONL, IPC) over text scanning for state that also appears in LLM output.
