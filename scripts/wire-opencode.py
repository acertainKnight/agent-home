#!/usr/bin/env python3
"""Non-breaking wiring of opencode.jsonc: MERGE our (optional) plugin and skills
path into whatever config already exists, preserving every other key the user has.
Model access is native as of opencode >=1.18 (`opencode auth login` for OpenRouter
and ChatGPT Pro/Plus) — this script does not write a provider block.
claude_in_opencode is LEGACY (blocked-era shim): native `opencode auth login`
-> Anthropic replaced it after the May/Jun 2026 reinstatement. false (the
default) also removes a stale shim plugin entry from the live config.
Usage: wire-opencode.py [--check] <claude_in_opencode:true|false>"""
import json
import os
import re
import sys

DST = os.path.expanduser("~/.config/opencode/opencode.jsonc")
CHECK = "--check" in sys.argv
_argv = [a for a in sys.argv[1:] if a != "--check"]
CIO = len(_argv) > 0 and _argv[0] == "true"

PLUGIN = "opencode-claude-auth@latest"

cfg = {}
if os.path.exists(DST):
    raw = open(DST).read()
    # jsonc -> json: drop /* */ and // comments and trailing commas, then parse.
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"(^|\s)//[^\n]*", "", raw)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    try:
        cfg = json.loads(raw) or {}
    except json.JSONDecodeError:
        os.rename(DST, DST + ".agent-home.bak")  # unparseable: preserve, start clean
        print(f"  (backed up unparseable opencode.jsonc -> {os.path.basename(DST)}.agent-home.bak)")
        cfg = {}

cfg.setdefault("$schema", "https://opencode.ai/config.json")

# owned-key snapshot, taken before we mutate cfg below — this is what --check
# diffs against (the state the live file was ACTUALLY in, not what we're about
# to make it).
live_paths = list(cfg.get("skills", {}).get("paths", []))
live_plugins = list(cfg.get("plugin", []))

# Shared skill library: opencode's native skill tool scans every dir listed in
# skills.paths, so pointing it at ~/.agents/skills gives it the same skill set
# as Claude Code and Codex without copying anything.
AGENTS_SKILLS = os.path.expanduser("~/.agents/skills")
paths = cfg.setdefault("skills", {}).setdefault("paths", [])
if AGENTS_SKILLS not in paths:
    paths.append(AGENTS_SKILLS)

plugins = [p for p in cfg.get("plugin", []) if p != PLUGIN]
if CIO:
    plugins.append(PLUGIN)
if plugins:
    cfg["plugin"] = plugins
elif "plugin" in cfg:
    del cfg["plugin"]

if CHECK:
    drift = []
    if AGENTS_SKILLS not in live_paths:
        drift.append("skills.paths (missing ~/.agents/skills)")
    if CIO and PLUGIN not in live_plugins:
        drift.append(f"plugin (missing {PLUGIN})")
    if not CIO and PLUGIN in live_plugins:
        drift.append(f"plugin (stale {PLUGIN}, claude_in_opencode=false)")
    if drift:
        sys.exit(f"wire-opencode --check: drift in {DST}: {'; '.join(drift)}")
    print(f"wire-opencode --check: {DST} OK")
    sys.exit(0)

os.makedirs(os.path.dirname(DST), exist_ok=True)
json.dump(cfg, open(DST, "w"), indent=2)
print(f"  merged skills.paths{' + claude plugin' if CIO else ''} into {DST} (kept your other keys)")
