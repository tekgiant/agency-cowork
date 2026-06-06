#!/usr/bin/env bash
# Regression test: session ID must be propagated to new task when sending from a saved task
#
# Bug: startTask() always generated a fresh taskId = String(Date.now()).
#      agent.getSessionId(newTaskId) always returned null because the session
#      was stored under the old (saved) task's ID. Result: PTY was spawned with
#      sessionId:"new" instead of --resume=<saved-session-id>.
#
# Fix (App.jsx): Before calling dispatchTask, copy the active task's session ID
#      to the new task ID via agent.setSessionId(newTaskId, inheritedSessionId).
#
# First introduced: regression since at least v1.0.7 (startTask never had
# session propagation — resume only worked via handleFollowUp/dispatchFollowUp
# which used activeTask.id directly rather than creating a fresh taskId).
#
# Fixed in: PR branch fix/prompt-delivery-hang-219 (this commit)

set -euo pipefail

PASS=0
FAIL=0

check() {
  local desc="$1"
  local result="$2"
  if [ "$result" = "1" ]; then
    echo "PASS: $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $desc"
    FAIL=$((FAIL + 1))
  fi
}

APP_JSX="ui/src/App.jsx"

# 1. startTask must read the active task's session ID before creating the new task
check "startTask reads inheritedSessionId from activeTask before dispatchTask" \
  "$(grep -c 'inheritedSessionId.*agent\.getSessionId\|agent\.getSessionId.*activeTask' "$APP_JSX")"

# 2. startTask must propagate it to the new taskId in the sessions map
check "startTask propagates inherited session to new taskId" \
  "$(grep -c 'agent\.setSessionId(taskId, inheritedSessionId)' "$APP_JSX")"

# 3. The guard must be conditional (don't set null/undefined)
check "session propagation is guarded (if inheritedSessionId)" \
  "$(grep -c 'if (inheritedSessionId) agent\.setSessionId' "$APP_JSX")"

# 4. dispatchTask already reads sessionId via agent.getSessionId(taskId) — must still be present
check "dispatchTask reads sessionId via agent.getSessionId(taskId)" \
  "$(grep -c 'agent\.getSessionId(taskId)' "$APP_JSX")"

# 5. startTask's useCallback dep array must include both activeTask and agent
check "startTask useCallback deps include activeTask and agent" \
  "$(grep -A2 'const startTask = useCallback' "$APP_JSX" | grep -c 'activeTask.*agent\|agent.*activeTask' || \
     awk '/const startTask = useCallback/,/\], \[/' "$APP_JSX" | grep -c 'activeTask' && \
     awk '/const startTask = useCallback/,/\], \[/' "$APP_JSX" | grep -c 'agent')"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
