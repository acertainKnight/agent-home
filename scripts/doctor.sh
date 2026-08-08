#!/usr/bin/env bash
# agent-home doctor — one command that says whether the whole system is still
# healthy, and the exact fix when it isn't. Read-only; safe to run anytime.
#
# Standing rule: a health check must assert that a thing RAN and produced the
# RIGHT CONTENT — never that it exists. "Listed in launchctl" is not "running
# successfully"; "file is newer" is not "file has the right keys."
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

# opencode.jsonc must parse, and must carry the key wire-opencode.py owns
# post-LiteLLM-retirement (skills.paths — NOT provider.litellm, which is gone
# on purpose: opencode >=1.18 does native auth instead, checked below).
OCJ="$HOME/.config/opencode/opencode.jsonc"
if [ -f "$OCJ" ]; then
  OCJ_STATUS=$(python3 - "$OCJ" <<'PY' 2>/dev/null
import json, re, sys
raw = open(sys.argv[1]).read()
raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
raw = re.sub(r"(^|\s)//[^\n]*", "", raw)
raw = re.sub(r",(\s*[}\]])", r"\1", raw)
try:
    cfg = json.loads(raw) or {}
except json.JSONDecodeError:
    print("PARSE_FAIL"); sys.exit()
print("OK" if cfg.get("skills", {}).get("paths") else "NO_KEY")
PY
)
  case "$OCJ_STATUS" in
    OK)     ok "opencode.jsonc: parses, skills.paths -> ~/.agents/skills" ;;
    NO_KEY) bad "opencode.jsonc parses but skills.paths missing — run: python3 scripts/wire-opencode.py" ;;
    *)      bad "opencode.jsonc UNPARSEABLE — run: python3 scripts/wire-opencode.py (backs up + rewrites clean)" ;;
  esac

  # native auth (opencode >=1.18) — replaces the retired provider.litellm block
  OC_AUTH="$HOME/.local/share/opencode/auth.json"
  if [ -f "$OC_AUTH" ]; then
    python3 -c "import json,sys;sys.exit(0 if 'openrouter' in json.load(open('$OC_AUTH')) else 1)" 2>/dev/null \
      && ok "opencode: OpenRouter native auth present" \
      || bad "opencode: no openrouter entry in $OC_AUTH — run: opencode auth login"
    python3 -c "import json,sys;a=json.load(open('$OC_AUTH'));sys.exit(0 if any(k in a for k in ('openai','chatgpt')) else 1)" 2>/dev/null \
      && ok "opencode: ChatGPT-plan native auth present" \
      || info "opencode: no ChatGPT-plan login (optional — opencode auth login)"
    python3 -c "import json,sys;sys.exit(0 if 'anthropic' in json.load(open('$OC_AUTH')) else 1)" 2>/dev/null \
      && ok "opencode: Anthropic native auth present (sanctioned since May/Jun 2026 — see MEMBERSHIPS.md)" \
      || info "opencode: no Anthropic login (optional — opencode auth login; native flow, no shim)"
  else
    bad "opencode: no $OC_AUTH — run: opencode auth login"
  fi
fi

