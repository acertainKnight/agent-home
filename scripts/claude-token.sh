#!/usr/bin/env bash
# Print a live Claude subscription OAuth bearer token for a named account.
# The single source of truth for "give me account X's token" — used by the
# verify script and by any harness provider that takes a command-based token.
#
#   ./claude-token.sh personal
#   ./claude-token.sh work
#
# Accounts are defined in config.json.claude_accounts: each has a config_dir
# (a CLAUDE_CONFIG_DIR, e.g. ~/.claude or ~/.claude-work) and an optional
# keychain service name. Token is read keychain-first, then
# <config_dir>/.credentials.json. Claude Code keeps its own token refreshed;
# if this one is expired, run:  CLAUDE_CONFIG_DIR=<config_dir> claude  once.
#
# Secret hygiene: prints ONLY the token, to stdout, for a consumer to capture.
# Never logs it. Exits non-zero (message on stderr) if no valid token.
set -euo pipefail
cd "$(dirname "$0")/.."
ACCOUNT="${1:-personal}"

IFS=$'\t' read -r CONFIG_DIR KEYCHAIN < <(python3 - "$ACCOUNT" <<'PY'
import json, sys, os
acct = sys.argv[1]
try:
    cfg = json.load(open("config.json"))
except OSError:
    cfg = {}
accts = cfg.get("accounts", cfg.get("claude_accounts", []))
# Anthropic-subscription accounts only (those with a config_dir).
claude = [a for a in accts if a.get("provider", "anthropic-sub") == "anthropic-sub" and a.get("config_dir")]
if not claude:
    claude = [{"name": "personal", "config_dir": "~/.claude", "keychain": "Claude Code-credentials"}]
# Match by exact name, or by suffix (so "personal" finds "claude-personal").
m = next((a for a in claude if a["name"] == acct), None) \
    or next((a for a in claude if a["name"].endswith("-" + acct) or a["name"] == "claude-" + acct), None)
if not m:
    sys.stderr.write(f"unknown claude account '{acct}'; known: {[a['name'] for a in claude]}\n"); sys.exit(1)
print(os.path.expanduser(m["config_dir"]), m.get("keychain") or "-", sep="\t")
PY
)

emit_from_json() {  # stdin = credentials json; print token or nothing
  # NB: python3 -c (not `python3 - <<HEREDOC`) so sys.stdin stays the piped data.
  python3 -c '
import json, sys, time
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
o = d.get("claudeAiOauth", d)
tok = o.get("accessToken") or ""
if not tok.startswith("sk-ant-oat"):
    sys.exit(1)
exp = o.get("expiresAt", 0)
if exp and exp/1000 < time.time():
    sys.stderr.write("token expired; run: CLAUDE_CONFIG_DIR=<dir> claude\n"); sys.exit(2)
print(tok)
'
}

TOKEN=""
if [ "$KEYCHAIN" != "-" ] && command -v security >/dev/null 2>&1; then
  TOKEN=$(security find-generic-password -s "$KEYCHAIN" -w 2>/dev/null | emit_from_json || true)
fi
if [ -z "$TOKEN" ] && [ -f "$CONFIG_DIR/.credentials.json" ]; then
  TOKEN=$(emit_from_json < "$CONFIG_DIR/.credentials.json" || true)
fi
[ -n "$TOKEN" ] || { echo "no valid subscription token for account '$ACCOUNT' (config_dir=$CONFIG_DIR). Log in: CLAUDE_CONFIG_DIR=$CONFIG_DIR claude" >&2; exit 1; }
printf '%s' "$TOKEN"
