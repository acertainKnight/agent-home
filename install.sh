#!/usr/bin/env bash
# agent-home installer — make skills/memory/instructions and your paid
# memberships portable across Claude Code, opencode, and Codex CLI.
#
# The unified store lives in ~/.agent-home (a dot-folder, like ~/.claude).
# THIS REPO holds only the setup code. Content stays in ~/.agent-home.
#
#   ./install.sh            interactive setup (asks which harnesses)
#   ./install.sh --status   show link state, change nothing
#   ./install.sh --yes      non-interactive; reuse existing config.json
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

ask() { # ask "question" default(y/n) -> returns 0 for yes
  local q=$1 def=${2:-y} ans
  read -r -p "$q [$([ "$def" = y ] && echo 'Y/n' || echo 'y/N')] " ans || true
  ans=${ans:-$def}; [[ $ans =~ ^[Yy] ]]; }

if [ "${1:-}" = "--status" ]; then python3 sync.py --status; exit 0; fi

# ---- config: interactive unless --yes (or no TTY) with an existing config.json ----
if [ "${1:-}" = "--yes" ] || [ ! -t 0 ]; then
  [ -f config.json ] || cp config.example.json config.json
  echo "Using existing config.json (non-interactive)."
else
  echo "== agent-home setup =="
  echo "Store (content lives here): $STORE"
  echo "Detected: $(for h in "${KNOWN[@]}"; do detected "$h" && printf '%s ' "$h"; done)"
  echo
  echo "Step 1/3 — which harnesses do you CURRENTLY use?"
  echo "  (import their existing skills/memory/instructions into the shared store)"
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
    echo "  ⚠ Reusing your Claude subscription inside opencode violates Anthropic's ToS"
    echo "    (subscription OAuth is for official clients; bans enforced since 2026)."
    ask "  enable Claude-in-opencode anyway?" n && CIO=true
  fi
  # write config.json
  python3 - "$LITELLM" "$CIO" "${SOURCES[*]}" "${TARGETS[*]}" <<'PY'
import json, sys
litellm, cio, sources, targets = sys.argv[1]=="true", sys.argv[2]=="true", sys.argv[3].split(), sys.argv[4].split()
known = ["claude-code","claude-code-work","opencode","codex"]
json.dump({
  "harnesses": {h: (h in targets) for h in known},
  "adopt_from": sources,
  "litellm": litellm,
  "claude_in_opencode": cio,
}, open("config.json","w"), indent=2)
print("\n→ wrote config.json")
PY
fi

get() { python3 -c "import json;print(json.load(open('config.json')).get('$1',$2))"; }
has_target() { python3 -c "import json;print('$1' in [k for k,v in json.load(open('config.json'))['harnesses'].items() if v])"; }

echo
echo "== 1. Unified store → harnesses (symlinks) =="
[ -f "$STORE/AGENTS.md" ] || { mkdir -p "$STORE"; cp templates/AGENTS.example.md "$STORE/AGENTS.md"; }
mkdir -p "$STORE"/{skills,agents,commands,memory}
python3 sync.py --adopt

if [ "$(get litellm False)" = "True" ]; then
  echo "== 2. LiteLLM =="
  command -v litellm >/dev/null 2>&1 || { command -v uv >/dev/null 2>&1 && uv tool install 'litellm[proxy]' || echo "  ! install uv or 'pip install litellm[proxy]'"; }
  echo "  start:  litellm --config $REPO/litellm/config.yaml   (device-code login on first chatgpt/* call)"
fi

if [ "$(has_target codex)" = "True" ]; then
  echo "== 3. Codex CLI =="
  command -v codex >/dev/null 2>&1 || { command -v npm >/dev/null 2>&1 && npm install -g @openai/codex || echo "  ! npm i -g @openai/codex"; }
  [ -f "$HOME/.codex/config.toml" ] || { mkdir -p "$HOME/.codex"; cp templates/codex.config.toml "$HOME/.codex/config.toml"; echo "  wrote ~/.codex/config.toml"; }
  echo "  login:  codex login   (ChatGPT account — plan-based, no API credits)"
fi

if [ "$(has_target opencode)" = "True" ]; then
  echo "== 4. opencode =="
  DST="$HOME/.config/opencode/opencode.jsonc"; mkdir -p "$(dirname "$DST")"
  { echo '{'; echo '  "$schema": "https://opencode.ai/config.json",'
    [ "$(get claude_in_opencode False)" = "True" ] && echo '  "plugin": ["opencode-claude-auth@latest"],'
    cat templates/opencode.provider.jsonc; echo '}'; } > "$DST"
  echo "  wrote $DST"
fi

echo
echo "== Done. Interactive logins to run yourself: =="
[ "$(has_target codex)" = "True" ] && echo "  codex login"
[ "$(get litellm False)" = "True" ] && echo "  litellm --config $REPO/litellm/config.yaml"
echo "Verify Claude runs on your membership (not API credits):  ./scripts/verify-claude-membership.sh"
