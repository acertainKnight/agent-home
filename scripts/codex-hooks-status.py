#!/usr/bin/env python3
"""doctor.sh helper (issue #19): which enabled, hook-carrying vendored plugins
are installed+enabled in one codex_home's config.toml. Proves the install
step ran (`codex plugin add <name>@agent-home`), NOT that the hook fires —
firing needs a one-time interactive hook-trust grant, see README's Hooks row.

Usage: codex-hooks-status.py <codex_home> <store>
Prints "<hook-carrying total>|<comma-separated names missing from config.toml>".
"""
import json
import sys
import tomllib
from pathlib import Path


def hook_carrying_plugins(store):
    """Enabled vendored plugins whose Codex manifest references a hooks file."""
    try:
        enabled = json.load(open(store / "plugins/enabled.json"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for name, on in enabled.items():
        if not on:
            continue
        try:
            manifest = json.load(open(store / "plugins" / name / ".codex-plugin/plugin.json"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("hooks"):
            out.append(name)
    return out


def installed_enabled_names(chome):
    """Short plugin names installed+enabled in this codex_home's config.toml."""
    try:
        plugins = tomllib.loads((chome / "config.toml").read_text()).get("plugins", {})
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    return {key.split("@")[0] for key, table in plugins.items() if table.get("enabled")}


def status(chome, store):
    """(hook-carrying total, [names missing from config.toml])."""
    hook_plugins = hook_carrying_plugins(store)
    installed = installed_enabled_names(chome)
    missing = [n for n in hook_plugins if n not in installed]
    return len(hook_plugins), missing


if __name__ == "__main__":
    total, missing = status(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{total}|{','.join(missing)}")
