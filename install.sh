#!/usr/bin/env bash
# agent-home installer — one guided walkthrough to join + merge your harnesses
# and log in every account. The unified store lives in ~/.agent-home (a
# dot-folder, like ~/.claude); THIS REPO holds only the setup code.
#
#   ./install.sh            full interactive walkthrough (merge + wire + logins)
#   ./install.sh --login    just the account login+verify walkthrough
#   ./install.sh --status   show link state, change nothing
#   ./install.sh --yes      non-interactive; reuse config.json, skip logins
set -euo pipefail
cd "$(dirname "$0")"
REPO="$PWD"
STORE="${AGENT_HOME:-$HOME/.agent-home}"

KNOWN=(claude-code claude-code-work opencode codex)
declare -A LABEL=(
  [claude-code]="Claude Code (~/.claude)"
  [claude-code-work]="Claude Code work profile (~/.claude-work)"
  [opencode]="opencode (~/.config/opencode)"
  [codex]="Codex CLI (~/.codex)"
)
detected() { case "$1" in
  claude-code)      [ -d "$HOME/.claude" ];;
  claude-code-work) [ -d "$HOME/.claude-work" ];;
  opencode)         command -v opencode >/dev/null 2>&1 || [ -d "$HOME/.config/opencode" ];;
  codex)            command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ];;
esac; }

ask() { # ask "question" default(y/n); reads the terminal even inside pipes
  local q=$1 def=${2:-y} ans
  read -r -p "$q [$([ "$def" = y ] && echo 'Y/n' || echo 'y/N')] " ans </dev/tty 2>/dev/null || ans=$def
  ans=${ans:-$def}; [[ $ans =~ ^[Yy] ]]; }

cfg() { python3 -c "import json;print(json.load(open('config.json')).get('$1',$2))"; }
has_target() { python3 -c "import json;print('$1' in [k for k,v in json.load(open('config.json'))['harnesses'].items() if v])"; }
accounts_tsv() { python3 -c '
import json, os
try: c = json.load(open("config.json"))
except OSError: c = {}
# "|" delimiter (not IFS-whitespace) so empty fields survive read.
for a in c.get("accounts", c.get("claude_accounts", [])):
    print(a.get("name",""), a.get("provider","anthropic-sub"),
          os.path.expanduser(a.get("config_dir","")), a.get("env_key",""), sep="|")
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
        if command -v codex >/dev/null 2>&1 && codex login status >/dev/null 2>&1; then
          echo "  ✓ $name (chatgpt) — codex logged in"
        else
          echo "  ✗ $name (chatgpt) — not logged in  →  codex login"
          $interactive && ask "      run 'codex login' now?" y && codex login || true
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
  --status) python3 sync.py --status; exit 0;;
  --login)  login_walkthrough; exit 0;;
esac

# ---- config: interactive unless --yes (or no TTY) ----
NONINTERACTIVE=false
if [ "${1:-}" = "--yes" ] || [ ! -t 0 ]; then
  NONINTERACTIVE=true
  [ -f config.json ] || cp config.example.json config.json
  echo "Using existing config.json (non-interactive)."
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
  echo "Step 3/3 — options"
  LITELLM=false; ask "  set up LiteLLM proxy (ChatGPT sub + OpenRouter + local on :4000)?" y && LITELLM=true
  CIO=false
  if printf '%s\n' "${TARGETS[@]}" | grep -qx opencode; then
    echo "  ⚠ Reusing a Claude subscription inside opencode violates Anthropic's ToS"
    echo "    (subscription OAuth is for official clients; bans enforced since 2026)."
    ask "  enable Claude-in-opencode anyway?" n && CIO=true
  fi
  python3 - "$LITELLM" "$CIO" "${SOURCES[*]}" "${TARGETS[*]}" <<'PY'
import json, sys, os
litellm, cio, sources, targets = sys.argv[1]=="true", sys.argv[2]=="true", sys.argv[3].split(), sys.argv[4].split()
known = ["claude-code","claude-code-work","opencode","codex"]
cfg = {}
if os.path.exists("config.json"):
    try: cfg = json.load(open("config.json"))
    except Exception: cfg = {}
cfg["harnesses"] = {h: (h in targets) for h in known}
cfg["adopt_from"] = sources
cfg["litellm"] = litellm
cfg["claude_in_opencode"] = cio
cfg.setdefault("accounts", json.load(open("config.example.json"))["accounts"])
json.dump(cfg, open("config.json","w"), indent=2)
print("\n→ wrote config.json (edit 'accounts' to add/remove logins)")
PY
fi

echo
echo "== 1. Unified store → harnesses (merge + symlink) =="
[ -f "$STORE/AGENTS.md" ] || { mkdir -p "$STORE"; cp templates/AGENTS.example.md "$STORE/AGENTS.md"; }
mkdir -p "$STORE"/{skills,agents,commands,memory}
python3 sync.py --adopt

if [ "$(cfg litellm False)" = "True" ]; then
  echo "== 2. LiteLLM =="
  command -v litellm >/dev/null 2>&1 || { command -v uv >/dev/null 2>&1 && uv tool install 'litellm[proxy]' || echo "  ! install uv or 'pip install litellm[proxy]'"; }
  echo "  config: $REPO/litellm/config.yaml   (start with 'make litellm')"
fi

if [ "$(has_target codex)" = "True" ]; then
  echo "== 3. Codex CLI =="
  command -v codex >/dev/null 2>&1 || { command -v npm >/dev/null 2>&1 && npm install -g @openai/codex || echo "  ! npm i -g @openai/codex"; }
  [ -f "$HOME/.codex/config.toml" ] || { mkdir -p "$HOME/.codex"; cp templates/codex.config.toml "$HOME/.codex/config.toml"; echo "  wrote ~/.codex/config.toml"; }
fi

if [ "$(has_target opencode)" = "True" ]; then
  echo "== 4. opencode =="
  DST="$HOME/.config/opencode/opencode.jsonc"; mkdir -p "$(dirname "$DST")"
  { echo '{'; echo '  "$schema": "https://opencode.ai/config.json",'
    [ "$(cfg claude_in_opencode False)" = "True" ] && echo '  "plugin": ["opencode-claude-auth@latest"],'
    cat templates/opencode.provider.jsonc; echo '}'; } > "$DST"
  echo "  wrote $DST"
fi

echo
if [ "$NONINTERACTIVE" = true ]; then
  echo "Merged + wired. Log in accounts with:  make login   (or ./install.sh --login)"
else
  login_walkthrough
  echo
  echo "All set. Re-verify any account anytime:  make verify ACCOUNT=<name>"
fi
