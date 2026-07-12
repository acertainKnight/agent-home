# agent-home — `just install` runs the full guided setup walkthrough.
default:
    @just --list

# full walkthrough: pick harnesses, merge, wire, log in accounts
install:
    ./install.sh

# log in & verify every account in config.json
login:
    ./install.sh --login

# re-merge the store into all harnesses (after adding a skill/plugin)
sync:
    python3 sync.py --adopt

# pull all MCP servers into the store, distribute to opencode + codex
mcp:
    python3 scripts/port-mcp.py adopt && python3 scripts/port-mcp.py apply && python3 scripts/port-mcp.py list

# show every symlink's state
status:
    ./install.sh --status

# prove an account runs on membership, not API credits
verify account="personal":
    ./scripts/verify-claude-membership.sh {{account}}

# run the merge-engine self-check
test:
    python3 test_merge.py

# start the LiteLLM router (:4000) — device-code login on first use
litellm:
    litellm --config litellm/config.yaml

# health-check everything: links, tokens, MCP freshness, env wiring
doctor:
    ./scripts/doctor.sh

# every account's headroom (Claude pools, Codex usage, OpenRouter credits)
quota:
    ./scripts/quota.sh

# index all harness transcripts into ~/.agent-home/history
history:
    python3 scripts/history.py

# search the indexed cross-harness history
search q:
    python3 scripts/history.py search "{{q}}"

# regenerate opencode agents from ~/.agent-home/agents
agents:
    python3 scripts/port-agents.py

# install the auto-resync watcher (launchd; re-runs sync on changes)
watcher:
    ./scripts/install-watcher.sh
