#!/usr/bin/env bash
# PreToolUse hook — adds a safety confirmation for outbound actions (email, Teams posts).
#
# This hook intercepts MCP tools that send data externally and logs the action.
# It does NOT block execution — the skill-level confirmation flow handles that.
# This provides a second layer of auditability.
#
# Install by adding to .claude/settings.local.json:
#   "hooks": {
#     "PreToolUse": [
#       { "matcher": "mcp__microsoft-outlook-mail__SendEmailWithAttachments", "command": "bash scripts/hooks/confirm-outbound.sh" },
#       { "matcher": "mcp__microsoft-teams__PostMessage", "command": "bash scripts/hooks/confirm-outbound.sh" },
#       { "matcher": "mcp__microsoft-teams__PostChannelMessage", "command": "bash scripts/hooks/confirm-outbound.sh" }
#     ]
#   }
#
# Reads from stdin: JSON with tool_name, tool_input fields.
# Appends an audit entry to outbound-actions.jsonl.

set -euo pipefail

LOG_DIR="${HOME}/.agency-cowork/telemetry"
LOG_FILE="${LOG_DIR}/outbound-actions.jsonl"

mkdir -p "${LOG_DIR}"

# Pipe stdin through a data channel — never interpolate into code
cat <<'PYEOF' | python3 - "${LOG_FILE}" 2>/dev/null || true
import json, sys, os
from datetime import datetime, timezone

log_file = sys.argv[1]

try:
    data = json.loads(sys.stdin.read())
except Exception:
    data = {}

tool = data.get('tool_name', 'unknown')
tool_input = data.get('tool_input', {})

# Extract key fields for audit trail
entry = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'tool': tool,
    'action': 'outbound',
}

# For email — log recipients (not body)
if 'to' in tool_input:
    entry['recipients'] = tool_input['to'] if isinstance(tool_input['to'], list) else [tool_input['to']]
if 'subject' in tool_input:
    entry['subject'] = tool_input['subject'][:100]

# For Teams — log chat/channel target
if 'chatId' in tool_input:
    entry['chatId'] = tool_input['chatId'][:50]
if 'channelId' in tool_input:
    entry['channelId'] = tool_input['channelId'][:50]

with open(log_file, 'a') as f:
    f.write(json.dumps(entry) + '\n')
PYEOF

exit 0
