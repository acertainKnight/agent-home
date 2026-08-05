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

# codex native skill dir mirrors ~/.agents/skills
for chome in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))" 2>/dev/null); do
  WANT=$(find "$HOME/.agents/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
  HAVE=$(find "$chome/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
  CBROKEN=$(find "$chome/skills" -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null | wc -l | tr -d ' ')
  if [ "${CBROKEN:-0}" -gt 0 ] || [ "${HAVE:-0}" -lt "${WANT:-0}" ]; then
    bad "$chome/skills: $HAVE/$WANT skills linked, $CBROKEN broken — run: make sync"
  else
    ok "$chome/skills: $HAVE skills linked"
  fi
done

# opencode reads the shared skill library
OCJ="$HOME/.config/opencode/opencode.jsonc"
if [ -f "$OCJ" ]; then
  grep -qs '.agents/skills' "$OCJ" \
    && ok "opencode skills.paths -> ~/.agents/skills" \
    || bad "opencode.jsonc missing skills.paths — run: python3 scripts/wire-opencode.py"
fi

# generated command library (store + plugin commands → codex prompts, opencode command)
CMDS=$(find "$HOME/.agents/commands" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
[ "${CMDS:-0}" -gt 0 ] && ok "~/.agents/commands: $CMDS commands linked" \
  || bad "~/.agents/commands empty — run: make sync"

# auto-resync watcher
launchctl list 2>/dev/null | grep -q com.agent-home.sync \
  && ok "auto-resync watcher loaded (hourly + on change)" \
  || bad "watcher not loaded — run: make watcher"

# cortex env parity: Claude gets CORTEX_* via settings.json env; other harnesses
# (and the codex distill sweep) only see it through the shared env file.
if python3 -c "import json,sys;s=json.load(open('$HOME/.claude/settings.json'));sys.exit(0 if 'CORTEX_API_TOKEN' in s.get('env',{}) else 1)" 2>/dev/null; then
  grep -qs 'CORTEX_API_TOKEN' "$STORE/env" 2>/dev/null \
    && ok "cortex env shared cross-harness" \
    || bad "CORTEX_* env only in Claude settings.json — copy to $STORE/env"
fi
[ -z "${CORTEX_BRAIN_URL:-}" ] && ! grep -qs 'CORTEX_BRAIN_URL' "$STORE/env" 2>/dev/null \
  && info "CORTEX_BRAIN_URL unset — session distill dormant in ALL harnesses (hooks exit early)"

# codex native memory (memories_*.sqlite): we rely on AGENTS.md pointing codex
# at the shared store; if its own memory starts filling up, those learnings are
# invisible to other harnesses until exported.
for chome in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))" 2>/dev/null); do
  for db in "$chome"/memories_*.sqlite; do
    [ -f "$db" ] || continue
    ROWS=$(sqlite3 "$db" "select count(*) from stage1_outputs" 2>/dev/null || echo 0)
    [ "${ROWS:-0}" -eq 0 ] \
      && ok "codex native memory empty (all learnings flow through the store)" \
      || bad "codex native memory has $ROWS session memories NOT in the shared store — export or disable codex memory"
  done
done

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