# generated command library (store + plugin commands → codex prompts, opencode command)
CMDS=$(find "$HOME/.agents/commands" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
[ "${CMDS:-0}" -gt 0 ] && ok "~/.agents/commands: $CMDS commands linked" \
  || bad "~/.agents/commands empty — run: make sync"

# auto-resync watcher — "loaded" is not "working": this printed "loaded" through
# 104 consecutive real failures because it only checked launchctl's job LIST,
# never the job's exit status or whether a resync ever actually completed. Now
# it reads the exit-status column (3rd field of `launchctl list`'s matching
# line; "0" or "-" = healthy, anything else = the last run failed) AND
# requires a "resync complete" line in the watcher log within 2x StartInterval
# (300s in scripts/install-watcher.sh, so 600s here).
WSTATUS=$(launchctl list 2>/dev/null | awk '$3=="com.agent-home.sync"{print $2}')
MAXAGE=600
if [ -z "$WSTATUS" ]; then
  bad "watcher not loaded — run: make watcher"
elif [ "$WSTATUS" != "0" ] && [ "$WSTATUS" != "-" ]; then
  bad "watcher loaded but last run exited $WSTATUS — see $STORE/.watcher.log"
else
  LAST=$(grep -a "resync complete" "$STORE/.watcher.log" 2>/dev/null | tail -1 | sed 's/.*resync complete //')
  LAST_EPOCH=$(date -j -f "%F %T" "${LAST:-1970-01-01 00:00:00}" +%s 2>/dev/null || echo 0)
  AGE=$(( $(date +%s) - LAST_EPOCH ))
  if [ -n "$LAST" ] && [ "$AGE" -le "$MAXAGE" ]; then
    ok "auto-resync watcher: exit $WSTATUS, last resync ${AGE}s ago (limit ${MAXAGE}s)"
  else
    bad "watcher: no successful resync within ${MAXAGE}s in $STORE/.watcher.log — run: ./scripts/resync.sh"
  fi
fi

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
      || bad "codex native memory has $ROWS session memories NOT in the shared store — run: python3 scripts/distill-codex-memory.py"
  done
done

# hook-carrying plugins installed in Codex: plugin listed + enabled in
# config.toml AND its manifest actually references a hooks file. This proves
# the install step ran, NOT that the hook fires — firing needs hook TRUST,
# granted only in an interactive session (see README's Hooks row, #19).
for chome in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))" 2>/dev/null); do
  RESULT=$(python3 scripts/codex-hooks-status.py "$chome" "$STORE" 2>/dev/null)
  TOTAL="${RESULT%%|*}"; MISSING="${RESULT#*|}"
  if [ -z "${TOTAL:-}" ]; then
    info "$chome: could not read plugin state (no config.toml yet?)"
  elif [ "$TOTAL" -eq 0 ]; then
    info "$chome: no enabled plugin ships hooks"
  elif [ -z "$MISSING" ]; then
    ok "$chome: $TOTAL hook-carrying plugin(s) installed+enabled"
  else
    bad "$chome: hook-carrying plugin(s) not installed: $MISSING — run: make install"
  fi
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

# MCP distribution: ask the emitter, don't compare mtimes. A harness that
# rewrites its own config always wins an mtime race, so "newer" never proved
# "correct" — a real drift (opencode.jsonc missing a whole provider block, but
# still newer than mcp.json) passed silently under the old check.
if [ -f "$STORE/mcp.json" ]; then
  MCPCHECK=$(python3 scripts/port-mcp.py check 2>&1); MCPRC=$?
  [ "$MCPRC" -eq 0 ] && ok "MCP configs match canonical mcp.json" \
    || bad "MCP drift — $MCPCHECK"
fi

# Cursor's generated files (#23): hooks.json is a pure derivation from
# vendored plugins (same "always safe to regenerate" contract as the
# .claude-plugin/.codex-plugin shims), so drift means a plugin got
# vendored/enabled/disabled since the last apply.
if [ -d "$HOME/.cursor" ]; then
  HOOKSCHECK=$(python3 scripts/port-hooks-cursor.py --check 2>&1); HOOKSRC=$?
  [ "$HOOKSRC" -eq 0 ] && ok "cursor hooks.json matches vendored plugins" \
    || bad "cursor hooks.json drift — run: python3 scripts/port-hooks-cursor.py"
  [ -L "$HOME/.cursor/skills" ] && ok "cursor: ~/.cursor/skills linked" \
    || info "cursor: ~/.cursor/skills not linked — run: make sync (only if cursor is a configured target)"
fi

# LiteLLM (on-demand service, so absence is informational)
if [ "$(python3 -c "import json,os;print(json.load(open(os.environ['AGENT_HOME_CONFIG'])).get('litellm',False))" 2>/dev/null)" = "True" ]; then
  if nc -z localhost 4000 2>/dev/null; then ok "LiteLLM responding on :4000"
  else info "LiteLLM parked (legacy workaround; native auth covers all memberships)"; fi
fi

# history freshness — the index should track the newest harness transcript
# within an hour; a bigger lag means `make history` (or the watcher, which
# runs it) has stopped picking up new sessions in some harness.
HIST_LAG=$(python3 - <<'PY' 2>/dev/null
from pathlib import Path
import sync
srcs = []
claude_dirs = {Path.home() / ".claude", Path.home() / ".claude-work"}
claude_dirs |= {Path(a["config_dir"]).expanduser() for a in sync._accounts() if a.get("config_dir")}
for d in claude_dirs:
    srcs += d.glob("projects/*/*.jsonl")
for h in sync.codex_homes():
    srcs += Path(h).glob("sessions/**/*.jsonl")
db = Path.home() / ".local/share/opencode/opencode.db"
if db.exists():
    srcs.append(db)
hist = sync.CANON / "history"
idx = list(hist.rglob("*.md")) if hist.exists() else []
t_src = max((p.stat().st_mtime for p in srcs), default=0)
t_idx = max((p.stat().st_mtime for p in idx), default=0)
print(int(t_src - t_idx) if t_src else -1)
PY
)
if [ "${HIST_LAG:--1}" = "-1" ]; then
  info "history: no harness transcripts found yet"
