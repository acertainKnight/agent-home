# agent-home — `make install` runs the full guided setup walkthrough.
ACCOUNT ?= personal
.PHONY: help install login sync status verify test litellm
.DEFAULT_GOAL := help

help:  ## show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t20

install:  ## full walkthrough: pick harnesses, merge, wire, log in accounts
	@./install.sh

login:  ## log in & verify every account in config.json
	@./install.sh --login

sync:  ## re-merge the store into all harnesses (after adding a skill/plugin)
	@python3 sync.py --adopt

status:  ## show every symlink's state
	@./install.sh --status

verify:  ## prove an account runs on membership, not API credits (ACCOUNT=name)
	@./scripts/verify-claude-membership.sh $(ACCOUNT)

test:  ## run the merge-engine self-check
	@python3 test_merge.py

litellm:  ## start the LiteLLM router (:4000) — device-code login on first use
	@litellm --config litellm/config.yaml
