#!/usr/bin/env bash
# agent-home installer — one guided walkthrough to join + merge your harnesses
# and log in every account. The unified store lives in ~/.agent-home (a
# dot-folder, like ~/.claude); THIS REPO holds only the setup code.
#
#   ./install.sh            full interactive walkthrough (merge + wire + logins)
#   ./install.sh --login    just the account login+verify walkthrough
#   ./install.sh --status   show link state, change nothing
#   ./install.sh --watcher  install/refresh the auto-resync watcher only
#   ./install.sh --yes      non-interactive; reuse config.json, skip logins
set -euo pipefail
cd "$(dirname "$0")"
REPO="$PWD"
STORE="${AGENT_HOME:-$HOME/.agent-home}"
CONFIG="$STORE/config.json"          # per-user config lives IN the store, not the repo
export AGENT_HOME_CONFIG="$CONFIG"   # read by the inline python blocks below

KNOWN=(claude-code claude-code-work opencode codex cursor)
declare -A LABEL=(
  [claude-code]="Claude Code (~/.claude)"
  [claude-code-work]="Claude Code work profile (~/.claude-work)"
  [opencode]="opencode (~/.config/opencode)"
  [codex]="Codex CLI (~/.codex)"
  [cursor]="Cursor (cursor-agent CLI + Cursor.app, ~/.cursor)"
)
detected() { case "$1" in
  claude-code)      [ -d "$HOME/.claude" ];;
  claude-code-work) [ -d "$HOME/.claude-work" ];;
  opencode)         command -v opencode >/dev/null 2>&1 || [ -d "$HOME/.config/opencode" ];;
  codex)            command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ];;
  cursor)           command -v cursor-agent >/dev/null 2>&1 || [ -d "$HOME/.cursor" ];;
esac; }

ask() { # ask "question" default(y/n); reads the terminal even inside pipes
  local q=$1 def=${2:-y} ans
  read -r -p "$q [$([ "$def" = y ] && echo 'Y/n' || echo 'y/N')] " ans </dev/tty 2>/dev/null || ans=$def
  ans=${ans:-$def}; [[ $ans =~ ^[Yy] ]]; }

cfg() { python3 -c "import json,os;print(json.load(open(os.environ['AGENT_HOME_CONFIG'])).get('$1',$2))"; }
has_target() { python3 -c "import json,os;print('$1' in [k for k,v in json.load(open(os.environ['AGENT_HOME_CONFIG']))['harnesses'].items() if v])"; }
accounts_tsv() { python3 -c '
import json, os
try: c = json.load(open(os.environ["AGENT_HOME_CONFIG"]))
except OSError: c = {}
# "|" delimiter (not IFS-whitespace) so empty fields survive read.
# dir = the accounts config dir: CLAUDE_CONFIG_DIR (claude) or CODEX_HOME (codex).
for a in c.get("accounts", c.get("claude_accounts", [])):
    d = a.get("config_dir") or a.get("codex_home") or ""
    print(a.get("name",""), a.get("provider","anthropic-sub"),
          os.path.expanduser(d), a.get("env_key",""), sep="|")
'; }

login_walkthrough() {
  echo "== Accounts — log in & verify =="
  local interactive=false; [ -t 0 ] && interactive=true
  mapfile -t ACCTS < <(accounts_tsv)
  [ ${#ACCTS[@]} -eq 0 ] && { echo "  (no accounts in config.json)"; return; }
  for line in "${ACCTS[@]}"; do
    [ -z "$line" ] && continue
    IFS='|' read -r name provider cdir envkey <<<"$line"
    case "$provider" in
      anthropic-sub)
        if ./scripts/claude-token.sh "$name" >/dev/null 2>&1; then
          echo "  ✓ $name (claude) — logged in"
        else
          echo "  ✗ $name (claude) — not logged in  →  CLAUDE_CONFIG_DIR=$cdir claude auth login"
          $interactive && ask "      log in now?" y && CLAUDE_CONFIG_DIR="$cdir" claude auth login || true
        fi ;;
      chatgpt-sub)
        home="${cdir:-$HOME/.codex}"
        if command -v codex >/dev/null 2>&1 && CODEX_HOME="$home" codex login status >/dev/null 2>&1; then
          echo "  ✓ $name (chatgpt) — logged in (CODEX_HOME=$home)"
        else
          echo "  ✗ $name (chatgpt) — not logged in  →  CODEX_HOME=$home codex login"
          $interactive && ask "      run 'codex login' for $name now?" y && CODEX_HOME="$home" codex login || true
        fi ;;
      openai-key)
        val=""; [ -n "$envkey" ] && eval "val=\"\${$envkey:-}\""  # bash 3.2-safe indirect
        if [ -n "$val" ]; then echo "  ✓ $name (key) — \$$envkey is set"
        else echo "  ✗ $name (key) — export $envkey=… to use"; fi ;;
      *) echo "  ? $name — unknown provider '$provider'";;
    esac
  done
  echo "  — membership proof (no API credits) —"
  for line in "${ACCTS[@]}"; do
    IFS='|' read -r name provider _ _ <<<"$line"
    [ "$provider" = anthropic-sub ] || continue
    if ./scripts/claude-token.sh "$name" >/dev/null 2>&1; then
      ./scripts/verify-claude-membership.sh "$name" >/dev/null 2>&1 \
        && echo "  ✓ $name on membership (sk-ant-oat, unified rate-limit pool)" \
        || echo "  ! $name token present but request failed"
    fi
  done
}

