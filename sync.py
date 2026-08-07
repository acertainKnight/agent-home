#!/usr/bin/env python3
"""agent-home: link the unified store (~/.agent-home) — skills, agents, commands,
memory, AGENTS.md — into every coding harness. This repo holds only the code;
your content lives in the ~/.agent-home dot-folder (override with $AGENT_HOME).

Usage:
  ./sync.py            apply mappings (idempotent)
  ./sync.py --adopt    move existing harness files INTO ~/.agent-home, then link
  ./sync.py --sweep    safe auto return path (skills/commands only), then link
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
    # ~/.remember is the remember-plugin's rolling session log; storing it here
    # lets every harness read it (writes still come from the Claude Code plugin).
    "claude-code": [
        (CANON / "skills", HOME / ".claude/skills"),
        (CANON / "agents", HOME / ".claude/agents"),
        (CANON / "commands", HOME / ".claude/commands"),
        (CANON / "memory", HOME / ".claude/auto-memory"),
        (CANON / "workflows", HOME / ".claude/workflows"),
        (CANON / "AGENTS.md", HOME / ".claude/CLAUDE.md"),
        (CANON / "remember", HOME / ".remember"),
    ],
    # Second Claude Code profile (e.g. work). Shares ~/.claude/skills already.
    "claude-code-work": [
        (CANON / "workflows", HOME / ".claude-work/workflows"),
        (CANON / "AGENTS.md", HOME / ".claude-work/CLAUDE.md"),
        (CANON / "commands", HOME / ".claude-work/commands"),
    ],
    # opencode: reads ~/.config/opencode/AGENTS.md, its own command/ dir (pointed
    # at the generated shared-command library so plugin commands port too), and
    # skills via skills.paths in opencode.jsonc (wire-opencode.py).
    "opencode": [
        (CANON / "AGENTS.md", HOME / ".config/opencode/AGENTS.md"),
        (HOME / ".agents/commands", HOME / ".config/opencode/command"),  # note: singular
    ],
    # Codex CLI is handled dynamically (one CODEX_HOME per chatgpt-sub account);
    # see codex_links() below.
}


def _accounts():
    c = load_config()
    return c.get("accounts", c.get("claude_accounts", []))


def codex_homes():
    """Every Codex account's CODEX_HOME (defaults to ~/.codex if none defined)."""
    homes = [os.path.expanduser(a["codex_home"]) for a in _accounts()
             if a.get("provider") == "chatgpt-sub" and a.get("codex_home")]
    return homes or [str(HOME / ".codex")]


def codex_links():
    out = []
    for h in codex_homes():
        h = Path(h)
        out += [(CANON / "AGENTS.md", h / "AGENTS.md"),
                (HOME / ".agents/commands", h / "prompts")]
    return out

def load_config():
    try:
        return json.load(open(CANON / "config.json"))
    except (OSError, json.JSONDecodeError):
        return {}


def links_for(names):
    out = []
    for name in names:
        out += HARNESSES.get(name, [])
    if "codex" in names:
        out += codex_links()  # one CODEX_HOME per chatgpt-sub account
    return out


def target_names():
    """Harnesses to link the store into."""
    cfg = load_config().get("harnesses")
    if not cfg:
        return list(HARNESSES) + ["codex"]
    return [n for n, on in cfg.items() if on]


def source_names():
    """Harnesses whose existing config we adopt INTO the store (subset of targets)."""
    return load_config().get("adopt_from", target_names())


# Everything the store links into. `status` and `apply` operate over targets.
SYMLINKS = links_for(target_names())

AGENTS_SKILLS = HOME / ".agents/skills"  # universal skill dir (Codex, opencode, spec default)
AGENTS_COMMANDS = HOME / ".agents/commands"  # generated command/prompt library

# Native skill dirs to MERGE into the store on sweep/adopt (skills reach these
# harnesses via ~/.agents/skills, so we import but don't keep a back-link).
SKILL_SWEEP = [AGENTS_SKILLS, HOME / ".codex/skills"]


def _enabled_plugin_roots():
    try:
        inst = json.load(open(HOME / ".claude/plugins/installed_plugins.json"))["plugins"]
        enabled = json.load(open(HOME / ".claude/settings.json")).get("enabledPlugins", {})
    except (OSError, KeyError, json.JSONDecodeError):
        return []
    return [Path(entries[0]["installPath"]) for name, entries in inst.items() if enabled.get(name)]


def enabled_plugin_skill_dirs():
    """Skill dirs shipped by ENABLED Claude Code plugins (plugins themselves don't port)."""
    out = []
    for root in _enabled_plugin_roots():
        skills = root / "skills"
        if skills.is_dir():
            out += [d for d in skills.iterdir() if (d / "SKILL.md").exists()]
    return out


