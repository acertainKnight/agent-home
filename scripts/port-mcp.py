#!/usr/bin/env python3
"""Port MCP servers across harnesses — the portable core of a "plugin".

A Claude Code plugin is really {skills, commands, subagents, MCP servers, hooks}.
Skills/commands already travel via the store. This adds MCP servers: it reads
every MCP definition any harness knows (Claude user-level + enabled plugins'
bundled .mcp.json, Codex's config.toml, opencode's mcp block) plus a hand-
curated list of claude.ai-only remote connectors, unions them into ONE
canonical file (~/.agent-home/mcp.json), then generates each harness's native
MCP config from it (non-breaking merge).

  port-mcp.py adopt      union every harness's MCP defs + hand connectors -> ~/.agent-home/mcp.json
  port-mcp.py apply      canonical -> opencode.jsonc + ~/.codex/config.toml (merge)
  port-mcp.py check      diff live configs against canonical; exit non-zero on drift
  port-mcp.py list       show canonical servers and per-harness portability

Canonical schema (~/.agent-home/mcp.json), Agent Plugins spec vocabulary:
  {"mcpServers": {"<name>": {
      "type": "stdio"|"streamable-http"|"sse",
      "origin": "claude"|"codex"|"opencode"|"hand",   # where adopt() found it
      # stdio:
      "command": "bun", "args": ["run", "..."], "env": {"K": "V"},
      # streamable-http / sse:
      "url": "https://…", "headers": {"…": "…"}
  }}}
A file written before this vocabulary (top-level "servers", "transport"/
"protocol") is read once via a backward-compat migration in load_canon();
the next adopt() rewrites it clean, so the migration only ever fires once
per machine.
"""
import json
import os
import re
import sys
import tomllib
from pathlib import Path

HOME = Path.home()
STORE = Path(os.environ.get("AGENT_HOME", HOME / ".agent-home"))
CANON = STORE / "mcp.json"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync  # noqa: E402 (needs the sys.path insert above)

# Remote connectors claude.ai connects with NO on-disk source of their own —
# ~/.claude.json's claudeAiMcpEverConnected holds display names only, never
# endpoints. Endpoints below are the ones the ticket supplied directly, plus
# Expedia's confirmed via https://mcpservers.org/remote-mcp-servers/expedia
# (Expedia's own developer docs describe MCP as still "in exploration", so
# that page is the only public confirmation of the live endpoint). All OAuth
# (no static headers) -> generate_codex emits auth = "oauth", opencode gets
# its plain remote form. "slack" and "cortex" are already adopted from a live
# harness and stay out of this list to avoid a second, conflicting source.
# WhatsApp: no vendor-published remote MCP endpoint exists (Meta ships none;
# only third-party bridges like verygoodplugins/whatsapp-mcp) — not guessed,
# see the comment on issue #15 instead.
HAND_CONNECTORS = {
    "notion": "https://mcp.notion.com/mcp",
    "linear": "https://mcp.linear.app/mcp",
    "vercel": "https://mcp.vercel.com",
    "supabase": "https://mcp.supabase.com/mcp",
    "figma": "https://mcp.figma.com/mcp",
    "huggingface": "https://huggingface.co/mcp",
    "context7": "https://mcp.context7.com/mcp",
    "miro": "https://mcp.miro.com",
    "strava": "https://mcp.strava.com/mcp",
    "google-calendar": "https://calendarmcp.googleapis.com/mcp/v1",
    "gmail": "https://gmailmcp.googleapis.com/mcp/v1",
    "google-drive": "https://drivemcp.googleapis.com/mcp/v1",
    "expedia": "https://www.expedia.com/mcp",
}


def read_hand_connectors():
    return {n: {"type": "streamable-http", "url": u} for n, u in HAND_CONNECTORS.items()}


def _normalize(name, cfg):
    """Claude MCP entry -> canonical entry (AP spec vocabulary)."""
    remote_url = cfg.get("url")
    ctype = cfg.get("type", "")
    if remote_url or ctype in ("http", "sse", "streamable-http"):
        e = {"type": "sse" if ctype == "sse" else "streamable-http", "url": remote_url}
        if cfg.get("headers"):
            e["headers"] = cfg["headers"]
        return e
    e = {"type": "stdio", "command": cfg.get("command", "")}
    if cfg.get("args"):
        e["args"] = cfg["args"]
    if cfg.get("env"):
        e["env"] = cfg["env"]
    return e


