#!/usr/bin/env bash
# Regression test: xterm overlay scrollbar must use opacity:1 !important to stay visible
#
# Date: 2026-04-06 (updated 2026-04-07)
# Bug: display:none on .xterm-scrollable-element > .scrollbar kills mouse wheel and
#      text-selection-drag-to-scroll by removing the element from pointer-event dispatch.
# Regression (2026-04-07): opacity:1 without !important is overridden by xterm's
#   .invisible rule which appears later in the Vite-built CSS bundle (same specificity,
#   later position wins). xterm toggles .invisible, hiding the scrollbar and setting
#   pointer-events:none — breaking mouse wheel again.
# Fix: opacity:1 !important; pointer-events:auto !important on .scrollbar
# See: architecture.md Lesson #36

set -e

PASS=0
FAIL=0

check() {
  local desc="$1"
  local result="$2"
  if [ "$result" = "0" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS+1))
  else
    echo "  FAIL: $desc"
    FAIL=$((FAIL+1))
  fi
}

CSS="ui/src/index.css"
echo "=== xterm scrollbar visibility regression (index.css) ==="

# Must NOT use display:none on the xterm overlay scrollbar
grep -q "display: none" "$CSS" && \
  grep -B2 "display: none" "$CSS" | grep -q "xterm-scrollable-element" && \
  MATCH=1 || MATCH=0
check "No 'display: none' on .xterm-scrollable-element > .scrollbar" "$MATCH"

# Must NOT use display:none on .xterm-viewport
grep -q "xterm-viewport" "$CSS" && \
  grep -A5 "xterm-viewport" "$CSS" | grep -q "display: none" && \
  MATCH=1 || MATCH=0
check "No 'display: none' on .xterm-viewport" "$MATCH"

# Must use opacity:1 !important to override xterm's .invisible rule (cascade ordering fix)
grep -q "opacity: 1 !important" "$CSS"
check "Uses 'opacity: 1 !important' to override xterm .invisible cascade" "$?"

# Must use pointer-events:auto !important to override .invisible pointer-events:none
grep -q "pointer-events: auto !important" "$CSS"
check "Uses 'pointer-events: auto !important' to keep scrollbar interactive" "$?"

echo ""
echo "=== xterm wheel debug listener cleanup (XTerminal.jsx) ==="

JSX="ui/src/XTerminal.jsx"

# Debug wheel listener must have a corresponding removeEventListener cleanup
grep -q "handleWheelDebug" "$JSX"
check "handleWheelDebug listener defined" "$?"

grep -q "removeEventListener.*handleWheelDebug" "$JSX"
check "handleWheelDebug listener cleaned up in return()" "$?"

# Debug listener must be passive (never preventDefault on debug-only handler)
grep -A3 "handleWheelDebug" "$JSX" | grep -q "passive: true"
check "handleWheelDebug registered as passive" "$?"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
