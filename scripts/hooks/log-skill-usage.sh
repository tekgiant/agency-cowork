#!/usr/bin/env bash
# PreToolUse hook — logs skill invocations to a JSONL file for usage telemetry.
#
# Install by adding to .claude/settings.local.json:
#   "hooks": {
#     "PreToolUse": [
#       { "matcher": "Skill", "command": "bash scripts/hooks/log-skill-usage.sh" }
#     ]
#   }
#
# Reads from stdin: JSON with tool_name, tool_input fields.
# Appends a JSONL entry to skills-usage.jsonl with timestamp, skill name, and args.

set -euo pipefail

LOG_DIR="${HOME}/.agency-cowork/telemetry"
LOG_FILE="${LOG_DIR}/skills-usage.jsonl"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Pipe stdin through a data channel — never interpolate into code
cat <<'PYEOF' | python3 - "${LOG_FILE}" 2>/dev/null || true
import json, sys
from datetime import datetime, timezone

log_file = sys.argv[1]

try:
    data = json.loads(sys.stdin.read())
except Exception:
    data = {}

tool_input = data.get('tool_input', {})
skill = tool_input.get('skill', 'unknown')
args = tool_input.get('args', '')

entry = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'skill': skill,
    'args': args[:200] if args else None,
    'tool': data.get('tool_name', 'unknown'),
}

with open(log_file, 'a') as f:
    f.write(json.dumps(entry) + '\n')
PYEOF

# Always exit 0 — logging failures should never block skill execution
exit 0