def _expand(obj, subs):
    """Resolve Claude-plugin path vars (${CLAUDE_PLUGIN_ROOT}, …) to absolute paths,
    since other harnesses don't provide them."""
    if isinstance(obj, str):
        for k, v in subs.items():
            obj = obj.replace("${%s}" % k, v).replace("$%s" % k, v)
        return obj
    if isinstance(obj, list):
        return [_expand(x, subs) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand(v, subs) for k, v in obj.items()}
    return obj


def read_claude_mcp():
    """All MCP servers Claude Code knows: user-level + enabled plugins' .mcp.json.
    Plugin roots prefer the vendored store copy (~/.agent-home/plugins/<name>)
    over Claude's version-pinned cache path, once vendor-plugins.py has run —
    the cache path breaks on the next plugin update, the store copy doesn't."""
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
    data_root = HOME / ".claude/plugins/data"
    for name, entries in inst.items():
        if not enabled.get(name):
            continue
        short = name.split("@")[0]
        vendored = STORE / "plugins" / short
        root = vendored if vendored.is_dir() else Path(entries[0]["installPath"])
        mf = root / ".mcp.json"
        if mf.exists():
            subs = {"CLAUDE_PLUGIN_ROOT": str(root),
                    "CLAUDE_PLUGIN_DATA": str(data_root / short)}
            for n, c in json.load(open(mf)).get("mcpServers", {}).items():
                servers.setdefault(n, _normalize(n, _expand(c, subs)))
    return servers


