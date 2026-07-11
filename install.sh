#!/usr/bin/env bash
# agent-home installer — one command to make skills/memory/instructions and your
# memberships portable across Claude Code, opencode, and Codex CLI.
#
#   ./install.sh          set up everything enabled in config.json
#   ./install.sh --status show link state, don't change anything
#
# Idempotent. Reads config.json (copied from config.example.json on first run).
set -euo pipefail
cd "$(dirname "$0")"
REPO="$PWD"

jq_get() { python3 -c "import json,sys; d=json.load(open('config.json')); print(json.dumps(d$1))" 2>/dev/null; }
enabled() { [ "$(jq_get "$1")" = "true" ]; }

if [ "${1:-}" = "--status" ]; then
  python3 sync.py --status
  exit 0
fi

# 0. Config
[ -f config.json ] || { cp config.example.json config.json; echo "→ created config.json (edit to taste, re-run)"; }

echo "== 1. Canonical store → harness config (symlinks) =="
# Starter instructions if the user has none (real content is gitignored).
[ -f canonical/AGENTS.md ] || cp canonical/AGENTS.example.md canonical/AGENTS.md
mkdir -p canonical/skills canonical/agents canonical/commands canonical/memory
# --adopt is safe on re-run: it only moves REAL files in, never clobbers links.
python3 sync.py --adopt

# 2. LiteLLM proxy (ChatGPT subscription + OpenRouter + local, one endpoint)
if enabled "['litellm']"; then
  echo "== 2. LiteLLM =="
  if ! command -v litellm >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then uv tool install 'litellm[proxy]'
    else echo "  ! install uv (https://astral.sh/uv) or 'pip install litellm[proxy]', then re-run"; fi
  fi
  echo "  config: $REPO/litellm/config.yaml"
  echo "  start:  litellm --config $REPO/litellm/config.yaml   (device-code login on first chatgpt/* call)"
fi

# 3. Codex CLI (official ChatGPT sign-in; can also point at LiteLLM/OpenRouter/local)
if enabled "['harnesses']['codex']"; then
  echo "== 3. Codex CLI =="
  command -v codex >/dev/null 2>&1 || { command -v npm >/dev/null 2>&1 && npm install -g @openai/codex || echo "  ! install Node/npm, then: npm i -g @openai/codex"; }
  # config.toml is user-authored; only scaffold if absent (don't stomp edits).
  if [ ! -f "$HOME/.codex/config.toml" ]; then
    mkdir -p "$HOME/.codex"
    cp templates/codex.config.toml "$HOME/.codex/config.toml"
    echo "  wrote ~/.codex/config.toml"
  fi
  echo "  login:  codex login   (browser, ChatGPT account — plan-based, no API credits)"
fi

# 4. opencode (portable skills/memory already linked above; wire providers)
if enabled "['harnesses']['opencode']"; then
  echo "== 4. opencode =="
  DST="$HOME/.config/opencode/opencode.jsonc"
  mkdir -p "$(dirname "$DST")"
  CLAUDE_PLUGIN=""
  if enabled "['claude_in_opencode']"; then
    CLAUDE_PLUGIN='  "plugin": ["opencode-claude-auth@latest"],'
    echo "  ⚠ claude_in_opencode=true: reusing your Claude subscription in opencode."
    echo "    Anthropic ToS restricts subscription OAuth to official clients (ban risk since 2026)."
  fi
  # Generate provider config (LiteLLM endpoint always; Claude plugin iff opted in).
  { echo '{'
    echo '  "$schema": "https://opencode.ai/config.json",'
    [ -n "$CLAUDE_PLUGIN" ] && echo "$CLAUDE_PLUGIN"
    cat templates/opencode.provider.jsonc
    echo '}'
  } > "$DST"
  echo "  wrote $DST"
fi

echo
echo "== Done. Interactive logins left for you (run in your terminal): =="
enabled "['harnesses']['codex']"     && echo "  codex login"
enabled "['litellm']"                && echo "  litellm --config $REPO/litellm/config.yaml   # then complete device-code URL"
echo
echo "Verify Claude membership (no API credits):  ./scripts/verify-claude-membership.sh"
