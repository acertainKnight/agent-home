#!/usr/bin/env python3
"""agent-home: one canonical store for skills/agents/commands/memory/instructions,
symlinked or generated into every installed coding harness.

Usage:
  ./sync.py            apply mappings (idempotent)
  ./sync.py --adopt    first run: move existing harness files INTO canonical/, then link
  ./sync.py --status   show state of every mapping
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
CANON = REPO / "canonical"
HOME = Path.home()

# Per-harness link maps. `install.sh` writes config.json to pick which apply;
# absent config = all of them (backwards compatible). Uses $HOME so it's
# portable across teammates' machines.
HARNESSES = {
    # Claude Code, personal account: full canonical mount + native auto-memory.
    "claude-code": [
        (CANON / "skills", HOME / ".claude/skills"),
        (CANON / "agents", HOME / ".claude/agents"),
        (CANON / "commands", HOME / ".claude/commands"),
        (CANON / "memory", HOME / ".claude/auto-memory"),
        (CANON / "AGENTS.md", HOME / ".claude/CLAUDE.md"),
    ],
    # Second Claude Code profile (e.g. work). Shares ~/.claude/skills already.
    "claude-code-work": [
        (CANON / "AGENTS.md", HOME / ".claude-work/CLAUDE.md"),
    ],
    # opencode: reads ~/.config/opencode/AGENTS.md + ~/.agents/skills, and
    # natively ~/.claude/skills + ~/.claude/CLAUDE.md as fallbacks.
    "opencode": [
        (CANON / "AGENTS.md", HOME / ".config/opencode/AGENTS.md"),
    ],
    # Codex CLI: reads ~/.codex/AGENTS.md + ~/.agents/skills.
    "codex": [
        (CANON / "AGENTS.md", HOME / ".codex/AGENTS.md"),
    ],
}


def load_config():
    try:
        cfg = json.load(open(REPO / "config.json"))
    except (OSError, json.JSONDecodeError):
        return {name: True for name in HARNESSES}
    return cfg.get("harnesses", {name: True for name in HARNESSES})


def symlinks():
    enabled = load_config()
    out = []
    for name, links in HARNESSES.items():
        if enabled.get(name):
            out += links
    return out


SYMLINKS = symlinks()

AGENTS_SKILLS = HOME / ".agents/skills"  # universal skill dir (Codex, opencode, spec default)


def enabled_plugin_skill_dirs():
    """Skill dirs shipped by ENABLED Claude Code plugins (plugins themselves don't port)."""
    try:
        inst = json.load(open(HOME / ".claude/plugins/installed_plugins.json"))["plugins"]
        enabled = json.load(open(HOME / ".claude/settings.json")).get("enabledPlugins", {})
    except (OSError, KeyError, json.JSONDecodeError):
        return []
    out = []
    for name, entries in inst.items():
        if not enabled.get(name):
            continue
        skills = Path(entries[0]["installPath"]) / "skills"
        if skills.is_dir():
            out += [d for d in skills.iterdir() if (d / "SKILL.md").exists()]
    return out


def build_agents_skills():
    """~/.agents/skills = union of canonical skills + enabled plugin skills,
    as per-skill symlinks. Canonical wins on name collision. Regenerated each run."""
    AGENTS_SKILLS.mkdir(parents=True, exist_ok=True)
    for entry in AGENTS_SKILLS.iterdir():
        if entry.is_symlink():
            entry.unlink()
        else:
            print(f"skip stale {entry}: not a symlink, not touching", file=sys.stderr)
    seen = set()
    for d in sorted(CANON.glob("skills/*")) + enabled_plugin_skill_dirs():
        if not (d / "SKILL.md").exists() or d.name in seen:
            continue
        seen.add(d.name)
        link = AGENTS_SKILLS / d.name
        if link.exists() and not link.is_symlink():
            continue  # stale real dir, already warned above
        link.symlink_to(d)
    print(f"~/.agents/skills: {len(seen)} skills linked")


def status():
    for src, dst in SYMLINKS:
        if dst.is_symlink():
            ok = dst.resolve() == src.resolve()
            print(f"{'OK   ' if ok else 'WRONG'} {dst} -> {dst.resolve()}")
        elif dst.exists():
            print(f"REAL  {dst} (not linked; run --adopt)")
        else:
            print(f"MISS  {dst}")


def adopt():
    """Move real files/dirs into canonical/, leaving symlinks behind."""
    for src, dst in SYMLINKS:
        if dst.is_symlink() or not dst.exists():
            continue
        if src.is_dir() and not any(src.iterdir()):
            src.rmdir()
        if src.exists():
            if src.is_file() and dst.is_file() and src.read_bytes() == dst.read_bytes():
                dst.unlink()  # identical copy; symlink replaces it below via apply()
                continue
            print(f"skip {dst}: both real; merge into {src} manually", file=sys.stderr)
            continue
        print(f"adopt {dst} -> {src}")
        shutil.move(str(dst), str(src))
        dst.symlink_to(src)


def apply():
    for src, dst in SYMLINKS:
        if not src.exists():
            continue
        if dst.is_symlink():
            if dst.resolve() == src.resolve():
                continue
            dst.unlink()
        elif dst.exists():
            print(f"skip {dst}: real file exists, run --adopt", file=sys.stderr)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.symlink_to(src)
        print(f"link {dst} -> {src}")
    build_agents_skills()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--adopt", action="store_true")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
    elif a.adopt:
        adopt()
        apply()
    else:
        apply()
