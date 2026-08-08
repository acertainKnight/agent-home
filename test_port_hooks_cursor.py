#!/usr/bin/env python3
"""Self-check for scripts/port-hooks-cursor.py (issue #23): event mapping,
${CLAUDE_PLUGIN_ROOT} expansion, un-vendored-file filtering, "if"-conditional
filtering, and the merged multi-plugin build. Run: python3 test_port_hooks_cursor.py"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("port_hooks_cursor", REPO / "scripts" / "port-hooks-cursor.py")
phc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phc)


def w(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s)


def _plugin(tmp, name, hooks_json_obj, extra_files=()):
    root = tmp / "plugins" / name
    w(root / "hooks" / "hooks.json", json.dumps(hooks_json_obj))
    for rel in extra_files:
        w(root / rel, "#!/bin/sh\necho hi\n")
    return root


def test_expand_variable():
    assert phc._expand("${CLAUDE_PLUGIN_ROOT}/hooks/x.sh", Path("/p")) == "/p/hooks/x.sh"
    assert phc._expand("$CLAUDE_PLUGIN_ROOT/hooks/x.sh", Path("/p")) == "/p/hooks/x.sh"


def test_missing_referenced_files():
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "widget"
    (root / "hooks").mkdir(parents=True)
    (root / "hooks" / "real.sh").write_text("#!/bin/sh\n")
    ok_cmd = f'bash "{root}/hooks/real.sh"'
    bad_cmd = f'bash "{root}/scripts/missing.sh"'
    assert phc._missing_referenced_files(ok_cmd, root) == []
    assert phc._missing_referenced_files(bad_cmd, root) == [f"{root}/scripts/missing.sh"]
    shutil.rmtree(tmp)


def test_translate_plugin_maps_known_events():
    tmp = Path(tempfile.mkdtemp())
    root = _plugin(tmp, "widget", {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/start.sh"}]}],
        }
    }, extra_files=["hooks/start.sh"])
    out, skipped = phc.translate_plugin(root)
    assert out == {"sessionStart": [{"command": f"{root}/hooks/start.sh"}]}
    assert skipped == []
    shutil.rmtree(tmp)


def test_translate_plugin_skips_unmapped_event():
    tmp = Path(tempfile.mkdtemp())
    root = _plugin(tmp, "widget", {
        "hooks": {
            "Notification": [{"hooks": [{"type": "command", "command": "echo hi"}]}],
        }
    })
    out, skipped = phc.translate_plugin(root)
    assert out == {}
    assert "widget:Notification (no Cursor equivalent)" in skipped
    shutil.rmtree(tmp)


def test_translate_plugin_skips_if_conditional():
    tmp = Path(tempfile.mkdtemp())
    root = _plugin(tmp, "widget", {
        "hooks": {
            "PostToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "echo commit-review", "if": "Bash(git commit:*)"},
            ]}],
        }
    })
    out, skipped = phc.translate_plugin(root)
    assert out == {}
    assert any('has "if" conditional' in s for s in skipped)
    shutil.rmtree(tmp)


def test_translate_plugin_skips_un_vendored_file():
    tmp = Path(tempfile.mkdtemp())
    root = _plugin(tmp, "widget", {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/missing.sh"}]}],
        }
    })  # note: scripts/missing.sh deliberately not written
    out, skipped = phc.translate_plugin(root)
    assert out == {}
    assert any("references un-vendored file" in s for s in skipped)
    shutil.rmtree(tmp)


def test_translate_plugin_preserves_matcher():
    tmp = Path(tempfile.mkdtemp())
    root = _plugin(tmp, "widget", {
        "hooks": {
            "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
                {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check.sh"},
            ]}],
        }
    }, extra_files=["hooks/check.sh"])
    out, _ = phc.translate_plugin(root)
    assert out["postToolUse"][0]["matcher"] == "Edit|Write"
    # a bare "*" matcher (matches everything) is omitted, not carried over literally
    root2 = _plugin(tmp, "widget2", {
        "hooks": {"SessionStart": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/s.sh"}]}]}
    }, extra_files=["hooks/s.sh"])
    out2, _ = phc.translate_plugin(root2)
    assert "matcher" not in out2["sessionStart"][0]
    shutil.rmtree(tmp)


def test_build_merges_across_enabled_plugins():
    tmp = Path(tempfile.mkdtemp())
    a = _plugin(tmp, "alpha", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/a.sh"}]}]}}, ["hooks/a.sh"])
    b = _plugin(tmp, "beta", {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/b.sh"}]}]}}, ["hooks/b.sh"])

    orig = phc.sync._enabled_plugin_roots
    phc.sync._enabled_plugin_roots = lambda: [a, b]
    try:
        merged, skipped = phc.build()
        assert len(merged["stop"]) == 2
        assert {e["command"] for e in merged["stop"]} == {f"{a}/hooks/a.sh", f"{b}/hooks/b.sh"}
        assert skipped == []
    finally:
        phc.sync._enabled_plugin_roots = orig
    shutil.rmtree(tmp)


if __name__ == "__main__":
    test_expand_variable()
    test_missing_referenced_files()
    test_translate_plugin_maps_known_events()
    test_translate_plugin_skips_unmapped_event()
    test_translate_plugin_skips_if_conditional()
    test_translate_plugin_skips_un_vendored_file()
    test_translate_plugin_preserves_matcher()
    test_build_merges_across_enabled_plugins()
    print("port-hooks-cursor self-check: PASS")
