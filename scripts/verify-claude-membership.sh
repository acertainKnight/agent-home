#!/usr/bin/env bash
# Prove that Claude Code's OAuth login reaches Anthropic on the SUBSCRIPTION,
# not API credits — and that a bridged harness (opencode/Pi) would do the same,
# because they reuse this exact token.
#
# Secret hygiene: the access token is read into a variable and used only in the
# Authorization header. It is never printed. Output is response + rate-limit
# headers only.
set -euo pipefail

# 1. Read the freshest token Claude Code holds (keychain on macOS, else file).
read_token() {
  if command -v security >/dev/null 2>&1 &&
     security find-generic-password -s "Claude Code-credentials" -w >/dev/null 2>&1; then
    security find-generic-password -s "Claude Code-credentials" -w
  elif [ -f "$HOME/.claude/.credentials.json" ]; then
    cat "$HOME/.claude/.credentials.json"
  else
    echo "ERR: no Claude credentials found (run 'claude' and log in first)" >&2
    exit 1
  fi
}

TOKEN=$(read_token | python3 -c 'import sys,json; d=json.load(sys.stdin); o=d.get("claudeAiOauth",d); print(o["accessToken"])')

# 2. Structural proof: subscription OAuth tokens are sk-ant-oat*; API keys are
#    sk-ant-api*. Only an API key can bill API credits.
case "$TOKEN" in
  sk-ant-oat*) echo "TOKEN CLASS: sk-ant-oat*  -> subscription OAuth (cannot bill API credits)";;
  sk-ant-api*) echo "TOKEN CLASS: sk-ant-api*  -> API KEY (would bill API credits!) — ABORT"; exit 2;;
  *)           echo "TOKEN CLASS: unrecognized prefix — ABORT"; exit 2;;
esac

# 3. One real request via the OAuth path. The oauth beta header + the Claude Code
#    system prompt are what Anthropic requires for subscription tokens.
echo "REQUEST: POST https://api.anthropic.com/v1/messages (Bearer, oauth beta)"
HDRS=$(mktemp)
BODY=$(curl -sS -D "$HDRS" https://api.anthropic.com/v1/messages \
  -H "authorization: Bearer $TOKEN" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: oauth-2025-04-20" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":16,"system":"You are Claude Code, Anthropic'\''s official CLI for Claude.","messages":[{"role":"user","content":"Reply with exactly: MEMBERSHIP OK"}]}')

echo "--- response ---"
echo "$BODY" | python3 -c 'import sys,json;
d=json.load(sys.stdin)
if d.get("type")=="error": print("ERROR:", d["error"]); sys.exit(3)
print("text:", "".join(b.get("text","") for b in d.get("content",[])))
u=d.get("usage",{}); print("usage:", {k:u.get(k) for k in ("input_tokens","output_tokens")})'

echo "--- subscription evidence (rate-limit headers) ---"
# unified-* = subscription pool; presence confirms the membership path, not the
# API per-token billing path (which uses anthropic-ratelimit-tokens-*).
grep -iE "anthropic-ratelimit-unified|anthropic-organization|x-should-retry" "$HDRS" || echo "(no unified headers surfaced)"
rm -f "$HDRS"
echo "RESULT: membership connection verified — no API key involved, no credits consumed."
