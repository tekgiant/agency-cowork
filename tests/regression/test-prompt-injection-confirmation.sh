#!/bin/bash
# Regression test: Prompt injection must use confirmation-based detection
# Date: 2026-03-20
# Bug: On cold starts, prompt injected during "Loading environment:" was silently
#      swallowed — Enter accepted by terminal but not processed by Ink's useInput.
#      No confirmation detection meant no retry, causing silent task failure.
# Root cause: READY_RE matched early TUI indicators (splash box, ❯ prompt) that
#      appear BEFORE the CLI is truly ready. "Environment loaded:" (past tense)
#      is the only reliable ready signal.
# Fix: Confirmation-based injection — watch for "Thinking" after Enter,
#      retry on "Environment loaded:" if not confirmed. Max 3 attempts.
# Commit: a55f6d4

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Regression: Prompt injection confirmation-based detection ==="

MAIN="$REPO_ROOT/ui/electron/main.js"

# 1. Must have LOADED_RE matching "Environment loaded:" (the reliable signal)
echo -n "  LOADED_RE matches 'Environment loaded:'... "
if grep -q 'LOADED_RE.*Environment loaded:' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — LOADED_RE regex missing"
  exit 1
fi

# 2. Must have EARLY_RE for TUI splash detection (fast path, not for injection trigger)
echo -n "  EARLY_RE matches early TUI indicators... "
if grep -q 'EARLY_RE.*Type @\|Describe a task' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — EARLY_RE regex missing"
  exit 1
fi

# 3. Must have PROMPT_CONFIRM_RE for "Thinking" detection
echo -n "  PROMPT_CONFIRM_RE matches 'Thinking'... "
if grep -q 'PROMPT_CONFIRM_RE.*Thinking' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — PROMPT_CONFIRM_RE missing"
  exit 1
fi

# 4. Must have YOLO_CONFIRM_RE for "All permissions" detection
echo -n "  YOLO_CONFIRM_RE matches 'All permissions'... "
if grep -q 'YOLO_CONFIRM_RE.*All permissions' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — YOLO_CONFIRM_RE missing"
  exit 1
fi

# 5. Must track promptConfirmed state
echo -n "  promptConfirmed state tracked... "
if grep -q 'promptConfirmed = true' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — promptConfirmed not tracked"
  exit 1
fi

# 6. Must have retry logic on Environment loaded
echo -n "  Retry triggers on Environment loaded without confirmation... "
if grep -q 'LOADED_RE.test.*promptConfirmed.*MAX_PROMPT_ATTEMPTS\|env-loaded-retry' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — env-loaded-retry logic missing"
  exit 1
fi

# 7. Must have MAX_PROMPT_ATTEMPTS guard to prevent infinite retries
echo -n "  MAX_PROMPT_ATTEMPTS guard exists... "
if grep -q 'MAX_PROMPT_ATTEMPTS' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — MAX_PROMPT_ATTEMPTS missing"
  exit 1
fi

# 8. pendingYolo must be declared in writePromptOnce's closure scope (not block-scoped)
echo -n "  pendingYolo declared in closure scope (not const inside block)... "
if grep -q 'let pendingYolo' "$MAIN" && ! grep -q 'const pendingYolo' "$MAIN"; then
  echo "PASS"
else
  echo "FAIL — pendingYolo must be 'let' in closure scope, not 'const' in block"
  exit 1
fi

# 9. Safety fallback must be >= 30s (not the old 15s)
echo -n "  Safety fallback >= 30s... "
FALLBACK=$(grep -oP 'setTimeout\(writePromptOnce,\s*\K\d+' "$MAIN" | tail -1)
if [ -n "$FALLBACK" ] && [ "$FALLBACK" -ge 30000 ]; then
  echo "PASS ($FALLBACK ms)"
else
  echo "FAIL — safety fallback is ${FALLBACK:-missing}ms, need >= 30000ms"
  exit 1
fi

echo "=== All prompt injection confirmation checks passed ==="
