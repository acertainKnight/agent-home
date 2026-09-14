# agent-home — `make install` runs the full guided setup walkthrough.
ACCOUNT ?= personal
.PHONY: help install login sync lib status verify test litellm mcp doctor quota history agents watcher plugins plugins-refresh
.DEFAULT_GOAL := help

help:  ## show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t20

install:  ## full walkthrough: pick harnesses, merge, wire, log in accounts
	@./install.sh

login:  ## log in & verify every account in config.json
	@./install.sh --login

sync: lib  ## re-merge the store into all harnesses (after adding a skill/plugin)
	@python3 sync.py --adopt

lib:  ## vendor sync.py + scripts/ into the store (outside TCC's ~/Documents block, for the watcher)
	@./scripts/vendor-lib.sh

resync:  ## everything: sync + mcp + agents + history + codex distill (what the watcher runs)
	@./scripts/resync.sh

mcp:  ## pull all MCP servers into the store, distribute to opencode + codex
	@python3 scripts/port-mcp.py adopt && python3 scripts/port-mcp.py apply && python3 scripts/port-mcp.py list

status:  ## show every symlink's state
	@./install.sh --status

verify:  ## prove an account runs on membership, not API credits (ACCOUNT=name)
	@./scripts/verify-claude-membership.sh $(ACCOUNT)

test-ownership:  ## prove the store owns its content (env-override, no live renames)
	python3 test_ownership.py

test:  ## run the merge-engine and claude-account self-checks
	@python3 test_merge.py
	@python3 test_claude_account.py

plugins:  ## vendor enabled Claude plugins into ~/.agent-home/plugins (never overwrites an already-vendored plugin)
	@python3 scripts/vendor-plugins.py

plugins-refresh:  ## report vendored plugins that drifted from the live Claude cache; writes nothing for existing dirs
	@python3 scripts/vendor-plugins.py --refresh

litellm:  ## OPTIONAL, parked: LiteLLM router (:4000), retired as the default model path 2026-08-06 — opencode/codex use native auth now
	@litellm --config litellm/config.yaml

doctor:  ## health-check everything: links, tokens, MCP freshness, env wiring
	@./scripts/doctor.sh

quota:  ## every account's headroom (Claude pools, Codex usage, OpenRouter credits)
	@./scripts/quota.sh

history:  ## index all harness transcripts; search with q="regex"
	@python3 scripts/history.py $(if $(q),search "$(q)",index)

agents:  ## regenerate opencode agents from ~/.agent-home/agents
	@python3 scripts/port-agents.py

watcher:  ## install the auto-resync watcher (launchd; re-runs sync on changes)
	@./scripts/install-watcher.sh
