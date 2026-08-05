#!/usr/bin/env bash
# Full drift-elimination pass: links, MCP, opencode agents, history index,
# codex distill. Run by the launchd watcher (on change + hourly) and `make resync`.
set -uo pipefail
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
[ -f "$STORE/env" ] && set -a && . "$STORE/env" && set +a
python3 sync.py
python3 scripts/port-mcp.py adopt && python3 scripts/port-mcp.py apply
python3 scripts/port-agents.py
python3 scripts/history.py index
python3 scripts/distill-codex.py
echo "resync complete $(date '+%F %T')"
