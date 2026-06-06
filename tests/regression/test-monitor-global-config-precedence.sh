#!/bin/bash
# Regression test: global monitor config must win over legacy agentconfig.json once a workspace entry exists
# Date: 2026-03-15
# Bug: Teams monitor start hung because ~/.agency-cowork/monitor-config.json enabled the workspace, but repo agentconfig.json still had monitor.enabled=false and the Python service let the legacy flag override the global config.
# Root cause: scripts/monitor/config.py applied agentconfig.json overrides onto an existing global workspace entry, clobbering enabled state and making Electron and the Python service disagree about whether the monitor should run.
# Commit: pending

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TMP_HOME"' EXIT

mkdir -p "$TMP_HOME/.agency-cowork"

cat > "$TMP_HOME/.agency-cowork/monitor-config.json" <<EOF
{
  "identity": {
    "mri": "8:orgid:test-user",
    "displayName": "Test User",
    "upn": "test@example.com"
  },
  "connection": {},
  "workspaces": {
    "$REPO_ROOT": {
      "enabled": true,
      "keyword": "joo",
      "reply_prefix": "Agency Cowork: ",
      "monitored_conversations": [
        {
          "id": "*",
          "name": "All Conversations",
          "type": "Wildcard",
          "added": "2026-03-15T00:00:00Z"
        }
      ],
      "dispatch": {
        "command": "agency copilot -p",
        "working_directory": "",
        "timeout_minutes": 15,
        "send_receipt": true,
        "send_result_summary": false,
        "response_conversation": "",
        "persistent_session_id": "test-session-id",
        "use_persistent_pty": true,
        "pty_warmup_conversations": ["48:notes"],
        "pty_queue_max": 5,
        "pty_idle_timeout_minutes": 60,
        "pty_max_sessions": 5
      }
    }
  }
}
EOF

HOME="$TMP_HOME" REPO_ROOT="$REPO_ROOT" python3 - <<'PY'
import os
import sys

repo_root = os.environ["REPO_ROOT"]
sys.path.insert(0, os.path.join(repo_root, "skills", "teams"))

from scripts.monitor.config import load_global_config, _normalise_workspace_key

cfg = load_global_config()
workspace_key = _normalise_workspace_key(repo_root)
ws = cfg.workspaces.get(workspace_key)

if ws is None:
    raise SystemExit("FAIL: workspace entry disappeared while loading global config")
if not ws.enabled:
    raise SystemExit("FAIL: legacy agentconfig.json overrode enabled=true from global config")

print("PASS: global monitor config remains authoritative over legacy agentconfig.json")
PY