def read_codex_mcp():
    """[mcp_servers.*] tables from every codex_home's config.toml -> canonical
    entries. Multiple accounts can define the same server name differently;
    later homes win (matches adopt()'s general last-source-wins-on-heal rule)."""
    servers = {}
    for home in sync.codex_homes():
        toml_path = Path(home) / "config.toml"
        if not toml_path.exists():
            continue
        try:
            data = tomllib.loads(toml_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        for n, cfg in data.get("mcp_servers", {}).items():
            if "url" in cfg:
                e = {"type": "streamable-http", "url": cfg["url"]}
                bev = cfg.get("bearer_token_env_var")
                if bev:
                    e["headers"] = {"Authorization": "Bearer ${%s}" % bev}
            else:
                e = {"type": "stdio", "command": cfg.get("command", "")}
                if cfg.get("args"):
                    e["args"] = cfg["args"]
                if cfg.get("env"):
                    e["env"] = cfg["env"]
            servers[n] = e
    return servers


def read_opencode_mcp():
    """opencode.jsonc's `mcp` block -> canonical entries."""
    cfg = _read_jsonc(OPENCODE)
    if not cfg:
        return {}
    servers = {}
    for n, e in cfg.get("mcp", {}).items():
        if e.get("type") == "remote":
            out = {"type": "streamable-http", "url": e.get("url")}
            if e.get("headers"):
                out["headers"] = e["headers"]
        else:
            cmd = e.get("command") or []
            out = {"type": "stdio", "command": cmd[0] if cmd else ""}
            if len(cmd) > 1:
                out["args"] = cmd[1:]
            if e.get("environment"):
                out["env"] = e["environment"]
        servers[n] = out
    return servers


def _migrate_entry(e):
    """A pre-spec-vocabulary canonical entry ("transport"/"protocol") -> the AP
    spec vocabulary ("type"). One-shot: adopt() always writes the new form, so
    this only ever fires against a file nothing has re-adopted yet."""
    if "type" in e:
        return e
    if e.get("transport") == "stdio":
        out = {"type": "stdio", "command": e.get("command", "")}
        if e.get("args"):
            out["args"] = e["args"]
        if e.get("env"):
            out["env"] = e["env"]
    else:
        out = {"type": "sse" if e.get("protocol") == "sse" else "streamable-http",
               "url": e.get("url")}
        if e.get("headers"):
            out["headers"] = e["headers"]
    if e.get("origin"):
        out["origin"] = e["origin"]
    return out


def load_canon():
    if not CANON.exists():
        return {}
    raw = json.load(open(CANON))
    if "mcpServers" in raw:
        return raw["mcpServers"]
    return {n: _migrate_entry(e) for n, e in raw.get("servers", {}).items()}


def _has_cache_path(e):
    """True if a stdio entry's command/args reference Claude's version-pinned
    plugin cache (~/.claude/plugins/cache/...) — stale once the plugin is
    vendored into the store, since the cache path breaks on the next update."""
    if e.get("type") != "stdio":
        return False
    return any("/plugins/cache/" in str(a) for a in [e.get("command", "")] + list(e.get("args", [])))


def adopt():
    """Union every harness's MCP defs + the hand-curated connectors into the
    canonical file. New names are added with their origin recorded; an
    existing entry is only ever overwritten to heal a stale plugin-cache path
    (never to silently replace a manually-adjusted entry)."""
    servers = load_canon()
    added = healed = 0
    for origin, found in (("claude", read_claude_mcp()),
                           ("codex", read_codex_mcp()),
                           ("opencode", read_opencode_mcp()),
                           ("hand", read_hand_connectors())):
        for n, e in found.items():
            if n not in servers:
                e["origin"] = origin
                servers[n] = e
                added += 1
            elif _has_cache_path(servers[n]) and not _has_cache_path(e):
                e["origin"] = servers[n].get("origin", origin)
                servers[n] = e
                healed += 1
    STORE.mkdir(parents=True, exist_ok=True)
    json.dump({"mcpServers": servers}, open(CANON, "w"), indent=2)
    extra = f", {healed} healed" if healed else ""
    print(f"canonical mcp.json: {len(servers)} servers ({added} new{extra})")


def cmd_list():
    for n, e in load_canon().items():
        if e["type"] == "stdio":
            print(f"  {n}: stdio ({e.get('command')}) — ports to opencode + codex")
        else:
            oauth = not e.get("headers")
            print(f"  {n}: remote {e.get('type')} ({e.get('url','')[:40]}…) — "
                  f"opencode + codex: yes"
                  + ("; Claude-managed OAuth → re-authenticate in each harness" if oauth
                     else "; static auth ports"))


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
    """Returns {} for a missing file, None for a file that exists but won't parse
    (distinct cases — None must never be treated as "empty, safe to overwrite")."""
    if not p.exists():
        return {}
    raw = open(p).read()
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = re.sub(r"(^|\s)//[^\n]*", "", raw)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    try:
        return json.loads(raw) or {}
    except json.JSONDecodeError:
        return None


def _oc_entry(e):
    """canonical server entry -> opencode's mcp.<name> shape (the key this
    emitter owns; shared by generate_opencode and check_opencode so the two
    can never drift apart from each other)."""
    if e["type"] == "stdio":
        entry = {"type": "local",
                 "command": [e["command"]] + list(e.get("args", [])),
                 "enabled": True}
        if e.get("env"):
            entry["environment"] = {k: _oc_syntax(v) for k, v in e["env"].items()}
    else:
        entry = {"type": "remote", "url": e.get("url"), "enabled": True}
        if e.get("headers"):
            entry["headers"] = {k: _oc_syntax(v) for k, v in e["headers"].items()}
    return entry


def generate_opencode():
    """Merge canonical MCP servers into opencode.jsonc `mcp` block, non-breaking.
    opencode: {"type":"local","command":[...],"environment":{...}} | {"type":"remote","url":...}"""
    servers = load_canon()
    if not servers:
        return
    cfg = _read_jsonc(OPENCODE)
    if cfg is None:
        sys.exit(f"port-mcp: {OPENCODE} exists but won't parse as JSONC — "
                  f"not touching it. Fix the syntax error (or run "
                  f"scripts/wire-opencode.py, which backs up and rewrites clean).")
    cfg.setdefault("$schema", "https://opencode.ai/config.json")
    mcp = cfg.setdefault("mcp", {})
    for n, e in servers.items():
        mcp[n] = _oc_entry(e)
    OPENCODE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(cfg, open(OPENCODE, "w"), indent=2)
    print(f"opencode: wrote {len(servers)} MCP server(s) into {OPENCODE}")


def check_opencode():
    """--check: diff the mcp.<name> keys this emitter owns against the live
    file, without writing anything. Returns True if no drift."""
    servers = load_canon()
    if not servers:
        return True
    cfg = _read_jsonc(OPENCODE)
    if cfg is None:
        print(f"opencode --check: {OPENCODE} unparseable as JSONC")
        return False
    live = cfg.get("mcp", {})
    drift = [n for n, e in servers.items() if live.get(n) != _oc_entry(e)]
    if drift:
        print(f"opencode --check: drift in mcp.{{{', '.join(drift)}}} — run: make mcp")
    return not drift


def _toml_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _codex_block(n, e):
    """canonical server entry -> the [mcp_servers.<name>] TOML block text this
    emitter owns (plus is-remote and, for OAuth remotes, the reauth name).
    Shared by generate_codex and check_codex so the two can't drift apart."""
    lines = [f"\n[mcp_servers.{n}]"]
    reauth = None
    if e["type"] == "stdio":
        lines.append(f"command = {_toml_str(e['command'])}")
        if e.get("args"):
            lines.append("args = [" + ", ".join(_toml_str(a) for a in e["args"]) + "]")
        if e.get("env"):
            inner = ", ".join(f"{k} = {_toml_str(v)}" for k, v in e["env"].items())
            lines.append("env = { " + inner + " }")
    else:
        lines.append(f"url = {_toml_str(e['url'])}")
        bev = _bearer_env_var(e.get("headers"))
        if bev:
            lines.append(f"bearer_token_env_var = {_toml_str(bev)}")
        else:
            lines.append('auth = "oauth"')  # Claude-managed OAuth -> re-auth in Codex
            reauth = n
    return "\n".join(lines), e["type"] != "stdio", reauth


def generate_codex():
    """Write MCP servers to ~/.codex/config.toml. Idempotent: rewrites our managed
    [mcp_servers.*] blocks (so updates land), leaves every other key/table intact.
    stdio: command/args/env. remote (Streamable HTTP): url + bearer_token_env_var or
    auth=oauth, gated by [features] experimental_use_rmcp_client."""
    servers = load_canon()
    if not servers:
        return
    existing = CODEX_TOML.read_text() if CODEX_TOML.exists() else ""
    # Idempotent + updatable: drop our managed server blocks, then re-emit fresh.
    # (User's own [mcp_servers.*] not in canonical are left untouched.)
    for n in servers:
        existing = re.sub(r"(?ms)^\n?\[mcp_servers\." + re.escape(n) + r"\].*?(?=^\[|\Z)", "", existing)
    existing = existing.rstrip() + "\n"
    blocks, reauth, has_remote = [], [], False
    for n, e in servers.items():
        block, is_remote, ra = _codex_block(n, e)
        has_remote = has_remote or is_remote
        if ra:
            reauth.append(ra)
        blocks.append(block)
    prefix = ""
    if has_remote and "experimental_use_rmcp_client" not in existing:
        if "[features]" in existing:
            print("  ! add `experimental_use_rmcp_client = true` under [features] in config.toml for remote MCP")
        else:
            prefix = "\n[features]\nexperimental_use_rmcp_client = true\n"
    CODEX_TOML.parent.mkdir(parents=True, exist_ok=True)
    CODEX_TOML.write_text(existing.rstrip() + "\n" + prefix + "\n".join(blocks) + "\n")
    print(f"codex: wrote {len(blocks)} MCP server(s)"
          + (f"; re-authenticate in Codex: {reauth}" if reauth else ""))


def check_codex():
    """--check: diff the [mcp_servers.<name>] blocks this emitter owns against
    the live file's text, without writing anything. Returns True if no drift."""
    servers = load_canon()
    if not servers:
        return True
    existing = CODEX_TOML.read_text() if CODEX_TOML.exists() else ""
    drift = [n for n, e in servers.items() if _codex_block(n, e)[0] not in existing]
    if drift:
        print(f"codex --check: drift in mcp_servers.{{{', '.join(drift)}}} — run: make mcp")
    return not drift


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "adopt":
        adopt()
    elif cmd == "list":
        cmd_list()
    elif cmd == "apply":
        generate_opencode()
        generate_codex()
    elif cmd == "check":
        oc_ok, cx_ok = check_opencode(), check_codex()  # run both — don't let
        sys.exit(0 if oc_ok and cx_ok else 1)            # one drift hide the other
    else:
        print(__doc__)
