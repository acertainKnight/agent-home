#!/usr/bin/env bash
# Full drift-elimination pass: links, MCP, opencode agents, history index,
# codex distill. Run by the launchd watcher (on change + hourly) and `make resync`.
set -uo pipefail
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
[ -f "$STORE/env" ] && set -a && . "$STORE/env" && set +a
python3 sync.py --sweep
CIO=$(python3 -c "import json;print(str(json.load(open('$STORE/config.json')).get('claude_in_opencode',False)).lower())" 2>/dev/null || echo false)
python3 scripts/wire-opencode.py "$CIO"
python3 scripts/port-mcp.py adopt && python3 scripts/port-mcp.py apply
python3 scripts/port-agents.py
python3 scripts/history.py index
python3 scripts/history.py latest
python3 scripts/distill-codex.py
echo "resync complete $(date '+%F %T')"