case "${1:-}" in
  --status)  python3 sync.py --status; exit 0;;
  --login)   login_walkthrough; exit 0;;
  --watcher) ./scripts/install-watcher.sh; exit 0;;
esac

# ---- config: interactive unless --yes (or no TTY) ----
NONINTERACTIVE=false
if [ "${1:-}" = "--yes" ] || [ ! -t 0 ]; then
  NONINTERACTIVE=true
  if [ ! -f "$CONFIG" ]; then
    mkdir -p "$STORE"
    # Bootstrap from THIS machine: detected harnesses + auto-detected Claude
    # accounts (never the checked-in example's accounts).
    python3 - <<'PY'
import json, os, subprocess, sys
from pathlib import Path
H = Path.home()
harnesses = {
  "claude-code": (H/".claude").is_dir(),
  "claude-code-work": (H/".claude-work").is_dir(),
  "opencode": bool(__import__("shutil").which("opencode")) or (H/".config/opencode").is_dir(),
  "codex": bool(__import__("shutil").which("codex")) or (H/".codex").is_dir(),
  "cursor": bool(__import__("shutil").which("cursor-agent")) or (H/".cursor").is_dir(),
}
accounts = json.loads(subprocess.check_output([sys.executable, "scripts/detect-accounts.py"]))["accounts"]
json.dump({
  "harnesses": harnesses,
  "adopt_from": [h for h,on in harnesses.items() if on],
  "accounts": accounts,
  "litellm": False,
  "claude_in_opencode": False,
}, open(os.environ["AGENT_HOME_CONFIG"],"w"), indent=2)
print(f"→ bootstrapped {os.environ['AGENT_HOME_CONFIG']} ({sum(harnesses.values())} harnesses, {len(accounts)} accounts)")
PY
  fi
  echo "Using config.json (non-interactive)."
