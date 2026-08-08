#!/usr/bin/env python3
"""Self-check for scripts/codex-hooks-status.py (issue #19 doctor check).
Run: python3 test_codex_hooks_status.py"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("codex_hooks_status", REPO / "scripts" / "codex-hooks-status.py")
chs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chs)


def _write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def test_missing_hook_plugin_is_reported():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-hookstatus-"))
    store, chome = scratch / "store", scratch / "chome"
    _write_json(store / "plugins/enabled.json", {"ponytail": True, "no-hooks-plugin": True})
    _write_json(store / "plugins/ponytail/.codex-plugin/plugin.json", {"hooks": "./hooks/hooks.json"})
    _write_json(store / "plugins/no-hooks-plugin/.codex-plugin/plugin.json", {})
    chome.mkdir(parents=True)
    (chome / "config.toml").write_text('forced_login_method = "chatgpt"\n')  # nothing installed yet

    total, missing = chs.status(chome, store)
    assert total == 1, total  # only ponytail ships hooks
    assert missing == ["ponytail"], missing
    shutil.rmtree(scratch)


def test_installed_and_enabled_is_clean():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-hookstatus-clean-"))
    store, chome = scratch / "store", scratch / "chome"
    _write_json(store / "plugins/enabled.json", {"ponytail": True})
    _write_json(store / "plugins/ponytail/.codex-plugin/plugin.json", {"hooks": "./hooks/hooks.json"})
    chome.mkdir(parents=True)
    (chome / "config.toml").write_text('[plugins."ponytail@agent-home"]\nenabled = true\n')

    total, missing = chs.status(chome, store)
    assert total == 1 and missing == [], (total, missing)
    shutil.rmtree(scratch)


def test_disabled_plugin_not_installed_but_enabled_true_is_clean_because_disabled_in_store():
    """A plugin OFF in the store's enabled.json is never expected in Codex,
    even if it ships hooks."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-hookstatus-disabled-"))
    store, chome = scratch / "store", scratch / "chome"
    _write_json(store / "plugins/enabled.json", {"ponytail": False})
    _write_json(store / "plugins/ponytail/.codex-plugin/plugin.json", {"hooks": "./hooks/hooks.json"})
    chome.mkdir(parents=True)
    (chome / "config.toml").write_text("")

    total, missing = chs.status(chome, store)
    assert total == 0 and missing == [], (total, missing)
    shutil.rmtree(scratch)


def test_installed_but_disabled_in_codex_is_reported_missing():
    """[plugins.X] present with enabled = false still counts as not installed."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-hookstatus-toggledoff-"))
    store, chome = scratch / "store", scratch / "chome"
    _write_json(store / "plugins/enabled.json", {"ponytail": True})
    _write_json(store / "plugins/ponytail/.codex-plugin/plugin.json", {"hooks": "./hooks/hooks.json"})
    chome.mkdir(parents=True)
    (chome / "config.toml").write_text('[plugins."ponytail@agent-home"]\nenabled = false\n')

    total, missing = chs.status(chome, store)
    assert total == 1 and missing == ["ponytail"], (total, missing)
    shutil.rmtree(scratch)


if __name__ == "__main__":
    test_missing_hook_plugin_is_reported()
    test_installed_and_enabled_is_clean()
    test_disabled_plugin_not_installed_but_enabled_true_is_clean_because_disabled_in_store()
    test_installed_but_disabled_in_codex_is_reported_missing()
    print("codex-hooks-status self-check: PASS")
