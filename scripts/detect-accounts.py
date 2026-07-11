#!/usr/bin/env python3
"""Auto-detect Claude accounts on THIS machine from its CLAUDE_CONFIG_DIR-style
dirs (~/.claude, ~/.claude-work, ~/.claude-*). Prints a config.json `accounts`
array. Used as the fallback so a fresh/teammate machine gets ITS OWN accounts,
never a checked-in default. ChatGPT/key accounts are opt-in via the walkthrough,
so they aren't auto-added here."""
import json
import sys
from pathlib import Path

HOME = Path.home()


def looks_like_claude_dir(p):
    return p.is_dir() and any((p / f).exists() for f in (".credentials.json", "settings.json", "projects"))


def detect():
    accounts = []
    # personal first if present, then any other ~/.claude* profile dirs
    candidates = [HOME / ".claude"] + sorted(
        d for d in HOME.glob(".claude-*") if d.name != ".claude"
    )
    for d in candidates:
        if not looks_like_claude_dir(d):
            continue
        suffix = d.name[len(".claude"):].lstrip("-") or "personal"
        name = f"claude-{suffix}"
        acct = {"name": name, "provider": "anthropic-sub", "config_dir": "~/" + d.name}
        # The default profile also has a macOS keychain entry.
        acct["keychain"] = "Claude Code-credentials" if d.name == ".claude" else None
        accounts.append(acct)
    return accounts


if __name__ == "__main__":
    json.dump({"accounts": detect()}, sys.stdout, indent=2)
    sys.stdout.write("\n")
