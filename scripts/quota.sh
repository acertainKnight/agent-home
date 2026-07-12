#!/usr/bin/env bash
# Show every account's usage/quota side by side, so you know which account has
# headroom before a big session. Per provider:
#   anthropic-sub  one 1-token request → unified 5h/7d membership pools
#   chatgpt-sub    latest rate-limit snapshot Codex saved in its session logs
#                  (local read, no request; empty until you've used codex once)
#   openai-key     OpenRouter credits endpoint (skipped for other base_urls)
# Tokens/keys are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
export AGENT_HOME_CONFIG="$STORE/config.json"
# shared env (OPENROUTER_API_KEY etc.) — same file every harness sources
[ -f "$STORE/env" ] && { set -a; . "$STORE/env"; set +a; }

while IFS='|' read -r name provider cdir envkey baseurl; do
  [ -z "$name" ] && continue
  echo "== $name ($provider) =="
  case "$provider" in

    anthropic-sub)
      if ! TOKEN=$(./scripts/claude-token.sh "$name" 2>/dev/null); then
        echo "  (not logged in — make login)"; continue
      fi
      curl -sS -D - -o /dev/null https://api.anthropic.com/v1/messages \
        -H "authorization: Bearer $TOKEN" \
        -H "anthropic-version: 2023-06-01" \
        -H "anthropic-beta: oauth-2025-04-20" \
        -H "content-type: application/json" \
        -d '{"model":"claude-haiku-4-5-20251001","max_tokens":1,"system":"You are Claude Code, Anthropic'\''s official CLI for Claude.","messages":[{"role":"user","content":"hi"}]}' \
        | grep -i '^anthropic-ratelimit-unified' | sed 's/^/  /' \
        || echo "  (request failed — token may need refresh: make login)" ;;

    chatgpt-sub)
      # Codex writes a rate_limits snapshot into each session rollout; read the
      # newest one instead of spending a request. Format is best-effort.
      python3 - "${cdir:-$HOME/.codex}" <<'PY'
import json, sys, time
from pathlib import Path
home = Path(sys.argv[1]).expanduser()
files = sorted(home.glob("sessions/**/*.jsonl"), key=lambda p: p.stat().st_mtime)
snap = stamp = None
for f in reversed(files[-5:]):           # newest few files, newest line wins
    for line in reversed(f.read_text(errors="replace").splitlines()):
        if '"rate_limits"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else rec
        rl = payload.get("rate_limits")
        if isinstance(rl, dict):
            snap, stamp = rl, rec.get("timestamp")
            break
    if snap:
        break
if not snap:
    print("  (no usage snapshot yet — appears after your first codex session)")
    sys.exit(0)
print(f"  as of {stamp or 'last session'}:")
for label, w in snap.items():
    if isinstance(w, dict) and "used_percent" in w:
        mins = w.get("window_minutes")
        win = f"{mins/60:.0f}h window" if mins else label
        reset = w.get("resets_in_seconds")
        reset = f", resets in {reset/3600:.1f}h" if reset else ""
        print(f"  {label} ({win}): {w['used_percent']:.0f}% used{reset}")
PY
      ;;

    openai-key)
      case "$baseurl" in *openrouter*) ;; *) echo "  (no quota endpoint wired for $baseurl)"; continue;; esac
      val=""; [ -n "$envkey" ] && eval "val=\"\${$envkey:-}\""
      [ -n "$val" ] || { echo "  (\$$envkey unset — add it to $STORE/env)"; continue; }
      curl -sS https://openrouter.ai/api/v1/credits -H "Authorization: Bearer $val" \
        | python3 -c '
import json, sys
d = json.load(sys.stdin).get("data") or {}
if not d: sys.exit("  (credits request failed — key invalid?)")
tc, tu = d.get("total_credits", 0), d.get("total_usage", 0)
print(f"  credits: ${tc:.2f} bought, ${tu:.2f} spent, ${tc-tu:.2f} remaining")' \
        || true ;;

    *) echo "  (unknown provider)";;
  esac
done < <(python3 -c '
import json, os
try: c = json.load(open(os.environ["AGENT_HOME_CONFIG"]))
except OSError: c = {}
for a in c.get("accounts", c.get("claude_accounts", [])):
    d = a.get("config_dir") or a.get("codex_home") or ""
    print(a.get("name",""), a.get("provider","anthropic-sub"),
          os.path.expanduser(d), a.get("env_key",""), a.get("base_url",""), sep="|")
')
