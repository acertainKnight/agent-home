#!/usr/bin/env python3
"""Vendor every ENABLED Claude Code plugin's bytes into
~/.agent-home/plugins/<name>/ in Agent Plugins 1.0.0 layout, so the store
owns its plugin content instead of pointing at Claude's cache.

Reads (never writes): ~/.claude/plugins/installed_plugins.json (install
paths — the 7 plugins that live under ~/.claude-work/plugins/cache are
listed here too, same shared file), ~/.claude/settings.json's
enabledPlugins, ~/.claude/plugins/known_marketplaces.json (upstream repo
per marketplace).

Per plugin, writes ~/.agent-home/plugins/<name>/:
  plugin.json   Agent Plugins 1.0.0 root manifest ($schema, name, metadata.upstream)
  skills/       copied verbatim from the source plugin
  mcp.json      only if the source ships MCP servers; normalized to the
                {"mcpServers": {name: {..., "type": ...}}} vocabulary
  hooks/ commands/ agents/   copied verbatim, kept as extra files (the AP
                spec allows them; harness shims reference them)

Usage:
  vendor-plugins.py             vendor every enabled plugin not yet vendored (never overwrites an existing vendored dir)
  vendor-plugins.py --refresh   compare vendored plugins against the live Claude cache; report drift, write nothing for existing dirs
  vendor-plugins.py --validate  check every vendored skill's dir name against its SKILL.md `name:` field; report only
"""
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

HOME = Path.home()
STORE = Path(os.environ.get("AGENT_HOME", HOME / ".agent-home"))
PLUGINS_DIR = STORE / "plugins"
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", HOME / ".claude"))

SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CONTENT_DIRS = ("skills", "hooks", "commands", "agents")  # skills is AP-mandated; the rest ride as extra files
IGNORE = shutil.ignore_patterns(".in_use", "*.tmp.*", "__pycache__", "*.pyc")


def enabled_plugins():
    """[(short_name, marketplace, source_root, inst_version, git_sha)] for every ON plugin."""
    inst = json.load(open(CLAUDE_HOME / "plugins/installed_plugins.json"))["plugins"]
    enabled = json.load(open(CLAUDE_HOME / "settings.json")).get("enabledPlugins", {})
    out = []
    for key, entries in sorted(inst.items()):
        if not enabled.get(key):
            continue
        name, _, marketplace = key.partition("@")
        e = entries[0]
        out.append((name, marketplace, Path(e["installPath"]), e.get("version"), e.get("gitCommitSha")))
    return out