elif [ "$HIST_LAG" -gt 3600 ]; then
  bad "history index is $((HIST_LAG/60))min behind the newest transcript — run: make history"
else
  ok "history index tracks the newest harness transcript"
fi

# handoff staleness — a handoff written before the most recent indexed
# session is describing state that's already been superseded.
HANDOFF="$STORE/handoff.md"
if [ -f "$HANDOFF" ]; then
  NEWER=$(find "$STORE/history" -name '*.md' -newer "$HANDOFF" 2>/dev/null | head -1)
  [ -z "$NEWER" ] \
    && ok "handoff.md: no newer indexed session" \
    || info "handoff.md predates a newer indexed session (e.g. $NEWER) — may be stale"
else
  info "no handoff.md (written by /handoff)"
fi

# vendored pipeline freshness — the watcher runs from ~/.agent-home/lib (moved
# out of ~/Documents to clear TCC, see #6); a stale copy means an edit to
# sync.py or scripts/ hasn't been re-vendored, so the watcher runs old code.
LIB="$STORE/lib"
if [ ! -d "$LIB" ]; then
  info "~/.agent-home/lib not vendored yet (watcher TCC fix, #6) — nothing to check"
else
  LIBDRIFT=$(python3 - "$LIB" <<'PY' 2>/dev/null
import filecmp, sys
from pathlib import Path
lib, repo = Path(sys.argv[1]), Path(".")
srcs = [repo / "sync.py"] + sorted((repo / "scripts").glob("*"))
drift = []
for s in srcs:
    if not s.is_file():
        continue
    rel = s.relative_to(repo)
    dst = lib / rel
    if not dst.exists() or not filecmp.cmp(s, dst, shallow=False):
        drift.append(str(rel))
print(",".join(drift))
PY
)
  [ -z "$LIBDRIFT" ] \
    && ok "~/.agent-home/lib matches repo sync.py + scripts/" \
    || bad "~/.agent-home/lib stale: $LIBDRIFT — run: make lib"
fi

echo

# -- settings custody (#16) --
python3 "$PWD/scripts/port-settings.py" check >/dev/null 2>&1 \
  && ok "settings capture matches live ~/.claude/settings.json" \
  || info "settings capture stale or absent — next resync heals it (scripts/port-settings.py capture)"

# -- store-ownership acceptance harness (#18): counts derived from the store, no cache links --
OWN=$(python3 - <<PY
import sys, json
sys.path.insert(0, "$PWD")
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location("sync", "$PWD/sync.py")
sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)
home = Path.home()
expect_skills = len(list((sync.CANON/"skills").glob("*"))) + len(sync.enabled_plugin_skill_dirs())
expect_cmds = len(list((sync.CANON/"commands").glob("*.md"))) + len(sync.enabled_plugin_command_files())
links = [p for p in (home/".agents/skills").iterdir() if p.is_symlink()]
cmds  = [p for p in (home/".agents/commands").iterdir() if p.is_symlink()]
cache = [p for p in links+cmds if "plugins/cache" in str(p.resolve())]
outside = [p for p in links+cmds if str(sync.CANON) not in str(p.resolve())]
print(f"{len(links)}/{expect_skills};{len(cmds)}/{expect_cmds};{len(cache)};{len(outside)}")
PY
)
SK=${OWN%%;*}; REST=${OWN#*;}; CM=${REST%%;*}; REST=${REST#*;}; CA=${REST%%;*}; OUT=${REST##*;}
[ "${SK%/*}" = "${SK#*/}" ] && [ "${CM%/*}" = "${CM#*/}" ] \
  && ok "ownership counts: skills $SK, commands $CM (store-derived)" \
  || bad "ownership count mismatch: skills $SK commands $CM — run: python3 sync.py"
[ "$CA" = "0" ] && ok "no symlink resolves into a plugins/cache dir" \
  || bad "$CA symlink(s) resolve into plugins/cache — store does not own them; run: python3 sync.py"
[ "$OUT" = "0" ] && ok "every ~/.agents link resolves inside ~/.agent-home" \
  || bad "$OUT link(s) resolve outside the store"

[ "$FAILS" -eq 0 ] && echo "All healthy." || echo "$FAILS problem(s) — fixes listed above."
exit $((FAILS > 0))
