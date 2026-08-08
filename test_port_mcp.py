#!/usr/bin/env python3
"""Self-check for scripts/port-mcp.py (issue #15): spec-vocabulary migration,
--check drift detection, adopt() round-trip idempotence on a scratch store
(including a hand-authored Codex [mcp_servers.*] block flowing back in), and
the #8 destructive-emitter guard still holding. Run: python3 test_port_mcp.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("port_mcp", REPO / "scripts" / "port-mcp.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)


def test_migrate_entry_old_vocabulary():
    stdio_old = {"transport": "stdio", "command": "bun", "args": ["run", "start"]}
    assert pm._migrate_entry(stdio_old) == {"type": "stdio", "command": "bun", "args": ["run", "start"]}

    remote_old = {"transport": "remote", "url": "https://mcp.slack.com/mcp", "protocol": "http"}
    assert pm._migrate_entry(remote_old) == {"type": "streamable-http", "url": "https://mcp.slack.com/mcp"}

    sse_old = {"transport": "remote", "url": "https://x", "protocol": "sse"}
    assert pm._migrate_entry(sse_old)["type"] == "sse"

    already_new = {"type": "stdio", "command": "bun"}
    assert pm._migrate_entry(already_new) is already_new  # no-op, not even copied


def test_load_canon_one_shot_migration():
    """A file in the pre-#15 {"servers"} vocabulary reads back translated into
    the {"mcpServers"} / "type" vocabulary — the one-shot backward-compat read."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-mcp-migrate-"))
    canon = scratch / "mcp.json"
    canon.write_text(json.dumps({"servers": {
        "slack": {"transport": "remote", "url": "https://mcp.slack.com/mcp", "protocol": "http"},
        "snowflake": {"transport": "stdio", "command": "bash", "args": ["run.sh"]},
    }}))
    old_canon = pm.CANON
    pm.CANON = canon
    try:
        servers = pm.load_canon()
    finally:
        pm.CANON = old_canon
    assert servers["slack"] == {"type": "streamable-http", "url": "https://mcp.slack.com/mcp"}, servers["slack"]
    assert servers["snowflake"] == {"type": "stdio", "command": "bash", "args": ["run.sh"]}, servers["snowflake"]
    shutil.rmtree(scratch)


def test_has_cache_path():
    stale = {"type": "stdio", "command": "bun",
             "args": ["run", "--cwd", "/Users/x/.claude/plugins/cache/claude-plugins-official/imessage/0.1.0"]}
    healed = {"type": "stdio", "command": "bun",
              "args": ["run", "--cwd", "/Users/x/.agent-home/plugins/imessage"]}
    assert pm._has_cache_path(stale)
    assert not pm._has_cache_path(healed)
    assert not pm._has_cache_path({"type": "streamable-http", "url": "https://x"})


def test_hand_connectors_emit_oauth_and_remote_form():
    """Every hand-curated connector is a bare remote entry (no headers) -> Codex
    gets auth = "oauth", opencode gets the plain remote form."""
    found = pm.read_hand_connectors()
    assert "notion" in found and found["notion"]["url"] == "https://mcp.notion.com/mcp"
    assert "whatsapp" not in found  # no published endpoint (see issue #15 comment)
    e = found["notion"]
    block, is_remote, reauth = pm._codex_block("notion", e)
    assert is_remote and reauth == "notion" and 'auth = "oauth"' in block
    assert pm._oc_entry(e) == {"type": "remote", "url": "https://mcp.notion.com/mcp", "enabled": True}


