#!/usr/bin/env python3
"""agent-home: link the unified store (~/.agent-home) — skills, agents, commands,
memory, AGENTS.md — into every coding harness. This repo holds only the code;
your content lives in the ~/.agent-home dot-folder (override with $AGENT_HOME).

Usage:
  ./sync.py            apply mappings (idempotent)
  ./sync.py --adopt    move existing harness files INTO ~/.agent-home, then link
  ./sync.py --status   show state of every mapping
"""
import argparse
import filecmp
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
HOME = Path.home()
CANON = Path(os.environ.get("AGENT_HOME", HOME / ".agent-home"))

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
    # opencode: reads ~/.config/opencode/AGENTS.md, its own command/ dir, and
    # ~/.agents/skills + ~/.claude/skills natively.
    "opencode": [
        (CANON / "AGENTS.md", HOME / ".config/opencode/AGENTS.md"),
        (CANON / "commands", HOME / ".config/opencode/command"),  # note: singular
    ],
    # Codex CLI: reads ~/.codex/AGENTS.md, ~/.codex/prompts/ (slash commands),
    # + ~/.agents/skills.
    "codex": [
        (CANON / "AGENTS.md", HOME / ".codex/AGENTS.md"),
        (CANON / "commands", HOME / ".codex/prompts"),
    ],
}

# Native skill dirs to MERGE into the store on --adopt (skills reach these
# harnesses via ~/.agents/skills, so we import but don't keep a back-link).
SKILL_SWEEP = [HOME / ".config/opencode/skills", HOME / ".codex/skills"]


def load_config():
    try:
        return json.load(open(REPO / "config.json"))
    except (OSError, json.JSONDecodeError):
        return {}


def links_for(names):
    out = []
    for name in names:
        out += HARNESSES.get(name, [])
    return out


def target_names():
    """Harnesses to link the store into."""
    cfg = load_config().get("harnesses")
    if not cfg:
        return list(HARNESSES)
    return [n for n, on in cfg.items() if on]


def source_names():
    """Harnesses whose existing config we adopt INTO the store (subset of targets)."""
    return load_config().get("adopt_from", target_names())


# Everything the store links into. `status` and `apply` operate over targets.
SYMLINKS = links_for(target_names())

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


def _harness_of(path):
    s = str(path)
    if "/.claude-work/" in s:
        return "claude-work"
    if "/opencode/" in s:
        return "opencode"
    if "/.codex/" in s:
        return "codex"
    if "/.claude/" in s:
        return "claude"
    return "other"


def _same(a, b):
    """Deep equality for files or directory trees."""
    if a.is_dir() and b.is_dir():
        c = filecmp.dircmp(a, b)
        if c.left_only or c.right_only or c.diff_files or c.funny_files:
            return False
        return all(_same(a / d, b / d) for d in c.common_dirs)
    if a.is_file() and b.is_file():
        return filecmp.cmp(a, b, shallow=False)
    return False


def merge_into_store(store, src, tag):
    """Union a harness dir/file into the store. Same-name-different-content is
    kept alongside as `name.from-<harness>` so nothing is ever lost."""
    if src.is_dir():
        store.mkdir(parents=True, exist_ok=True)
        for item in list(src.iterdir()):
            target = store / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
                print(f"  + {store.name}/{item.name} (from {tag})")
            elif _same(item, target):
                (shutil.rmtree if item.is_dir() else lambda p: Path(p).unlink())(item)
            else:
                alt = store / f"{item.stem}.from-{tag}{item.suffix}"
                shutil.move(str(item), str(alt))
                print(f"  ! conflict {item.name}: kept as {alt.name} (from {tag})", file=sys.stderr)
        shutil.rmtree(src)
    else:  # instruction file: concatenate distinct content under a header
        if not store.exists():
            shutil.move(str(src), str(store))
            print(f"  + {store.name} (from {tag})")
            return
        have, add = store.read_text(), src.read_text()
        if add.strip() and add.strip() not in have:
            store.write_text(have.rstrip() + f"\n\n# --- merged from {tag} ---\n\n" + add.lstrip())
            print(f"  ~ {store.name}: merged instructions from {tag}", file=sys.stderr)
        src.unlink()


def adopt():
    """Merge every SOURCE harness's real content into ~/.agent-home (union;
    nothing lost), then apply() links it all back."""
    CANON.mkdir(parents=True, exist_ok=True)
    for src, dst in links_for(source_names()):
        if dst.is_symlink() or not dst.exists():
            continue
        merge_into_store(src, dst, _harness_of(dst))
    # Native skill dirs that aren't in the link map (imported, not back-linked).
    for d in SKILL_SWEEP:
        if d.is_dir() and not d.is_symlink():
            merge_into_store(CANON / "skills", d, _harness_of(d))


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