def enabled_plugin_command_files():
    """Command/prompt markdown shipped by ENABLED plugins — portable to any
    harness with a prompt dir (Codex prompts/, opencode command/)."""
    out = []
    for root in _enabled_plugin_roots():
        cmds = root / "commands"
        if cmds.is_dir():
            out += sorted(cmds.rglob("*.md"))
    return out


def build_command_links():
    """~/.agents/commands = store commands + enabled plugin commands, as flat
    per-file symlinks. Store wins on name collision; first plugin wins after."""
    AGENTS_COMMANDS.mkdir(parents=True, exist_ok=True)
    for entry in AGENTS_COMMANDS.iterdir():
        if entry.is_symlink():
            entry.unlink()
        elif not entry.name.startswith("."):
            print(f"skip stale {entry}: not a symlink, not touching", file=sys.stderr)
    seen = set()
    for f in sorted(CANON.glob("commands/*.md")) + enabled_plugin_command_files():
        if f.name in seen:
            continue
        seen.add(f.name)
        link = AGENTS_COMMANDS / f.name
        if link.exists() and not link.is_symlink():
            continue
        link.symlink_to(f)
    print(f"{AGENTS_COMMANDS}: {len(seen)} commands linked")


def build_skill_links(dest):
    """dest = union of canonical skills + enabled plugin skills, as per-skill
    symlinks. Canonical wins on name collision. Regenerated each run. Hidden
    entries (Codex's .system) and real dirs are left alone."""
    dest.mkdir(parents=True, exist_ok=True)
    for entry in dest.iterdir():
        if entry.is_symlink():
            entry.unlink()
        elif not entry.name.startswith("."):
            print(f"skip stale {entry}: not a symlink, not touching", file=sys.stderr)
    seen = set()
    for d in sorted(CANON.glob("skills/*")) + enabled_plugin_skill_dirs():
        if not (d / "SKILL.md").exists() or d.name in seen:
            continue
        seen.add(d.name)
        link = dest / d.name
        if link.exists() and not link.is_symlink():
            continue  # stale real dir, already warned above
        link.symlink_to(d)
    print(f"{dest}: {len(seen)} skills linked")


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


def _merge_item(item, store, tag):
    """Move one file/dir into the store: new → move, identical → drop the copy,
    different → keep alongside as `name.from-<harness>` so nothing is ever lost."""
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


def merge_into_store(store, src, tag):
    """Union a harness dir/file into the store."""
    if src.is_dir():
        store.mkdir(parents=True, exist_ok=True)
        for item in list(src.iterdir()):
            _merge_item(item, store, tag)
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


def _sweep_skills():
    """Native skill dirs that aren't in the link map: import real skills only.
    Hidden entries (Codex ships built-ins in .system) and symlinks (our own
    generated links) stay put — the dir itself is never deleted."""
    for d in SKILL_SWEEP:
        if not d.is_dir() or d.is_symlink():
            continue
        for child in list(d.iterdir()):
            if child.name.startswith(".") or child.is_symlink():
                continue
            if (child / "SKILL.md").exists():
                _merge_item(child, CANON / "skills", _harness_of(child))


def _sweep_commands():
    """A command/prompt authored directly in ~/.agents/commands (a real file,
    not our generated symlink) merges into the store before build_command_links()
    regenerates the dir."""
    for f in list(AGENTS_COMMANDS.glob("*.md")):
        if not f.is_symlink():
            _merge_item(f, CANON / "commands", _harness_of(f))


def adopt():
    """Merge every SOURCE harness's real content into ~/.agent-home (union;
    nothing lost), then apply() links it all back."""
    CANON.mkdir(parents=True, exist_ok=True)
    for src, dst in links_for(source_names()):
        if dst.is_symlink() or not dst.exists():
            continue
        merge_into_store(src, dst, _harness_of(dst))
    _sweep_skills()
    _sweep_commands()


def sweep():
    """--sweep: the safe automatic return path (run by the watcher). Imports
    only skills/commands a harness authored directly, never touches a real
    harness config file the way --adopt's merge_into_store() does."""
    CANON.mkdir(parents=True, exist_ok=True)
    _sweep_skills()
    _sweep_commands()
    apply()


def apply():
    # Generated libraries first: they are link *sources* for codex/opencode.
    build_skill_links(AGENTS_SKILLS)
    build_command_links()
    if "codex" in target_names():  # Codex reads CODEX_HOME/skills natively
        for h in codex_homes():
            build_skill_links(Path(h) / "skills")
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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--adopt", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.status:
        status()
    elif a.adopt:
        adopt()
        apply()
    elif a.sweep:
        sweep()
    else:
        apply()
