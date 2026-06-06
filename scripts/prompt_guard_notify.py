"""Prompt guard notification helper.

Sends injection detection alerts to the owner via Teams self-chat and/or email.
Reads notification preferences from agentconfig.json → prompt_guard section.

Usage:
    python scripts/prompt_guard_notify.py --severity critical --source monitor \
        --patterns "ignore_instructions,data_exfiltration" --preview "ignore all previous..."

Called by integrations (monitor service, task scheduler) when injection is detected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENT_CONFIG = _REPO_ROOT / "agentconfig.json"
_TEAMS_ROOT = _REPO_ROOT / "skills" / "teams"


def _read_config() -> dict:
    """Read prompt_guard section from agentconfig.json."""
    try:
        if _AGENT_CONFIG.exists():
            with open(_AGENT_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f).get("prompt_guard", {})
    except (json.JSONDecodeError, OSError):
        pass
    return {"enabled": True, "notify_teams": True, "notify_email": False}


def notify_teams(severity: str, source: str, patterns: str, preview: str) -> bool:
    """Send alert to Teams self-chat (48:notes). Returns True on success."""
    body = (
        f"⚠️ **Prompt Injection Blocked**\n\n"
        f"**Severity:** {severity}\n"
        f"**Source:** {source}\n"
        f"**Patterns:** {patterns}\n"
        f"**Preview:** {preview[:150]}"
    )
    try:
        result = subprocess.run(
            ["python", "-m", "scripts.rich.send_message",
             "--to", "48:notes", "--body", body],
            cwd=str(_TEAMS_ROOT),
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def notify_email(severity: str, source: str, patterns: str, preview: str) -> bool:
    """Send alert email to self. Returns True on success.

    Note: This is a best-effort notification. The actual email send requires
    the Outlook MCP tools which run in the agent context. This function writes
    a notification request file that the agent can pick up.
    """
    notif = {
        "type": "prompt_injection_alert",
        "severity": severity,
        "source": source,
        "patterns": patterns,
        "preview": preview[:200],
    }
    try:
        notif_dir = _REPO_ROOT / "logs"
        notif_dir.mkdir(parents=True, exist_ok=True)
        notif_path = notif_dir / "pending-email-notification.json"
        with open(notif_path, "w", encoding="utf-8") as f:
            json.dump(notif, f, indent=2)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Send prompt injection alert")
    parser.add_argument("--severity", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--patterns", required=True)
    parser.add_argument("--preview", default="")
    args = parser.parse_args()

    config = _read_config()
    if not config.get("enabled", True):
        print("Prompt guard notifications disabled")
        sys.exit(0)

    sent = False
    if config.get("notify_teams", True):
        ok = notify_teams(args.severity, args.source, args.patterns, args.preview)
        print(f"Teams notification: {'sent' if ok else 'failed'}")
        sent = sent or ok

    if config.get("notify_email", False):
        ok = notify_email(args.severity, args.source, args.patterns, args.preview)
        print(f"Email notification: {'queued' if ok else 'failed'}")
        sent = sent or ok

    sys.exit(0 if sent else 1)


if __name__ == "__main__":
    main()
