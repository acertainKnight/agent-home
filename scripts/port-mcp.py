#!/usr/bin/env python3
"""Port MCP servers across harnesses — the portable core of a "plugin".

A Claude Code plugin is really {skills, commands, subagents, MCP servers, hooks}.
Skills/commands already travel via the store. This adds MCP servers: it reads
every MCP definition Claude Code knows (user-level + enabled plugins' bundled
.mcp.json) into ONE canonical file (~/.agent-home/mcp.json), then generates each
harness's native MCP config from it (non-breaking merge).

  port-mcp.py adopt      Claude MCP defs -> ~/.agent-home/mcp.json (merge)
  port-mcp.py apply      canonical -> opencode.jsonc + ~/.codex/config.toml (merge)
  port-mcp.py list       show canonical servers and per-harness portability

Canonical schema (~/.agent-home/mcp.json):
  {"servers": {"<name>": {
      "transport": "stdio"|"remote",
      # stdio:
      "command": "bun", "args": ["run", "..."], "env": {"K": "V"},
      # remote:
      "url": "https://…", "protocol": "http"|"sse", "headers": {"…": "…"}
  }}}
"""
import json
import os
import sys
from pathlib import Path

HOME = Path.home()
STORE = Path(os.environ.get("AGENT_HOME", HOME / ".agent-home"))
CANON = STORE / "mcp.json"


def _normalize(name, cfg):
    """Claude MCP entry -> canonical entry."""
    remote_url = cfg.get("url")
    ctype = cfg.get("type", "")
    if remote_url or ctype in ("http", "sse", "streamable-http"):
        e = {"transport": "remote", "url": remote_url,
             "protocol": "sse" if ctype == "sse" else "http"}
        if cfg.get("headers"):
            e["headers"] = cfg["headers"]
        return e
    e = {"transport": "stdio", "command": cfg.get("command", "")}
    if cfg.get("args"):
        e["args"] = cfg["args"]
    if cfg.get("env"):
        e["env"] = cfg["env"]
    return e


def read_claude_mcp():
    """All MCP servers Claude Code knows: user-level + enabled plugins' .mcp.json."""
    servers = {}
    # user-level (~/.claude.json)
    uj = HOME / ".claude.json"
    if uj.exists():
        for n, c in json.load(open(uj)).get("mcpServers", {}).items():
            servers[n] = _normalize(n, c)
    # enabled plugins
    try:
        inst = json.load(open(HOME / ".claude/plugins/installed_plugins.json"))["plugins"]
        enabled = json.load(open(HOME / ".claude/settings.json")).get("enabledPlugins", {})
    except (OSError, KeyError, json.JSONDecodeError):
        inst, enabled = {}, {}
    for name, entries in inst.items():
        if not enabled.get(name):
            continue
        mf = Path(entries[0]["installPath"]) / ".mcp.json"
        if mf.exists():
            for n, c in json.load(open(mf)).get("mcpServers", {}).items():
                servers.setdefault(n, _normalize(n, c))  # user-level wins on name clash
    return servers


def load_canon():
    if CANON.exists():
        return json.load(open(CANON)).get("servers", {})
    return {}


def adopt():
    servers = load_canon()
    found = read_claude_mcp()
    added = 0
    for n, e in found.items():
        if n not in servers:
            servers[n] = e
            added += 1
    STORE.mkdir(parents=True, exist_ok=True)
    json.dump({"servers": servers}, open(CANON, "w"), indent=2)
    print(f"canonical mcp.json: {len(servers)} servers ({added} new)")


def cmd_list():
    for n, e in load_canon().items():
        if e["transport"] == "stdio":
            print(f"  {n}: stdio ({e.get('command')}) — ports to opencode + codex")
        else:
            oauth = not e.get("headers")
            print(f"  {n}: remote {e.get('protocol')} ({e.get('url','')[:40]}…) — "
                  f"opencode + codex: yes"
                  + ("; Claude-managed OAuth → re-authenticate in each harness" if oauth
                     else "; static auth ports"))


import re

OPENCODE = HOME / ".config/opencode/opencode.jsonc"
CODEX_TOML = HOME / ".codex/config.toml"
CODEX_REMOTE = True  # Codex supports Streamable-HTTP MCP (needs experimental_use_rmcp_client)

