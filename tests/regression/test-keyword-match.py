#!/usr/bin/env python3
"""Regression test for matches_keyword() and extract_prompt() in message_handler.py.

Date:       2026-04-09
Bug #1:     Teams Monitor triggered on any message containing substring 'tai'
            (e.g. 'details', 'maintain', 'certain', 'sustainability') instead
            of only responding to actual @tai mentions.
Root cause: matches_keyword() used Python 'in' operator for substring matching.
Fix:        Word-boundary regex via _keyword_boundary_match().

Bug #2:     Teams Monitor triggered on bare 'agent' / 'agents' without an @.
            The @-stripped fallback matched any standalone use of the keyword.
Root cause: matches_keyword() unconditionally matched keyword[1:] (bare word)
            whenever the keyword started with '@'.
Fix:        Bare-word fallback now requires raw HTML to contain an <at> tag
            wrapping the keyword, proving it was a real Teams @mention.
"""
import sys
import os

# Add paths so we can import the monitor package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skills", "teams", "scripts"))

from monitor.message_handler import matches_keyword, extract_prompt

passed = 0
failed = 0


def check(description, result, expected):
    global passed, failed
    status = "PASS" if result == expected else "FAIL"
    if status == "FAIL":
        failed += 1
        print(f"  {status}: {description} (got {result!r}, expected {expected!r})")
    else:
        passed += 1
        print(f"  {status}: {description}")


print("=== matches_keyword() regression tests ===\n")

# --- CRITICAL: the bug scenario — substring false positives ---
print("[1] Substring false positives with '@tai' keyword")
check('"@tai" must NOT match "I need the details"',
      matches_keyword("I need the details", "@tai"), False)
check('"@tai" must NOT match "Please maintain the system"',
      matches_keyword("Please maintain the system", "@tai"), False)
check('"@tai" must NOT match "This contains important info"',
      matches_keyword("This contains important info", "@tai"), False)
check('"@tai" must NOT match "certain conditions apply"',
      matches_keyword("certain conditions apply", "@tai"), False)
check('"@tai" must NOT match "Captain America"',
      matches_keyword("Captain America", "@tai"), False)
check('"@tai" must NOT match "curtailed spending"',
      matches_keyword("curtailed spending", "@tai"), False)
check('"@tai" must NOT match "sustainability"',
      matches_keyword("sustainability", "@tai"), False)

# --- Bug #2: bare word without @mention must NOT trigger ---
print("\n[2] Bare word false positives (no <at> tag = no match)")
check('"@agent" must NOT match bare "agent do this" (no raw HTML)',
      matches_keyword("agent do this", "@agent"), False)
check('"@agent" must NOT match bare "agents working" (no raw HTML)',
      matches_keyword("agents working", "@agent"), False)
check('"@tai" must NOT match bare "tai search emails" (no raw HTML)',
      matches_keyword("tai search emails", "@tai"), False)
check('"@tai" must NOT match bare "tai" standalone (no raw HTML)',
      matches_keyword("tai", "@tai"), False)
check('"@tai" must NOT match bare "TAI do something" (no raw HTML)',
      matches_keyword("TAI do something", "@tai"), False)

# --- Literal @keyword in plain text still matches ---
print("\n[3] Literal @keyword in text (always matches)")
check('"@tai" matches "@tai search emails"',
      matches_keyword("@tai search emails", "@tai"), True)
check('"@tai" matches "hey @tai can you help"',
      matches_keyword("hey @tai can you help", "@tai"), True)
check('"@tai" matches "@Tai" (case-insensitive)',
      matches_keyword("@Tai do something", "@tai"), True)
check('"@tai" matches "@tai" alone',
      matches_keyword("@tai", "@tai"), True)
check('"@agent" matches "@agent do this"',
      matches_keyword("@agent do this", "@agent"), True)

# --- HTML-stripped @mentions with <at> tag proof ---
AT_TAI_HTML = '<div><at id="abc">tai</at> search emails</div>'
AT_AGENT_HTML = '<div><at id="xyz">agent</at> do this</div>'
print("\n[4] HTML-stripped @mentions with <at> tag (must match)")
check('"@tai" matches "tai search emails" with <at>tai</at> in raw HTML',
      matches_keyword("tai search emails", "@tai", AT_TAI_HTML), True)
check('"@agent" matches "agent do this" with <at>agent</at> in raw HTML',
      matches_keyword("agent do this", "@agent", AT_AGENT_HTML), True)
check('"@tai" matches standalone "tai" with <at> tag',
      matches_keyword("tai", "@tai", '<at>tai</at>'), True)
check('"@tai" matches "hello tai" with <at> tag',
      matches_keyword("hello tai", "@tai", 'hello <at>tai</at>'), True)

# --- Non-@ keyword (plain word, no @ prefix) ---
print("\n[5] Non-@ keyword (e.g. 'agent')")
check('"agent" matches "agent do this"',
      matches_keyword("agent do this", "agent"), True)
check('"agent" must NOT match "reagent"',
      matches_keyword("reagent", "agent"), False)
check('"agent" must NOT match "agents"',
      matches_keyword("agents", "agent"), False)

# --- Edge: <at> tag present but for wrong keyword ---
print("\n[6] <at> tag for wrong keyword must not match")
check('"@agent" must NOT match bare "agent" when <at> wraps "bob"',
      matches_keyword("agent do this", "@agent", '<at>bob</at> agent do this'), False)

print("\n=== extract_prompt() regression tests ===\n")

# --- extract_prompt with literal @keyword ---
print("[7] Prompt extraction with literal @keyword")
check('extract "@tai search emails" → "search emails"',
      extract_prompt("@tai search emails", "@tai"), "search emails")
check('extract "hey @tai join General" → "join General"',
      extract_prompt("hey @tai join General", "@tai"), "join General")

# --- extract_prompt with HTML-stripped @mention ---
print("\n[8] Prompt extraction with <at> tag proof")
check('extract "tai search emails" with <at> → "search emails"',
      extract_prompt("tai search emails", "@tai", AT_TAI_HTML), "search emails")
check('extract "TAI status" with <at> → "status"',
      extract_prompt("TAI status", "@tai", '<at>TAI</at> status'), "status")

# --- extract_prompt must not grab wrong position from substring ---
print("\n[9] Prompt extraction avoids substring positions")
check('extract "detailed @tai list" → "list" (not from "tai" in "detailed")',
      extract_prompt("detailed @tai list", "@tai"), "list")
check('extract "detailed tai list" with <at> → "list"',
      extract_prompt("detailed tai list", "@tai", '<at>tai</at> list'), "list")

# --- extract_prompt without match falls back to full text ---
print("\n[10] Prompt extraction fallback (no match)")
check('extract "just some text" with "@agent" (no match) → full text',
      extract_prompt("just some text", "@agent"), "just some text")

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(1 if failed > 0 else 0)
