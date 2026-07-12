#!/usr/bin/env bash
# Show every Claude account's membership rate-limit pools (the unified 5h/7d
# windows) side by side, so you know which account has headroom before a big
# session. One 1-token request per account; tokens are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
export AGENT_HOME_CONFIG="${AGENT_HOME:-$HOME/.agent-home}/config.json"

NAMES=$(python3 -c '
import json, os
try: c = json.load(open(os.environ["AGENT_HOME_CONFIG"]))
except OSError: c = {}
for a in c.get("accounts", c.get("claude_accounts", [])):
    if a.get("provider", "anthropic-sub") == "anthropic-sub":
        print(a.get("name",""))
')
[ -n "$NAMES" ] || { echo "no Claude accounts in config.json"; exit 1; }

for name in $NAMES; do
  echo "== $name =="
  if ! TOKEN=$(./scripts/claude-token.sh "$name" 2>/dev/null); then
    echo "  (not logged in — make login)"; continue
  fi
  curl -sS -D - -o /dev/null https://api.anthropic.com/v1/messages \
    -H "authorization: Bearer $TOKEN" \
    -H "anthropic-version: 2023-06-01" \
    -H "anthropic-beta: oauth-2025-04-20" \
    -H "content-type: application/json" \
    -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"system":"You are Claude Code, Anthropic'\''s official CLI for Claude.","messages":[{"role":"user","content":"hi"}]}' \
    | grep -i '^anthropic-ratelimit-unified' | sed 's/^/  /' \
    || echo "  (request failed — token may need refresh: make login)"
done