_VARREF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")


def _oc_syntax(v):
    """Claude ${VAR}/${VAR:-def} -> opencode {env:VAR} in a value string."""
    return _VARREF.sub(r"{env:\1}", str(v))


def _bearer_env_var(headers):
    """If an Authorization header is `Bearer ${VAR}`, return VAR (for Codex)."""
    for k, v in (headers or {}).items():
        if k.lower() == "authorization":
            m = _VARREF.search(str(v))
            if m:
                return m.group(1)
    return None


def _read_jsonc(p):
    if not p.exists():
        return {}
    raw = open(p).read()
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"(^|\s)//[^\n]*", "", raw)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    try:
        return json.loads(raw) or {}
    except json.JSONDecodeError:
        return {}


def generate_opencode():
    """Merge canonical MCP servers into opencode.jsonc `mcp` block, non-breaking.
    opencode: {"type":"local","command":[...],"environment":{...}} | {"type":"remote","url":...}"""
    servers = load_canon()
    if not servers:
        return
    cfg = _read_jsonc(OPENCODE)
    cfg.setdefault("$schema", "https://opencode.ai/config.json")
    mcp = cfg.setdefault("mcp", {})
    for n, e in servers.items():
        if e["transport"] == "stdio":
            entry = {"type": "local",
                     "command": [e["command"]] + list(e.get("args", [])),
                     "enabled": True}
            if e.get("env"):
                entry["environment"] = {k: _oc_syntax(v) for k, v in e["env"].items()}
        else:
            entry = {"type": "remote", "url": e.get("url"), "enabled": True}
            if e.get("headers"):
                entry["headers"] = {k: _oc_syntax(v) for k, v in e["headers"].items()}
        mcp[n] = entry
    OPENCODE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(cfg, open(OPENCODE, "w"), indent=2)
    print(f"opencode: wrote {len(servers)} MCP server(s) into {OPENCODE}")


def _toml_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def generate_codex():
    """Append MCP servers to ~/.codex/config.toml (append-only = non-breaking).
    stdio: command/args/env. remote (Streamable HTTP): url + bearer_token_env_var or
    auth=oauth, gated by [features] experimental_use_rmcp_client."""
    servers = load_canon()
    if not servers:
        return
    existing = CODEX_TOML.read_text() if CODEX_TOML.exists() else ""
    blocks, reauth, has_remote = [], [], False
    for n, e in servers.items():
        if f"[mcp_servers.{n}]" in existing:
            continue
        lines = [f"\n[mcp_servers.{n}]"]
        if e["transport"] == "stdio":
            lines.append(f"command = {_toml_str(e['command'])}")
            if e.get("args"):
                lines.append("args = [" + ", ".join(_toml_str(a) for a in e["args"]) + "]")
            if e.get("env"):
                inner = ", ".join(f"{k} = {_toml_str(v)}" for k, v in e["env"].items())
                lines.append("env = { " + inner + " }")
        else:
            has_remote = True
            lines.append(f"url = {_toml_str(e['url'])}")
            bev = _bearer_env_var(e.get("headers"))
            if bev:
                lines.append(f"bearer_token_env_var = {_toml_str(bev)}")
            else:
                lines.append('auth = "oauth"')  # Claude-managed OAuth -> re-auth in Codex
                reauth.append(n)
        blocks.append("\n".join(lines))
    prefix = ""
    if has_remote and "experimental_use_rmcp_client" not in existing:
        if "[features]" in existing:
            print("  ! add `experimental_use_rmcp_client = true` under [features] in config.toml for remote MCP")
        else:
            prefix = "\n[features]\nexperimental_use_rmcp_client = true\n"
    if blocks:
        CODEX_TOML.parent.mkdir(parents=True, exist_ok=True)
        with open(CODEX_TOML, "a") as f:
            f.write("\n" + prefix + "\n".join(blocks) + "\n")
    print(f"codex: added {len(blocks)} MCP server(s)"
          + (f"; re-authenticate in Codex: {reauth}" if reauth else ""))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "adopt":
        adopt()
    elif cmd == "list":
        cmd_list()
    elif cmd == "apply":
        generate_opencode()
        generate_codex()
    else:
        print(__doc__)
