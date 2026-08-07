#!/usr/bin/env python3
"""Self-check for scripts/vendor-plugins.py: MCP normalization, version
resolution, skill-name validation, and the never-overwrite-an-existing-
vendored-dir contract. Run: python3 test_vendor_plugins.py"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("vendor_plugins", REPO / "scripts" / "vendor-plugins.py")
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)


def w(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s)


def test_normalize_mcp():
    # bare map (no "mcpServers" wrapper, measured on linear's real .mcp.json) gets
    # wrapped, and an untyped remote entry gets "type": "http" inferred from url
    out = vp._normalize_mcp({"linear": {"url": "https://mcp.linear.app/mcp"}})
    assert out == {"mcpServers": {"linear": {"url": "https://mcp.linear.app/mcp", "type": "http"}}}, out
    # a stdio command entry gets "type": "stdio" inferred
    out = vp._normalize_mcp({"mcpServers": {"imessage": {"command": "bun"}}})
    assert out["mcpServers"]["imessage"]["type"] == "stdio", out
    # an already-typed entry is left alone
    out = vp._normalize_mcp({"mcpServers": {"cortex": {"type": "http", "url": "https://x"}}})
    assert out["mcpServers"]["cortex"]["type"] == "http"


def test_resolve_version():
    assert vp._resolve_version({"version": "1.2.3"}, "unknown") == "1.2.3"
    assert vp._resolve_version({}, "4.5.6") == "4.5.6"
    assert vp._resolve_version({}, "unknown") == "0.0.0"


def test_skill_name():
    assert vp._skill_name("---\nname: foo\ndescription: x\n---\nbody") == "foo"
    assert vp._skill_name("no frontmatter here") is None


def test_vendor_one_and_never_overwrite():
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src-cache" / "widget"
    w(src / "skills" / "widget" / "SKILL.md", "---\nname: widget\ndescription: d\n---\nbody")
    w(src / "hooks" / "hooks.json", '{"hooks": {}}')
    w(src / ".mcp.json", '{"mcpServers": {"widget": {"command": "bun"}}}')
    w(src / ".claude-plugin" / "plugin.json", json.dumps({"version": "1.0.0", "description": "a widget"}))

    vp.PLUGINS_DIR = tmp / "store" / "plugins"
    dst = vp.vendor_one("widget", "test-mp", src, "1.0.0", "deadbeef", {"test-mp": "org/widget"})
    assert dst == vp.PLUGINS_DIR / "widget"
    manifest = json.loads((dst / "plugin.json").read_text())
    assert manifest["name"] == "widget" and manifest["version"] == "1.0.0"
    assert manifest["$schema"] == vp.SCHEMA
    assert manifest["metadata"]["upstream"]["repo"] == "org/widget"
    assert manifest["metadata"]["upstream"]["commit"] == "deadbeef"
    assert (dst / "skills" / "widget" / "SKILL.md").exists()
    assert (dst / "hooks" / "hooks.json").exists()
    mcp = json.loads((dst / "mcp.json").read_text())
    assert mcp["mcpServers"]["widget"]["type"] == "stdio"

    # simulate a local hand-edit, then confirm vendor_all() (issue #12's "never
    # overwrite an already-vendored plugin dir" contract) leaves it untouched
    (dst / "skills" / "widget" / "SKILL.md").write_text("HAND EDITED")

    orig_enabled, orig_upstream = vp.enabled_plugins, vp.upstream_repos
    vp.enabled_plugins = lambda: [("widget", "test-mp", src, "1.0.0", "deadbeef")]
    vp.upstream_repos = lambda: {"test-mp": "org/widget"}
    try:
        vp.vendor_all()
    finally:
        vp.enabled_plugins, vp.upstream_repos = orig_enabled, orig_upstream
    assert (dst / "skills" / "widget" / "SKILL.md").read_text() == "HAND EDITED"

    shutil.rmtree(tmp)


def test_validate_reports_dir_mismatch():
    tmp = Path(tempfile.mkdtemp())
    vp.PLUGINS_DIR = tmp / "plugins"
    w(vp.PLUGINS_DIR / "p" / "skills" / "right-name" / "SKILL.md", "---\nname: wrong-name\n---\nbody")
    violations = vp.validate()
    assert len(violations) == 1 and violations[0][1] == "right-name", violations
    shutil.rmtree(tmp)


if __name__ == "__main__":
    test_normalize_mcp()
    test_resolve_version()
    test_skill_name()
    test_vendor_one_and_never_overwrite()
    test_validate_reports_dir_mismatch()
    print("vendor-plugins self-check: PASS")
