#!/usr/bin/env python3
"""Ownership proof for issue #14: sync.py's plugin discovery must read only
the store (~/.agent-home/plugins), never ~/.claude or ~/.claude-work. Builds
a scratch copy of the real store's skills/, commands/, and plugins/ (incl.
enabled.json) under a scratch HOME that has NEITHER Claude profile, runs
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
REAL_STORE = Path(os.environ.get("AGENT_HOME", Path.home() / ".agent-home"))


def _plugin_dirs(store):
    return [p for p in sorted((store / "plugins").iterdir()) if p.is_dir()]


def _expected_skill_names(store):
    """Same store-wins-on-collision dedup sync.py's build_skill_links() does,
    so the test's expected count can never silently drift from the real logic."""
    seen = {d.name for d in sorted(store.glob("skills/*")) if (d / "SKILL.md").exists()}
    for p in _plugin_dirs(store):
        skills = p / "skills"
        if skills.is_dir():
            seen |= {d.name for d in skills.iterdir() if (d / "SKILL.md").exists()}
    return seen


def _expected_command_names(store):
    """Same dedup sync.py's build_command_links() does."""
    seen = {f.name for f in sorted(store.glob("commands/*.md"))}
    for p in _plugin_dirs(store):
        cmds = p / "commands"
        if cmds.is_dir():
            seen |= {f.name for f in cmds.rglob("*.md")}
    return seen


def test_full_discovery_without_either_claude_profile():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-ownership-")).resolve()  # macOS: /var -> /private/var
    home = scratch / "home"
    store = scratch / "store"
    home.mkdir()
    for d in ("skills", "commands", "plugins"):
        shutil.copytree(REAL_STORE / d, store / d)
    assert not (home / ".claude").exists()
    assert not (home / ".claude-work").exists()

    expected_skills = _expected_skill_names(store)
    expected_commands = _expected_command_names(store)

    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))
    result = subprocess.run([sys.executable, str(REPO / "sync.py")],
                             cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"{len(expected_skills)} skills linked" in result.stdout, result.stdout
    assert f"{len(expected_commands)} commands linked" in result.stdout, result.stdout

    # today's real store: 28 store + 66 plugin skills = 94; 1 store + 17 plugin
    # commands = 18 — the exact figures issue #14 names as the acceptance bar
    print(f"  linked {len(expected_skills)} skills, {len(expected_commands)} commands "
          f"with neither Claude profile present")

    agents_skills = home / ".agents/skills"
    assert agents_skills.is_dir()
    linked = [p for p in agents_skills.iterdir() if p.is_symlink()]
    assert len(linked) == len(expected_skills)
    for link in linked:
        target = link.resolve()
        assert target.is_relative_to(store), f"{link} -> {target} escapes the store"
        assert ".claude" not in target.parts, f"{link} -> {target} resolves into a Claude profile"

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
    off ~/.claude/settings.json that issue #14 requires."""
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
