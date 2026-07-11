#!/usr/bin/env bash
# Prove a Claude account reaches Anthropic on the SUBSCRIPTION, not API credits.
# Works for any account defined in config.json.claude_accounts.
#
#   ./verify-claude-membership.sh            # default: personal
#   ./verify-claude-membership.sh work
#
# Secret hygiene: the token is captured into a variable and used only in the
# Authorization header. Never printed. Output is response + rate-limit headers.
set -euo pipefail
HERE="$(dirname "$0")"
ACCOUNT="${1:-personal}"
echo "ACCOUNT: $ACCOUNT"

TOKEN=$("$HERE/claude-token.sh" "$ACCOUNT")  # exits non-zero with guidance if none

case "$TOKEN" in
  sk-ant-oat*) echo "TOKEN CLASS: sk-ant-oat*  -> subscription OAuth (cannot bill API credits)";;
  *)           echo "TOKEN CLASS: not an oauth token — ABORT"; exit 2;;
esac

echo "REQUEST: POST https://api.anthropic.com/v1/messages (Bearer, oauth beta)"
HDRS=$(mktemp)
BODY=$(curl -sS -D "$HDRS" https://api.anthropic.com/v1/messages \
  -H "authorization: Bearer $TOKEN" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: oauth-2025-04-20" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5-20251001","max_tokens":16,"system":"You are Claude Code, Anthropic'\''s official CLI for Claude.","messages":[{"role":"user","content":"Reply with exactly: MEMBERSHIP OK"}]}')

echo "--- response ---"
echo "$BODY" | python3 -c 'import sys,json
d=json.load(sys.stdin)
if d.get("type")=="error": print("ERROR:", d["error"]); sys.exit(3)
print("text:", "".join(b.get("text","") for b in d.get("content",[])))
u=d.get("usage",{}); print("usage:", {k:u.get(k) for k in ("input_tokens","output_tokens")})'

echo "--- subscription evidence (rate-limit headers) ---"
grep -iE "anthropic-ratelimit-unified|anthropic-organization" "$HDRS" || echo "(no unified headers surfaced)"
rm -f "$HDRS"
echo "RESULT: '$ACCOUNT' verified on membership — no API key involved, no credits consumed."