else
  echo "== agent-home setup =="
  echo "Store (content lives here): $STORE"
  echo "Detected: $(for h in "${KNOWN[@]}"; do detected "$h" && printf '%s ' "$h"; done)"
  echo
  echo "Step 1/3 — which harnesses do you CURRENTLY use?"
  echo "  (merge their existing skills/memory/instructions/commands into the store)"
  SOURCES=(); for h in "${KNOWN[@]}"; do
    detected "$h" || continue
    ask "  import from ${LABEL[$h]}?" y && SOURCES+=("$h"); done
  echo
  echo "Step 2/3 — which harnesses to SET UP? (link the shared store into them)"
  echo "  (sources above are always set up; pick extra harnesses to migrate TO)"
  TARGETS=("${SOURCES[@]}"); for h in "${KNOWN[@]}"; do
    printf '%s\n' "${TARGETS[@]}" | grep -qx "$h" && continue
    ask "  set up ${LABEL[$h]}?" "$(detected "$h" && echo y || echo n)" && TARGETS+=("$h"); done
  echo
  echo "Step 3/4 — accounts (each becomes a login you can switch to in any harness)"
  # spec line = name|provider|dir|keychain|env_key|base_url|port
  #   anthropic-sub: dir=CLAUDE_CONFIG_DIR, keychain   chatgpt-sub: dir=CODEX_HOME
  #   openai-key: env_key, base_url   (chatgpt ports are auto-numbered by the writer)
  ACCT_SPECS=()
  # 1) Find every account on this machine (any ~/.claude* / ~/.codex*) and suggest each.
  mapfile -t FOUND < <(python3 scripts/detect-accounts.py --specs)
  if [ ${#FOUND[@]} -gt 0 ]; then
    echo "  found ${#FOUND[@]} account(s) on this machine:"
    for spec in "${FOUND[@]}"; do
      [ -z "$spec" ] && continue
      IFS='|' read -r fname fprov fdir _ <<<"$spec"
      ask "    connect $fprov account '$fname' ($fdir)?" y && ACCT_SPECS+=("$spec")
    done
  else
    echo "  (no existing accounts detected)"
  fi
  # 2) Add any accounts that weren't found.
  while ask "  add another Claude account (a CLAUDE_CONFIG_DIR)?" n; do
    read -r -p "      name (e.g. claude-side): " nm </dev/tty
    read -r -p "      its CLAUDE_CONFIG_DIR (e.g. ~/.claude-side): " cd </dev/tty
    [ -n "$nm" ] && [ -n "$cd" ] && ACCT_SPECS+=("$nm|anthropic-sub|$cd||||")
  done
  while ask "  add another ChatGPT/Codex account (a CODEX_HOME)?" n; do
    read -r -p "      name (e.g. chatgpt-work): " nm </dev/tty
    read -r -p "      its CODEX_HOME (e.g. ~/.codex-work): " cd </dev/tty
    [ -n "$nm" ] && [ -n "$cd" ] && ACCT_SPECS+=("$nm|chatgpt-sub|$cd||||")
  done
  ask "  add OpenRouter (OpenAI-compatible API key)?" n \
    && ACCT_SPECS+=("openrouter|openai-key|||OPENROUTER_API_KEY|https://openrouter.ai/api/v1|")
  echo
  echo "Step 4/4 — options"
  LITELLM=false; ask "  set up LiteLLM proxy too (OPTIONAL — opencode/codex already get ChatGPT sub + OpenRouter natively)?" n && LITELLM=true
  CIO=false
  if printf '%s\n' "${TARGETS[@]}" | grep -qx opencode; then
    echo "  ⚠ Reusing a Claude subscription inside opencode violates Anthropic's ToS"
    echo "    (subscription OAuth is for official clients; bans enforced since 2026)."
    ask "  enable Claude-in-opencode anyway?" n && CIO=true
  fi
  printf '%s\n' "${ACCT_SPECS[@]}" | python3 - "$LITELLM" "$CIO" "${SOURCES[*]}" "${TARGETS[*]}" <<'PY'
import json, sys, os
litellm, cio, sources, targets = sys.argv[1]=="true", sys.argv[2]=="true", sys.argv[3].split(), sys.argv[4].split()
known = ["claude-code","claude-code-work","opencode","codex","cursor"]
accounts = []
for line in sys.stdin.read().splitlines():
    if not line.strip():
        continue
    name, prov, dir_, keychain, envkey, baseurl, port = (line.split("|") + [""]*7)[:7]
    a = {"name": name, "provider": prov}
    if prov == "anthropic-sub":
        a["config_dir"] = dir_; a["keychain"] = keychain or None
    elif prov == "chatgpt-sub":
        a["codex_home"] = dir_  # port assigned below
    elif prov == "openai-key":
        a["env_key"] = envkey; a["base_url"] = baseurl
    accounts.append(a)
# Auto-number each Codex account's LiteLLM port (4001, 4002, …).
for i, a in enumerate(x for x in accounts if x["provider"] == "chatgpt-sub"):
    a["port"] = 4001 + i
cfg = {}
if os.path.exists(os.environ["AGENT_HOME_CONFIG"]):
    try: cfg = json.load(open(os.environ["AGENT_HOME_CONFIG"]))
    except Exception: cfg = {}
cfg["harnesses"] = {h: (h in targets) for h in known}
cfg["adopt_from"] = sources
if not accounts:  # user skipped all prompts → auto-detect this machine's Claude accounts
    import subprocess
    accounts = json.loads(subprocess.check_output([sys.executable, "scripts/detect-accounts.py"]))["accounts"]
cfg["accounts"] = accounts
cfg["litellm"] = litellm
cfg["claude_in_opencode"] = cio
os.makedirs(os.path.dirname(os.environ["AGENT_HOME_CONFIG"]), exist_ok=True)
json.dump(cfg, open(os.environ["AGENT_HOME_CONFIG"],"w"), indent=2)
print(f"\n→ wrote {os.environ['AGENT_HOME_CONFIG']} ({len(cfg['accounts'])} accounts; edit anytime)")
PY
fi

echo
echo "== 1. Unified store → harnesses (merge + symlink) =="
[ -f "$STORE/AGENTS.md" ] || { mkdir -p "$STORE"; cp templates/AGENTS.example.md "$STORE/AGENTS.md"; }
mkdir -p "$STORE"/{skills,agents,commands,memory,workflows}
python3 sync.py --adopt

if [ "$(cfg litellm False)" = "True" ]; then
  echo "== 2. LiteLLM (optional, parked — not the default model path) =="
  command -v litellm >/dev/null 2>&1 || { command -v uv >/dev/null 2>&1 && uv tool install 'litellm[proxy]' || echo "  ! install uv or 'pip install litellm[proxy]'"; }
  echo "  config: $REPO/litellm/config.yaml   (start with 'make litellm')"
fi

if [ "$(has_target codex)" = "True" ]; then
  echo "== 3. Codex CLI =="
  command -v codex >/dev/null 2>&1 || { command -v npm >/dev/null 2>&1 && npm install -g @openai/codex || echo "  ! npm i -g @openai/codex"; }
  # One config.toml per CODEX_HOME (one per ChatGPT/Codex account).
  for home in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))"); do
    [ -f "$home/config.toml" ] || { mkdir -p "$home"; cp templates/codex.config.toml "$home/config.toml"; echo "  wrote $home/config.toml"; }
  done
  # Store marketplace + every enabled plugin — both `codex plugin marketplace
  # add` and `codex plugin add` no-op cleanly on a repeat run, so this is safe
  # to run every install. This does NOT grant hook trust (a separate,
  # interactive first-run walk per hook-carrying plugin — see README's Hooks
  # row and "Manual steps" in #19's PR); an installed-but-untrusted hook never
  # fires, silently.
  if command -v codex >/dev/null 2>&1 && [ -d "$STORE/plugins" ]; then
    for home in $(python3 -c "import sync; print(' '.join(sync.codex_homes()))"); do
      CODEX_HOME="$home" codex plugin marketplace add "$STORE/plugins" >/dev/null 2>&1
      n=0
      for name in $(python3 -c "
import json
try: enabled = json.load(open('$STORE/plugins/enabled.json'))
except OSError: enabled = {}
print(' '.join(sorted(k for k, v in enabled.items() if v)))
"); do
        CODEX_HOME="$home" codex plugin add "$name@agent-home" >/dev/null 2>&1 && n=$((n+1))
      done
      echo "  $home: agent-home marketplace added, $n plugin(s) installed"
    done
  fi
fi

if [ "$(has_target opencode)" = "True" ]; then
  echo "== 4. opencode =="
  # Non-breaking: merges our provider (+ optional plugin) into any existing config.
  python3 scripts/wire-opencode.py "$(cfg claude_in_opencode False | tr '[:upper:]' '[:lower:]')"
fi

if [ "$(has_target cursor)" = "True" ]; then
  echo "== 5. Cursor =="
  command -v cursor-agent >/dev/null 2>&1 || { command -v brew >/dev/null 2>&1 && brew install --cask cursor-cli || echo "  ! install cursor-agent: https://cursor.com/cli"; }
  command -v cursor-agent >/dev/null 2>&1 && ! cursor-agent status >/dev/null 2>&1 && echo "  · not logged in — run: cursor-agent login"
fi

# 6. MCP servers — the portable core of "plugins". Pull every MCP Claude Code
# knows (user + enabled plugins) into the store, then distribute to each harness.
echo "== 6. MCP servers (plugins → portable) =="
python3 scripts/port-mcp.py adopt
python3 scripts/port-mcp.py apply
[ "$(has_target cursor)" = "True" ] && python3 scripts/port-hooks-cursor.py

echo "== 7. Seamless-switching extras =="
# Starter store content — only created if absent (store content is the user's).
[ -f "$STORE/commands/handoff.md" ] || { cp templates/commands/handoff.md "$STORE/commands/handoff.md"; echo "  + /handoff command (session handoff, works in every harness)"; }
[ -f "$STORE/models.json" ] || { cp templates/models.example.json "$STORE/models.json"; echo "  + models.json (edit to map model aliases per harness)"; }
[ -f "$STORE/env" ] || { cp templates/env.example "$STORE/env"; chmod 600 "$STORE/env"; echo "  + env (shared secrets/env for MCPs — add keys there)"; }
# AGENTS.md bridge blocks (handoff/models/history) — idempotent append.
python3 - <<'PY'
import os, re
path = os.path.join(os.path.dirname(os.environ["AGENT_HOME_CONFIG"]), "AGENTS.md")
tmpl = open("templates/AGENTS.example.md").read()
have = open(path).read() if os.path.exists(path) else ""
for m in re.finditer(r"^## .+?(?=^## |\Z)", tmpl, re.M | re.S):
    block = m.group(0)
    header = block.splitlines()[0]
    if header not in have:
        have = have.rstrip() + "\n\n" + block.strip() + "\n"
        print(f"  + AGENTS.md: appended '{header}'")
open(path, "w").write(have)
PY
# Shared env → every shell (so MCP secrets resolve in every harness).
ZLINE='[ -f "$HOME/.agent-home/env" ] && { set -a; . "$HOME/.agent-home/env"; set +a; }  # agent-home shared env'
if ! grep -qs 'agent-home shared env' "$HOME/.zshenv" 2>/dev/null; then
  if [ "$NONINTERACTIVE" = true ]; then
    echo "  · to share env across harnesses, add to ~/.zshenv:  $ZLINE"
  elif ask "  source $STORE/env from ~/.zshenv (every harness sees the same secrets)?" y; then
    printf '%s\n' "$ZLINE" >> "$HOME/.zshenv"; echo "  + ~/.zshenv sources the shared env"
  fi
fi
# opencode gets translated copies of your Claude subagents.
[ "$(has_target opencode)" = "True" ] && python3 scripts/port-agents.py
# Cross-harness history index (incremental; makes past sessions searchable everywhere).
python3 scripts/history.py || echo "  ! history indexing failed (non-fatal)"
# Auto-resync watcher (macOS launchd) — optional.
if [ "$NONINTERACTIVE" = false ] && [ "$(uname)" = "Darwin" ] && [ ! -f "$HOME/Library/LaunchAgents/com.agent-home.sync.plist" ]; then
  ask "  install auto-resync watcher (re-runs sync when plugins/skills change)?" n && ./scripts/install-watcher.sh
fi

echo
if [ "$NONINTERACTIVE" = true ]; then
  echo "Merged + wired. Log in accounts with:  make login   (or ./install.sh --login)"
else
  login_walkthrough
  echo
  echo "All set. Re-verify any account anytime:  make verify ACCOUNT=<name>"
fi
