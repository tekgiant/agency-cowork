#!/usr/bin/env python3
"""Regression test for _token_match() in cache-manager.py.

Date:       2026-03-26
Bug:        Issue #134 — email-triage posted sensitive triage summary to
            vendor's Teams chat because "self" substring-matched
            "Vendor Self-Service Portal" topic.
Root cause: cache-manager.py used Python `in` operator for substring matching,
            allowing short queries to match inside longer unrelated strings.
Fix:        Replaced `in` with _token_match() using word-boundary regex that
            treats hyphens as word-internal characters.
"""
import sys
import os

# Add the skills/teams/scripts directory to the path so we can import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "teams", "scripts"))

from importlib import import_module

# Import the cache-manager module (hyphen in name requires importlib)
cm = import_module("cache-manager")
_token_match = cm._token_match
normalize = cm.normalize

passed = 0
failed = 0


def check(description, result, expected):
    global passed, failed
    status = "PASS" if result == expected else "FAIL"
    if status == "FAIL":
        failed += 1
        print(f"  {status}: {description} (got {result}, expected {expected})")
    else:
        passed += 1
        print(f"  {status}: {description}")


print("=== _token_match() regression tests ===\n")

# --- CRITICAL: the bug scenario from #134 ---
print("[1] Self-chat leak prevention")
check('"self" must NOT match "Vendor Self-Service Portal"',
      _token_match("self", "Vendor Self-Service Portal"), False)
check('"self" must NOT match "self-service"',
      _token_match("self", "self-service"), False)
check('"self" must NOT match "self-assessment"',
      _token_match("self", "self-assessment"), False)

# --- Self-chat keywords that SHOULD match ---
print("\n[2] Self-chat keywords (positive matches)")
check('"self" matches "self" (exact)',
      _token_match("self", "self"), True)
check('"self" matches "Notes to Self"',
      _token_match("self", "Notes to Self"), True)
check('"notes" matches "Notes to Self"',
      _token_match("notes", "Notes to Self"), True)
check('"self-chat" matches "My Self-Chat"',
      _token_match("self-chat", "My Self-Chat"), True)

# --- Substring false positives that must NOT match ---
print("\n[3] Substring false positive prevention")
check('"john" must NOT match "johnson"',
      _token_match("john", "johnson"), False)
check('"art" must NOT match "artificial"',
      _token_match("art", "artificial"), False)
check('"team" must NOT match "steamroller"',
      _token_match("team", "steamroller"), False)
check('"data" must NOT match "metadata"',
      _token_match("data", "metadata"), False)

# --- Legitimate word-boundary matches ---
print("\n[4] Legitimate word-boundary matches")
check('"john" matches "John Smith"',
      _token_match("john", "John Smith"), True)
check('"data" matches "Data Engineering Team"',
      _token_match("data", "Data Engineering Team"), True)
check('"budget" matches "Q3 Budget Review"',
      _token_match("budget", "Q3 Budget Review"), True)
check('"maia" matches "Project Maia"',
      _token_match("maia", "Project Maia"), True)

# --- Hyphenated compound words ---
print("\n[5] Hyphenated compound word handling")
check('"self-service" matches "Vendor Self-Service Portal"',
      _token_match("self-service", "Vendor Self-Service Portal"), True)
check('"co-pilot" matches "GitHub Co-Pilot Team"',
      _token_match("co-pilot", "GitHub Co-Pilot Team"), True)
check('"pilot" must NOT match "co-pilot"',
      _token_match("pilot", "co-pilot"), False)

# --- Edge cases ---
print("\n[6] Edge cases")
check("empty query returns False",
      _token_match("", "some text"), False)
check("empty text returns False",
      _token_match("query", ""), False)
check("both empty returns False",
      _token_match("", ""), False)
check('"test" matches "test" (exact, single word)',
      _token_match("test", "test"), True)
check("case insensitive: 'JOHN' matches 'john smith'",
      _token_match("JOHN", "john smith"), True)

# --- UPN-style matching ---
print("\n[7] UPN/email matching")
check('"user@contoso.com" matches exact UPN',
      _token_match("user@contoso.com", "user@contoso.com"), True)
# Note: @ and . are word boundaries, so partial email matching works.
# This is desired — searching "contoso" should find contoso.com contacts.
check('"user" matches "user@contoso.com" (@ is a word boundary)',
      _token_match("user", "user@contoso.com"), True)
check('"contoso" matches "user@contoso.com" (. is a word boundary)',
      _token_match("contoso", "user@contoso.com"), True)

# --- Team/channel name matching (audit finding: cmd_lookup_team/channel) ---
print("\n[8] Team and channel name matching")
check('"data" must NOT match "Metadata Analytics"',
      _token_match("data", "Metadata Analytics"), False)
check('"data" matches "Data Engineering"',
      _token_match("data", "Data Engineering"), True)
check('"general" matches "General"',
      _token_match("general", "General"), True)
check('"general" must NOT match "Generalizations Team"',
      _token_match("general", "Generalizations Team"), False)
check('"ops" must NOT match "DevOps Pipeline"',
      _token_match("ops", "DevOps Pipeline"), False)
check('"devops" matches "DevOps Pipeline"',
      _token_match("devops", "DevOps Pipeline"), True)
check('"design" must NOT match "Redesign Sprint"',
      _token_match("design", "Redesign Sprint"), False)
check('"design" matches "Design Review"',
      _token_match("design", "Design Review"), True)

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(1 if failed > 0 else 0)