def _write_toml(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_adopt_round_trip_and_hand_authored_codex_entry():
    """Scratch HOME/AGENT_HOME, no Claude profile at all. A server hand-authored
    directly in Codex's config.toml appears in mcp.json after one adopt (the
    #15 acceptance line), the hand connectors are unioned in, and a second
    adopt is a no-op (idempotent)."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-mcp-adopt-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    _write_toml(home / ".codex/config.toml",
                'forced_login_method = "chatgpt"\n\n'
                '[mcp_servers.myserver]\n'
                'command = "bun"\n'
                'args = ["run", "start"]\n')
    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))

    def run(*args):
        return subprocess.run([sys.executable, str(REPO / "scripts/port-mcp.py"), *args],
                               cwd=REPO, env=env, capture_output=True, text=True)

    r1 = run("adopt")
    assert r1.returncode == 0, r1.stderr
    canon = json.loads((store / "mcp.json").read_text())
    servers = canon["mcpServers"]
    assert servers["myserver"] == {"type": "stdio", "command": "bun", "args": ["run", "start"],
                                    "origin": "codex"}, servers["myserver"]
    assert servers["notion"]["origin"] == "hand"
    assert len(servers) == 1 + len(pm.HAND_CONNECTORS)

    r2 = run("adopt")
    assert r2.returncode == 0, r2.stderr
    canon2 = json.loads((store / "mcp.json").read_text())
    assert canon2 == canon, "second adopt() changed the canonical file — not idempotent"

    # apply() distributes canonical -> codex/opencode; check should then be clean
    r3 = run("apply")
    assert r3.returncode == 0, r3.stderr
    r4 = run("check")
    assert r4.returncode == 0, r4.stdout + r4.stderr

    # simulate drift: drop the codex block for one server, check must catch it
    toml_text = (home / ".codex/config.toml").read_text()
    drifted = toml_text.replace("[mcp_servers.myserver]\ncommand = \"bun\"\nargs = [\"run\", \"start\"]\n", "")
    assert drifted != toml_text
    (home / ".codex/config.toml").write_text(drifted)
    r5 = run("check")
    assert r5.returncode != 0
    assert "myserver" in r5.stdout

    shutil.rmtree(scratch)


def test_heal_stale_cache_path_on_reimport():
    """A canonical entry pointing at Claude's version-pinned plugin cache heals
    to the vendored store path once the source (here: a live-Codex-style entry
    standing in for the vendored plugin's .mcp.json) offers a non-cache path."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-mcp-heal-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    store.mkdir(parents=True)
    (store / "mcp.json").write_text(json.dumps({"mcpServers": {
        "imessage": {"type": "stdio", "command": "bun",
                     "args": ["run", "--cwd",
                              "/Users/x/.claude/plugins/cache/claude-plugins-official/imessage/0.1.0",
                              "--shell=bun", "--silent", "start"],
                     "origin": "claude"},
    }}))
    _write_toml(home / ".codex/config.toml",
                '[mcp_servers.imessage]\n'
                'command = "bun"\n'
                'args = ["run", "--cwd", "/Users/x/.agent-home/plugins/imessage", "--shell=bun", "--silent", "start"]\n')
    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))
    r = subprocess.run([sys.executable, str(REPO / "scripts/port-mcp.py"), "adopt"],
                        cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    servers = json.loads((store / "mcp.json").read_text())["mcpServers"]
    assert "plugins/cache" not in " ".join(servers["imessage"]["args"]), servers["imessage"]
    assert "healed" in r.stdout, r.stdout
    shutil.rmtree(scratch)


def test_guard_still_holds_on_unparseable_opencode():
    """Issue #8's guard: an opencode.jsonc that won't parse must abort apply()
    non-zero and stay byte-for-byte untouched, never get overwritten with just
    {"$schema":..., "mcp":...}."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-mcp-guard-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    store.mkdir(parents=True)
    (store / "mcp.json").write_text(json.dumps({"mcpServers": {
        "x": {"type": "streamable-http", "url": "https://x"}}}))
    corrupt = '{\n  "provider": {"note": "see it here // trailing"},\n  "mcp": {}\n}\n'
    _write_toml(home / ".config/opencode/opencode.jsonc", corrupt)
    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))
    r = subprocess.run([sys.executable, str(REPO / "scripts/port-mcp.py"), "apply"],
                        cwd=REPO, env=env, capture_output=True, text=True)
    assert r.returncode != 0, r.stdout
    assert (home / ".config/opencode/opencode.jsonc").read_text() == corrupt
    shutil.rmtree(scratch)


def test_cursor_entry_stdio():
    # no "type" key -- Cursor's mcpServers shape matches Claude's own
    # ~/.claude.json, unlike opencode's {"type":"local"|"remote",...}
    e = {"type": "stdio", "command": "bun", "args": ["run", "x"], "env": {"K": "V"}}
    assert pm._cursor_entry(e) == {"command": "bun", "args": ["run", "x"], "env": {"K": "V"}}


def test_cursor_entry_stdio_minimal():
    assert pm._cursor_entry({"type": "stdio", "command": "bash"}) == {"command": "bash"}


def test_cursor_entry_remote():
    e = {"type": "streamable-http", "url": "https://x/mcp", "headers": {"Authorization": "Bearer ${TOK}"}}
    assert pm._cursor_entry(e) == {"url": "https://x/mcp", "headers": {"Authorization": "Bearer ${TOK}"}}


def test_cursor_entry_remote_no_headers():
    assert pm._cursor_entry({"type": "streamable-http", "url": "https://x/mcp"}) == {"url": "https://x/mcp"}


def test_generate_cursor_non_breaking_merge():
    tmp = Path(tempfile.mkdtemp())
    canon = tmp / "mcp.json"
    canon.write_text(json.dumps({"servers": {"widget": {"type": "stdio", "command": "bun"}}}))
    cursor_mcp = tmp / "mcp.json.cursor"
    # pre-existing file with an unrelated key and an unrelated server --
    # both must survive the merge untouched.
    cursor_mcp.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "someOtherKey": True}))

    pm.CANON = canon
    pm.CURSOR_MCP = cursor_mcp
    pm.generate_cursor()

    out = json.loads(cursor_mcp.read_text())
    assert out["mcpServers"]["widget"] == {"command": "bun"}
    assert out["mcpServers"]["other"] == {"command": "x"}, "pre-existing unrelated server must survive"
    assert out["someOtherKey"] is True, "pre-existing unrelated top-level key must survive"
    shutil.rmtree(tmp)


def test_check_cursor_detects_drift():
    tmp = Path(tempfile.mkdtemp())
    canon = tmp / "mcp.json"
    canon.write_text(json.dumps({"servers": {"widget": {"type": "stdio", "command": "bun"}}}))
    cursor_mcp = tmp / "mcp.json.cursor"

    pm.CANON = canon
    pm.CURSOR_MCP = cursor_mcp

    # missing file entirely -> drift (servers exist in canon, nothing on disk)
    assert pm.check_cursor() is False

    pm.generate_cursor()
    assert pm.check_cursor() is True, "freshly generated file must check clean"

    # hand-edit one server -> drift again
    live = json.loads(cursor_mcp.read_text())
    live["mcpServers"]["widget"]["command"] = "python3"
    cursor_mcp.write_text(json.dumps(live))
    assert pm.check_cursor() is False
    shutil.rmtree(tmp)

if __name__ == "__main__":
    test_migrate_entry_old_vocabulary()
    test_load_canon_one_shot_migration()
    test_has_cache_path()
    test_hand_connectors_emit_oauth_and_remote_form()
    test_adopt_round_trip_and_hand_authored_codex_entry()
    test_heal_stale_cache_path_on_reimport()
    test_cursor_entry_stdio()
    test_cursor_entry_stdio_minimal()
    test_cursor_entry_remote()
    test_cursor_entry_remote_no_headers()
    test_generate_cursor_non_breaking_merge()
    test_check_cursor_detects_drift()
    test_guard_still_holds_on_unparseable_opencode()
    print("port-mcp self-check: PASS")
