#!/usr/bin/env bash
# Regression test: Teams monitor identity auto-detection (issue #119)
# Ensures AADSTS530084 fallthrough and auto-populate patterns are in place.
# Date: 2026-03-21
# Root cause: Identity not auto-populated from JWT when CLI auth fails
# Fix: Extract oid/upn/name from JWT, persist to monitor-config.json

PASS=0; FAIL=0
check() {
  if eval "$2"; then
    echo "  ✓ $1"; ((PASS++))
  else
    echo "  ✗ $1"; ((FAIL++))
  fi
}

echo "=== Teams Monitor Identity Auto-Detection (issue #119) ==="

MH="skills/teams/scripts/monitor/message_handler.py"
SVC="skills/teams/scripts/monitor/service.py"
AUTH="skills/teams/scripts/api/auth.py"

echo ""
echo "--- message_handler.py ---"
check "Extracts UPN from JWT"           "grep -q 'preferred_username' $MH"
check "Extracts display name from JWT"  "grep -q '_user_display_name' $MH"
check "get_detected_identity() exists"  "grep -q 'def get_detected_identity' $MH"
check "matches_sender uses _user_mri"   "grep -q '_user_mri.*sender_mri' $MH"

echo ""
echo "--- service.py ---"
check "Imports get_detected_identity"    "grep -q 'get_detected_identity' $SVC"
check "_auto_populate_identity exists"   "grep -q 'def _auto_populate_identity' $SVC"
check "Calls _auto_populate_identity"    "grep -q '_auto_populate_identity(config)' $SVC"
check "Checks placeholder OID"          "grep -q '00000000-0000-0000-0000-000000000000' $SVC"
check "Saves to monitor-config.json"    "grep -q 'save_global_config' $SVC"
check "identity_configured in status"   "grep -q 'identity_configured' $SVC"

echo ""
echo "--- auth.py ---"
check "AADSTS530084 detection exists"   "grep -q 'AADSTS530084' $AUTH"
check "CLI blocked flag exists"         "grep -q '_cli_blocked_by_token_protection' $AUTH"
check "Playwright fallback exists"      "grep -q '_acquire_via_playwright' $AUTH"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1