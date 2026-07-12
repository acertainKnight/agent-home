#!/usr/bin/env python3
"""Non-breaking wiring of opencode.jsonc: MERGE our provider + (optional) plugin
into whatever config already exists, preserving every other key the user has.
Usage: wire-opencode.py <claude_in_opencode:true|false>"""
import json
import os
import re
import sys

DST = os.path.expanduser("~/.config/opencode/opencode.jsonc")
CIO = len(sys.argv) > 1 and sys.argv[1] == "true"

LITELLM_PROVIDER = {
    "npm": "@ai-sdk/openai-compatible",
    "name": "LiteLLM (ChatGPT sub + router)",
    "options": {"baseURL": "http://localhost:4000/v1"},
    "models": {
        "chatgpt/gpt-5.3-codex": {"name": "GPT-5.3 Codex (ChatGPT plan)"},
        "chatgpt/gpt-5.4": {"name": "GPT-5.4 (ChatGPT plan)"},
        "chatgpt/gpt-5.4-pro": {"name": "GPT-5.4 Pro (ChatGPT plan)"},
    },
}
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
cfg.setdefault("provider", {})
cfg["provider"]["litellm"] = LITELLM_PROVIDER  # our key; other providers untouched

plugins = [p for p in cfg.get("plugin", []) if p != PLUGIN]
if CIO:
    plugins.append(PLUGIN)
if plugins:
    cfg["plugin"] = plugins
elif "plugin" in cfg:
    del cfg["plugin"]

os.makedirs(os.path.dirname(DST), exist_ok=True)
json.dump(cfg, open(DST, "w"), indent=2)
print(f"  merged provider{' + claude plugin' if CIO else ''} into {DST} (kept your other keys)")
