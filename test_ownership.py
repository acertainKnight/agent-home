#!/usr/bin/env python3
"""Ownership proof: sync.py's skill and command discovery must read only the
store (~/.agent-home), never ~/.claude or ~/.claude-work. Builds a small
synthetic store under a scratch HOME that has NEITHER Claude profile, runs
`python3 sync.py` against it via env overrides only (no live renames), and
proves every generated skill/command symlink resolves inside the scratch
store — never into a Claude plugin cache.
Run: python3 test_ownership.py"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent


def _skill(root, name):
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(f"---\nname: {name}\n---\nx")


def _synthetic_store(store):
    """Two store skills and one store command; an enabled plugin whose skills
    collide with a store skill on one name; a disabled plugin; and a folder
    with no plugin.json, which is not a plugin at all.
    Expected links: skills {alpha, beta, gamma}, commands {go.md, run.md}."""
    _skill(store / "skills", "alpha")
    _skill(store / "skills", "beta")
    (store / "commands").mkdir()
    (store / "commands" / "go.md").write_text("go")
    on = store / "plugins" / "on"
    _skill(on / "skills", "beta")   # collides: the store copy must win
    _skill(on / "skills", "gamma")
    (on / "commands").mkdir()
    (on / "commands" / "run.md").write_text("run")
    (on / "plugin.json").write_text("{}")
    off = store / "plugins" / "off"
    _skill(off / "skills", "delta")
    (off / "plugin.json").write_text("{}")
    _skill(store / "plugins" / "bare" / "skills", "epsilon")  # no plugin.json
    (store / "plugins" / "enabled.json").write_text('{"on": true, "off": false, "bare": true}')


def test_full_discovery_without_either_claude_profile():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-ownership-")).resolve()  # macOS: /var -> /private/var
    home = scratch / "home"
    store = scratch / "store"
    home.mkdir()
    _synthetic_store(store)
    assert not (home / ".claude").exists()
    assert not (home / ".claude-work").exists()

    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))
    result = subprocess.run([sys.executable, str(REPO / "sync.py")],
                             cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "3 skills linked" in result.stdout, result.stdout
    assert "2 commands linked" in result.stdout, result.stdout

    agents_skills = home / ".agents/skills"
    assert agents_skills.is_dir()
    linked = {p.name: p for p in agents_skills.iterdir() if p.is_symlink()}
    assert set(linked) == {"alpha", "beta", "gamma"}, set(linked)
    assert linked["beta"].resolve() == (store / "skills" / "beta").resolve()  # store wins the collision
    for link in linked.values():
        target = link.resolve()
        assert target.is_relative_to(store), f"{link} -> {target} escapes the store"
        assert ".claude" not in target.parts, f"{link} -> {target} resolves into a Claude profile"
    commands = {p.name for p in (home / ".agents/commands").iterdir() if p.is_symlink()}
    assert commands == {"go.md", "run.md"}, commands
    print("  linked 3 skills, 2 commands with neither Claude profile present")

    shutil.rmtree(scratch)


def test_enabled_json_gates_discovery():
    """A plugin absent from enabled.json contributes nothing, even though its
    bytes are vendored — proves the store-owned list is what gates discovery,
    not just "a plugins/ dir exists"."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_scratch", REPO / "sync.py")

    scratch = Path(tempfile.mkdtemp(prefix="agent-home-enabled-gate-"))
    home = scratch / "home"
    store = scratch / "store"
    home.mkdir()
    (store / "skills").mkdir(parents=True)
    (store / "plugins" / "on" / "skills" / "on-skill").mkdir(parents=True)
    (store / "plugins" / "on" / "skills" / "on-skill" / "SKILL.md").write_text("---\nname: on-skill\n---\nx")
    (store / "plugins" / "on" / "plugin.json").write_text("{}")
    (store / "plugins" / "off" / "skills" / "off-skill").mkdir(parents=True)
    (store / "plugins" / "off" / "skills" / "off-skill" / "SKILL.md").write_text("---\nname: off-skill\n---\nx")
    (store / "plugins" / "off" / "plugin.json").write_text("{}")
    (store / "plugins" / "enabled.json").write_text('{"on": true, "off": false}')

    old_home, old_agent_home = os.environ.get("HOME"), os.environ.get("AGENT_HOME")
    os.environ["HOME"], os.environ["AGENT_HOME"] = str(home), str(store)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        names = {d.name for d in mod.enabled_plugin_skill_dirs()}
        assert names == {"on-skill"}, names
    finally:
        for k, v in (("HOME", old_home), ("AGENT_HOME", old_agent_home)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    shutil.rmtree(scratch)


def test_seed_enabled_writes_short_names_once():
    """_seed_enabled() reads Claude's enabledPlugins (name@marketplace -> bool),
    keeps only the ON ones, and stores short names — the one-time migration
    off ~/.claude/settings.json."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_scratch2", REPO / "sync.py")

    scratch = Path(tempfile.mkdtemp(prefix="agent-home-seed-"))
    home = scratch / "home"
    store = scratch / "store"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        '{"enabledPlugins": {"ponytail@ponytail": true, "slack@claude-plugins-official": true, '
        '"vercel@claude-plugins-official": false}}')
    (store / "plugins").mkdir(parents=True)

    old_home, old_agent_home = os.environ.get("HOME"), os.environ.get("AGENT_HOME")
    os.environ["HOME"], os.environ["AGENT_HOME"] = str(home), str(store)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seeded = mod._seed_enabled()
        assert seeded == {"ponytail": True, "slack": True}, seeded
        assert mod.ENABLED_FILE.exists()
        import json
        assert json.loads(mod.ENABLED_FILE.read_text()) == seeded
    finally:
        for k, v in (("HOME", old_home), ("AGENT_HOME", old_agent_home)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    shutil.rmtree(scratch)


if __name__ == "__main__":
    test_full_discovery_without_either_claude_profile()
    test_enabled_json_gates_discovery()
    test_seed_enabled_writes_short_names_once()
    print("ownership self-check: PASS")
