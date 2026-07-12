#!/usr/bin/env bash
# agent-home doctor — one command that says whether the whole system is still
# healthy, and the exact fix when it isn't. Read-only; safe to run anytime.
set -uo pipefail   # no -e: every check must run even after a failure
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
export AGENT_HOME_CONFIG="$STORE/config.json"
FAILS=0
ok()   { echo "  ✓ $1"; }
bad()  { echo "  ✗ $1"; FAILS=$((FAILS+1)); }
info() { echo "  · $1"; }

echo "== agent-home doctor =="

# store + config
[ -d "$STORE" ] && ok "store: $STORE" || bad "store missing — run: make install"
[ -f "$STORE/config.json" ] && ok "config.json present" || bad "config.json missing — run: make install"

# symlinks
NOTOK=$(python3 sync.py --status 2>/dev/null | grep -cE '^(WRONG|MISS|REAL)' || true)
[ "${NOTOK:-0}" -eq 0 ] && ok "symlinks: all OK" \
  || bad "$NOTOK link(s) not OK — run: make sync   (details: make status)"

# ~/.agents/skills broken links (a deleted plugin leaves dangling symlinks)
BROKEN=$(find "$HOME/.agents/skills" -type l ! -exec test -e {} \; -print 2>/dev/null | wc -l | tr -d ' ')
[ "${BROKEN:-0}" -eq 0 ] && ok "~/.agents/skills: no broken links" \
  || bad "$BROKEN broken skill link(s) — run: make sync"

# plugin changes since last skill rebuild
PLUG="$HOME/.claude/plugins/installed_plugins.json"
if [ -f "$PLUG" ] && [ "$PLUG" -nt "$HOME/.agents/skills" ]; then
  bad "Claude plugins changed since last sync — run: make sync"
else
  ok "plugin skills up to date"
fi

# accounts (token liveness; never prints tokens)
while IFS='|' read -r name provider cdir envkey; do
  [ -z "$name" ] && continue
  case "$provider" in
    anthropic-sub)
      ./scripts/claude-token.sh "$name" >/dev/null 2>&1 \
        && ok "account $name: live subscription token" \
        || bad "account $name: no/expired token — CLAUDE_CONFIG_DIR=$cdir claude auth login" ;;
    chatgpt-sub)
      [ -f "${cdir:-$HOME/.codex}/auth.json" ] \
        && ok "account $name: codex auth present" \
        || bad "account $name: not logged in — CODEX_HOME=${cdir:-$HOME/.codex} codex login" ;;
    openai-key)
      val=""; [ -n "$envkey" ] && eval "val=\"\${$envkey:-}\""
      [ -n "$val" ] && ok "account $name: \$$envkey set" || bad "account $name: \$$envkey unset — add it to $STORE/env" ;;
  esac
done < <(python3 -c '
import json, os
try: c = json.load(open(os.environ["AGENT_HOME_CONFIG"]))
except OSError: c = {}
for a in c.get("accounts", c.get("claude_accounts", [])):
    d = a.get("config_dir") or a.get("codex_home") or ""
    print(a.get("name",""), a.get("provider","anthropic-sub"), os.path.expanduser(d), a.get("env_key",""), sep="|")
')

# shared env
if [ -f "$STORE/env" ]; then
  grep -qs 'agent-home' "$HOME/.zshenv" 2>/dev/null \
    && ok "shared env wired into ~/.zshenv" \
    || bad "shared env exists but ~/.zshenv doesn't source it — re-run: make install"
else
  info "no shared env file ($STORE/env) — optional; created by make install"
fi

# MCP distribution freshness
MCP="$STORE/mcp.json"
if [ -f "$MCP" ]; then
  STALE=""
  OC="$HOME/.config/opencode/opencode.jsonc"; [ -f "$OC" ] && [ "$MCP" -nt "$OC" ] && STALE="opencode"
  for home in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))" 2>/dev/null); do
    [ -f "$home/config.toml" ] && [ "$MCP" -nt "$home/config.toml" ] && STALE="$STALE codex"
  done
  [ -z "$STALE" ] && ok "MCP configs up to date" || bad "mcp.json newer than:$STALE — run: make mcp"
fi

# LiteLLM (on-demand service, so absence is informational)
if [ "$(python3 -c "import json,os;print(json.load(open(os.environ['AGENT_HOME_CONFIG'])).get('litellm',False))" 2>/dev/null)" = "True" ]; then
  if nc -z localhost 4000 2>/dev/null; then ok "LiteLLM responding on :4000"
  else info "LiteLLM not running (start when needed: make litellm)"; fi
fi

echo
[ "$FAILS" -eq 0 ] && echo "All healthy." || echo "$FAILS problem(s) — fixes listed above."
exit $((FAILS > 0))
