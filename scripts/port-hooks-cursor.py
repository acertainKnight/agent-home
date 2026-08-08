#!/usr/bin/env python3
"""Translate every ENABLED vendored plugin's Claude-format hooks/hooks.json
into ~/.cursor/hooks.json, for the events Cursor's hooks system supports.

Claude's hooks.json nests per-event: [{"matcher": "...", "hooks": [{"type":
"command", "command": "..."}]}]. Cursor's hooks.json (schema version 1,
{"version":1,"hooks":{"<event>":[{"command":"...","matcher":"..."}]}}) is
flat -- one entry per command, per event. This flattens accordingly,
expanding ${CLAUDE_PLUGIN_ROOT} to the plugin's absolute vendored path (other
harnesses don't provide that variable).

Not every Claude hook event has a Cursor equivalent (EVENT_MAP below is the
full supported set); anything else is skipped and reported. Entries gated by
Claude's `"if"` key (a command-CONTENT matcher, e.g. security-guidance's
`Bash(git commit:*)`) are also skipped -- Cursor's `matcher` only matches the
TOOL NAME, so translating one would fire on every Bash call instead of just
commits, which is a behavior change, not a port.

~/.cursor/hooks.json is fully regenerated from vendored plugins each run --
same "pure derivation, always safe to overwrite" contract vendor-plugins.py
uses for the .claude-plugin/.codex-plugin shims. Hand edits will be lost.

Usage: port-hooks-cursor.py [--check]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync

HOME = Path.home()
CURSOR_HOOKS = HOME / ".cursor/hooks.json"

# Claude Code hook event name -> Cursor hooks.json event name. Cursor has no
# equivalent for Notification (a Claude-only sound/toast hook).
EVENT_MAP = {
    "SessionStart": "sessionStart",
    "SessionEnd": "sessionEnd",
    "UserPromptSubmit": "beforeSubmitPrompt",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "Stop": "stop",
    "SubagentStop": "subagentStop",
}


def _expand(command, plugin_root):
    return command.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root)).replace("$CLAUDE_PLUGIN_ROOT", str(plugin_root))


def _missing_referenced_files(command, plugin_root):
    """Any in-plugin path the (already-expanded) command references that
    doesn't actually exist. vendor-plugins.py's CONTENT_DIRS only copies
    skills/hooks/commands/agents -- a hooks.json that points at a sibling
    dir like scripts/ or hooks-handlers/ (remember, explanatory-output-style
    both do) references a file that was never vendored. Emitting that
    command into hooks.json would just fail silently every time Cursor
    fires it, so it's filtered out here instead (see README's "opencode
    hook parity" section for the same class of gap on the opencode side)."""
    root_str = str(plugin_root)
    candidates = set(re.findall(r'"([^"]*)"', command))
    candidates |= {t for t in command.split() if t.startswith(root_str)}
    return sorted(c for c in candidates if c.startswith(root_str) and not Path(c).exists())


def translate_plugin(plugin_root):
    """One vendored plugin's hooks/hooks.json -> {cursor_event: [{"command","matcher"}]}."""
    hooks_json = plugin_root / "hooks/hooks.json"
    if not hooks_json.exists():
        return {}, []
    try:
        claude_hooks = json.load(open(hooks_json)).get("hooks", {})
    except (OSError, json.JSONDecodeError):
        return {}, []

    out, skipped = {}, []
    for claude_event, groups in claude_hooks.items():
        cursor_event = EVENT_MAP.get(claude_event)
        if not cursor_event:
            skipped.append(f"{plugin_root.name}:{claude_event} (no Cursor equivalent)")
            continue
        for group in groups:
            matcher = group.get("matcher")
            for h in group.get("hooks", []):
                if h.get("type") != "command":
                    continue
                if "if" in h:  # command-content conditional -- no faithful Cursor translation
                    skipped.append(f"{plugin_root.name}:{claude_event} (has \"if\" conditional, not portable)")
                    continue
                command = _expand(h["command"], plugin_root)
                missing = _missing_referenced_files(command, plugin_root)
                if missing:
                    skipped.append(f"{plugin_root.name}:{claude_event} references un-vendored file(s) {missing}")
                    continue
                entry = {"command": command}
                if matcher and matcher != "*":
                    entry["matcher"] = matcher
                out.setdefault(cursor_event, []).append(entry)
    return out, skipped


def build():
    """Merged {cursor_event: [entries]} across every enabled vendored plugin,
    sorted by plugin name so output is deterministic run to run."""
    merged, all_skipped = {}, []
    for root in sync._enabled_plugin_roots():
        per_plugin, skipped = translate_plugin(root)
        all_skipped += skipped
        for event, entries in per_plugin.items():
            merged.setdefault(event, []).extend(entries)
    return merged, all_skipped


def apply():
    merged, skipped = build()
    doc = {"version": 1, "hooks": merged}
    CURSOR_HOOKS.parent.mkdir(parents=True, exist_ok=True)
    json.dump(doc, open(CURSOR_HOOKS, "w"), indent=2)
    n = sum(len(v) for v in merged.values())
    print(f"cursor: wrote {n} hook(s) across {len(merged)} event(s) into {CURSOR_HOOKS}")
    for s in skipped:
        print(f"  skipped: {s}", file=sys.stderr)


def check():
    merged, _ = build()
    doc = {"version": 1, "hooks": merged}
    try:
        live = json.load(open(CURSOR_HOOKS)) if CURSOR_HOOKS.exists() else None
    except json.JSONDecodeError:
        print(f"cursor --check: {CURSOR_HOOKS} unparseable as JSON")
        return False
    if live != doc:
        print(f"cursor --check: hooks.json drift — run: python3 scripts/port-hooks-cursor.py")
        return False
    return True


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    apply()
