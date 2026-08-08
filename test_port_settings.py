#!/usr/bin/env python3
"""Self-check for scripts/port-settings.py: secret split, placeholder
round-trip, idempotence, refusal to clobber. Run: python3 test_port_settings.py"""
import importlib.util
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ps", REPO / "scripts" / "port-settings.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)


def _scratch():
    d = Path(tempfile.mkdtemp())
    ps.LIVE = d / ".claude/settings.json"
    ps.PROFILES = {"claude": d / ".claude/settings.json",
                   "claude-work": d / ".claude-work/settings.json"}
    ps.CANON = d / ".agent-home"
    
    ps.SETTINGS_DIR = ps.CANON / "settings"
    ps.ENV_FILE = ps.CANON / "env"
    ps.HOOKS_VENDOR = ps.CANON / "hooks/claude"
    ps.BACKUPS = ps.CANON / "backups"
    ps.CANON.mkdir(parents=True)
    ps.LIVE.parent.mkdir(parents=True)
    return d


SAMPLE = {
    "model": "claude-fable-5",
    "outputStyle": "explanatory",
    "permissions": {"allow": ["Bash(git status)"]},
    "env": {"CORTEX_MCP_URL": "https://x/mcp", "CORTEX_API_TOKEN": "sekrit-abc123"},
    "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 /nope/dedupe.py"}]}]},
}


def test_capture_splits_secret_and_is_idempotent():
    _scratch()
    json.dump(SAMPLE, open(ps.LIVE, "w"))
    ps.capture()
    cap = json.load(open(ps._capture_path("claude")))
    assert cap["env"]["CORTEX_API_TOKEN"] == "${ENV:CORTEX_API_TOKEN}"
    assert cap["env"]["CORTEX_MCP_URL"] == "https://x/mcp"  # URL is not a secret
    assert "CORTEX_API_TOKEN=sekrit-abc123" in ps.ENV_FILE.read_text()
    before = ps._capture_path("claude").read_bytes(), ps.ENV_FILE.read_text()
    ps.capture()  # second run: no dup env line, same capture
    assert ps._capture_path("claude").read_bytes() == before[0]
    assert ps.ENV_FILE.read_text() == before[1]


def test_env_value_never_rewritten():
    _scratch()
    ps.ENV_FILE.write_text("CORTEX_API_TOKEN=hand-tended-newer\n")
    json.dump(SAMPLE, open(ps.LIVE, "w"))
    ps.capture()
    assert ps.ENV_FILE.read_text().count("CORTEX_API_TOKEN") == 1
    assert "hand-tended-newer" in ps.ENV_FILE.read_text()


def test_apply_resolves_placeholder_and_refuses_clobber():
    _scratch()
    json.dump(SAMPLE, open(ps.LIVE, "w"))
    ps.capture()
    ps.LIVE.unlink()
    ps.apply()
    restored = json.load(open(ps.LIVE))
    assert restored["env"]["CORTEX_API_TOKEN"] == "sekrit-abc123"
    assert restored["permissions"] == SAMPLE["permissions"]
    try:
        ps.apply()  # live exists now -> must refuse without --force
        raise AssertionError("apply() should have refused to clobber")
    except SystemExit as e:
        assert "refusing" in str(e)


def test_check_matches_and_detects_drift():
    _scratch()
    json.dump(SAMPLE, open(ps.LIVE, "w"))
    ps.capture()
    assert ps.check() is True
    live = json.load(open(ps.LIVE))
    live["model"] = "something-else"
    json.dump(live, open(ps.LIVE, "w"))
    assert ps.check() is False


def test_work_symlink_round_trip():
    d = _scratch()
    json.dump(SAMPLE, open(ps.LIVE, "w"))
    work = ps.PROFILES["claude-work"]
    work.parent.mkdir(parents=True)
    work.symlink_to(ps.LIVE)
    ps.capture()
    marker = json.load(open(ps.SETTINGS_DIR / "claude-work-settings.json"))
    assert marker == {"__symlink_to__": "claude"}
    assert ps.check() is True
    # fresh machine: both live files gone -> apply restores file + symlink
    work.unlink(); ps.LIVE.unlink()
    ps.apply()
    assert ps.LIVE.exists() and not ps.LIVE.is_symlink()
    assert work.is_symlink() and work.resolve() == ps.LIVE.resolve()


if __name__ == "__main__":
    test_capture_splits_secret_and_is_idempotent()
    test_env_value_never_rewritten()
    test_apply_resolves_placeholder_and_refuses_clobber()
    test_check_matches_and_detects_drift()
    test_work_symlink_round_trip()
    print("port-settings self-check: PASS")