def upstream_repos():
    """marketplace id -> upstream repo/url, from Claude's own marketplace registry."""
    try:
        known = json.load(open(CLAUDE_HOME / "plugins/known_marketplaces.json"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for mp, info in known.items():
        src = info.get("source", {})
        out[mp] = src.get("repo") or src.get("url") or ""
    return out


def _read_json(p):
    try:
        return json.load(open(p))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump(obj, open(p, "w"), indent=2)


def _resolve_version(src_manifest, inst_version):
    return src_manifest.get("version") or (inst_version if inst_version != "unknown" else None) or "0.0.0"


def _normalize_mcp(raw):
    """Source .mcp.json -> AP {"mcpServers": {name: {..., "type": ...}}} vocabulary.
    Some plugins ship the bare {name: config} map with no "mcpServers" wrapper
    (measured: linear) — wrap it. Entries missing "type" get one inferred from
    whether they're a stdio command or a remote url."""
    servers = raw.get("mcpServers", raw)
    out = {}
    for name, cfg in servers.items():
        cfg = dict(cfg)
        if "type" not in cfg:
            cfg["type"] = "stdio" if "command" in cfg else "http"
        out[name] = cfg
    return {"mcpServers": out}


def build_manifest(name, marketplace, src, inst_version, sha, repos):
    src_manifest = _read_json(src / ".claude-plugin" / "plugin.json")
    version = _resolve_version(src_manifest, inst_version)
    manifest = {
        "$schema": SCHEMA,
        "name": name,
        "description": src_manifest.get("description", ""),
        "version": version,
        "metadata": {
            "upstream": {
                "marketplace": marketplace,
                "repo": repos.get(marketplace, ""),
                "version": version,
                "commit": sha,
                "vendored_at": date.today().isoformat(),
            }
        },
    }
    for k in ("author", "license", "homepage"):
        if src_manifest.get(k):
            manifest[k] = src_manifest[k]
    return manifest


def vendor_one(name, marketplace, src, inst_version, sha, repos):
    """Write ~/.agent-home/plugins/<name>/ fresh from the source cache. Overwrites
    whatever was there — callers decide whether that's safe (see vendor_all/refresh)."""
    dst = PLUGINS_DIR / name
    dst.mkdir(parents=True, exist_ok=True)
    for d in CONTENT_DIRS:
        if (src / d).is_dir():
            target = dst / d
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src / d, target, ignore=IGNORE)
    _write_json(dst / "plugin.json", build_manifest(name, marketplace, src, inst_version, sha, repos))
    mcp_src = src / ".mcp.json"
    if mcp_src.exists():
        raw = _read_json(mcp_src)
        if raw:
            _write_json(dst / "mcp.json", _normalize_mcp(raw))
    return dst


def vendor_all():
    """First-populate every enabled plugin not already vendored. Never touches a
    plugin dir that already exists — re-pulling upstream changes is --refresh's job,
    and it never overwrites either (see refresh())."""
    repos = upstream_repos()
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    new, skipped = 0, 0
    for name, marketplace, src, ver, sha in enabled_plugins():
        if not src.is_dir():
            print(f"  ! {name}: source {src} missing, skipped", file=sys.stderr)
            continue
        if (PLUGINS_DIR / name).exists():
            skipped += 1
            continue
        vendor_one(name, marketplace, src, ver, sha, repos)
        print(f"  + {name}")
        new += 1
    print(f"vendored {new} new plugin(s), {skipped} already vendored -> {PLUGINS_DIR}")


def _diff_report(live, src):
    """Human-readable diffs between an already-vendored content dir and the
    matching dir in the live source cache, recursively. [] if identical/absent."""
    import filecmp
    if not live.exists() and not src.exists():
        return []
    if not live.exists() or not src.exists():
        return [f"{live.name}/ " + ("added upstream" if src.exists() else "removed upstream")]
    diffs = []

    def walk(a, b, rel):
        c = filecmp.dircmp(a, b)
        diffs.extend(f"{rel}{n} (local only)" for n in c.left_only)
        diffs.extend(f"{rel}{n} (new upstream)" for n in c.right_only)
        diffs.extend(f"{rel}{n} (changed)" for n in c.diff_files)
        for d in c.common_dirs:
            walk(a / d, b / d, f"{rel}{d}/")

    walk(live, src, f"{live.name}/")
    return diffs


def refresh():
    """Report which vendored plugins have drifted from the live Claude cache
    (upstream version bump, or hand-edited vendored content) without writing
    anything for plugins already vendored. Brand-new enabled plugins (not yet
    vendored at all) are vendored for real, same as a plain run."""
    repos = upstream_repos()
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    changed = []
    for name, marketplace, src, ver, sha in enabled_plugins():
        if not src.is_dir():
            print(f"  ! {name}: source {src} missing, skipped", file=sys.stderr)
            continue
        live = PLUGINS_DIR / name
        if not live.exists():
            vendor_one(name, marketplace, src, ver, sha, repos)
            print(f"  + {name}: vendored (new)")
            changed.append(name)
            continue
        recorded = _read_json(live / "plugin.json").get("metadata", {}).get("upstream", {})
        fresh_version = _resolve_version(_read_json(src / ".claude-plugin/plugin.json"), ver)
        diffs = []
        for d in CONTENT_DIRS:
            diffs += _diff_report(live / d, src / d)
        if fresh_version == recorded.get("version") and sha == recorded.get("commit") and not diffs:
            continue
        detail = f" (upstream {recorded.get('version')} -> {fresh_version})" if fresh_version != recorded.get("version") else ""
        print(f"  ~ {name}{detail}" + (f", diffs: {diffs}" if diffs else ""))
        changed.append(name)
    if changed:
        print(f"plugins-refresh: {len(changed)} plugin(s) drifted from vendored copy — "
              f"inspect, then delete+re-run `python3 scripts/vendor-plugins.py` per plugin to accept "
              f"(never auto-overwrites an existing vendored dir)")
    else:
        print("plugins-refresh: every vendored plugin matches its recorded upstream")


def _skill_name(skill_md_text):
    """name: field from a SKILL.md's frontmatter, or None."""
    if not skill_md_text.startswith("---"):
        return None
    head = skill_md_text.split("---", 2)[1]
    for line in head.splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() == "name":
            return v.strip()
    return None


def validate():
    """Every vendored skill's dir name vs its SKILL.md `name:` field (the
    agentskills name-matches-dir rule). Report-only — never auto-fixes."""
    violations = []
    for plugin_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()):
        skills_dir = plugin_dir / "skills"
        if not skills_dir.is_dir():
            continue
        for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
            md = skill_dir / "SKILL.md"
            if not md.exists():
                violations.append((plugin_dir.name, skill_dir.name, "missing SKILL.md"))
                continue
            name = _skill_name(md.read_text())
            if name != skill_dir.name:
                violations.append((plugin_dir.name, skill_dir.name, f"SKILL.md name={name!r}"))
    if violations:
        print(f"skill name/dir violations ({len(violations)}):")
        for plugin, dirname, reason in violations:
            print(f"  {plugin}/skills/{dirname}: {reason}")
    else:
        print("all vendored skills: name matches dir")
    return violations


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    elif "--validate" in sys.argv:
        sys.exit(1 if validate() else 0)
    else:
        vendor_all()
