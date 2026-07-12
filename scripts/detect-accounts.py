#!/usr/bin/env python3
"""Auto-detect accounts on THIS machine from its per-account config dirs:
Claude (~/.claude, ~/.claude-work, ~/.claude-*) and Codex (~/.codex, ~/.codex-*).
Prints a config.json `accounts` array. Used as the fallback so a fresh/teammate
machine gets ITS OWN accounts, never a checked-in default. Key accounts
(OpenRouter etc.) are opt-in via the walkthrough, so they aren't auto-added."""
import json
import sys
from pathlib import Path

HOME = Path.home()


def _profiles(base, markers):
    """~/{base} then ~/{base}-* dirs that look real (contain any marker file)."""
    cands = [HOME / base] + sorted(d for d in HOME.glob(base + "-*"))
    return [d for d in cands if d.is_dir() and any((d / m).exists() for m in markers)]


def detect():
    accounts = []
    for d in _profiles(".claude", (".credentials.json", "settings.json", "projects")):
        suffix = d.name[len(".claude"):].lstrip("-") or "personal"
        accounts.append({
            "name": f"claude-{suffix}", "provider": "anthropic-sub",
            "config_dir": "~/" + d.name,
            "keychain": "Claude Code-credentials" if d.name == ".claude" else None,
        })
    port = 4001
    for d in _profiles(".codex", ("auth.json", "config.toml")):
        suffix = d.name[len(".codex"):].lstrip("-") or "personal"
        accounts.append({
            "name": f"chatgpt-{suffix}", "provider": "chatgpt-sub",
            "codex_home": "~/" + d.name, "port": port,
        })
        port += 1
    return accounts


def specs():
    """Pipe-delimited spec lines for the installer: name|provider|dir|keychain|env_key|base_url|port"""
    out = []
    for a in detect():
        if a["provider"] == "anthropic-sub":
            out.append(f'{a["name"]}|anthropic-sub|{a["config_dir"]}|{a.get("keychain") or ""}|||')
        elif a["provider"] == "chatgpt-sub":
            out.append(f'{a["name"]}|chatgpt-sub|{a["codex_home"]}||||')
    return out


if __name__ == "__main__":
    if "--specs" in sys.argv:
        print("\n".join(specs()))
    else:
        json.dump({"accounts": detect()}, sys.stdout, indent=2)
        sys.stdout.write("\n")
