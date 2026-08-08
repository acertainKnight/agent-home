#!/usr/bin/env python3
"""Claude Code settings custody: the live ~/.claude/settings.json stays the
working copy (Claude rewrites it freely); the store holds a portable, sanitized
capture so harness configuration survives a machine move.

  port-settings.py capture   live settings -> store, secrets split out
  port-settings.py apply     store -> live settings (only if absent; --force
                             backs up first) for a new machine
  port-settings.py check     is the store capture stale vs live? (informational)

Secret env values (key matches TOKEN/KEY/SECRET/PASSWORD) are replaced with
"${ENV:<KEY>}" placeholders in the tracked capture and merged as real values
into ~/.agent-home/env (gitignored, chmod 600). Hook scripts referenced by
hook commands under ~/.claude/hooks/ are vendored into
~/.agent-home/hooks/claude/ so they travel too.
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

HOME = Path.home()
LIVE = HOME / ".claude/settings.json"
# Both Claude accounts. claude-work's settings.json is (today) a symlink to
# claude's — capture records that relationship as a marker so apply can
# recreate it on a fresh machine; if it ever becomes a real file it gets its
# own full capture automatically.
PROFILES = {
    "claude": HOME / ".claude/settings.json",
    "claude-work": HOME / ".claude-work/settings.json",
}
CANON = HOME / ".agent-home"
CAPTURE = CANON / "settings/claude-settings.json"
SETTINGS_DIR = CANON / "settings"
ENV_FILE = CANON / "env"
HOOKS_VENDOR = CANON / "hooks/claude"
BACKUPS = CANON / "backups"

SECRET_KEY = re.compile(r"TOKEN|KEY|SECRET|PASSWORD", re.I)
PLACEHOLDER = re.compile(r"^\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}$")


def _read(p):
    return json.load(open(p))


def _env_lines():
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().removeprefix("export ").strip()] = v.strip()
    return out


def _merge_env(secrets):
    """Append missing KEY=value lines to ~/.agent-home/env; never rewrite
    existing values (env is hand-tended)."""
    have = _env_lines()
    missing = {k: v for k, v in secrets.items() if k not in have}
    if not missing:
        return []
    with open(ENV_FILE, "a") as f:
        for k, v in sorted(missing.items()):
            f.write(f"{k}={v}\n")
    ENV_FILE.chmod(0o600)
    return sorted(missing)


def _sanitize(cfg):
    """Return (sanitized copy, secrets dict)."""
    out = json.loads(json.dumps(cfg))
    secrets = {}
    for k, v in list(out.get("env", {}).items()):
        if SECRET_KEY.search(k) and isinstance(v, str) and not PLACEHOLDER.match(v):
            secrets[k] = v
            out["env"][k] = "${ENV:%s}" % k
    return out, secrets


def _hook_scripts(cfg):
    """Paths under ~/.claude/hooks/ referenced by any hook command."""
    out = []
    for rules in cfg.get("hooks", {}).values():
        for r in rules:
            for h in r.get("hooks", []):
                for tok in h.get("command", "").split():
                    p = Path(tok).expanduser()
                    if str(p).startswith(str(HOME / ".claude/hooks/")) and p.is_file():
                        out.append(p)
    return out


def _capture_path(profile):
    return SETTINGS_DIR / f"{profile}-settings.json"


def _symlinked_to(profile, live):
    """If this profile's settings.json symlinks to another profile's, return
    that profile's name, else None."""
    if not live.is_symlink():
        return None
    target = live.resolve()
    for other, other_live in PROFILES.items():
        if other != profile and target == other_live.resolve():
            return other
    return None


def capture():
    global CAPTURE  # kept pointing at the primary profile for check()/tests
    captured_any = False
    for profile, live in PROFILES.items():
        if not live.exists():
            continue
        out = _capture_path(profile)
        out.parent.mkdir(parents=True, exist_ok=True)
        link = _symlinked_to(profile, live)
        if link:
            json.dump({"__symlink_to__": link}, open(out, "w"), indent=2)
            print(f"settings[{profile}]: symlink to {link} — relationship captured")
            continue
        cfg = _read(live)
        sanitized, secrets = _sanitize(cfg)
        added = _merge_env(secrets)
        json.dump(sanitized, open(out, "w"), indent=2, sort_keys=True)
        vendored = []
        for src in _hook_scripts(cfg):
            HOOKS_VENDOR.mkdir(parents=True, exist_ok=True)
            dst = HOOKS_VENDOR / src.name
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copy2(src, dst)
                vendored.append(src.name)
        print(f"settings[{profile}]: captured -> {out}"
              + (f"; env += {added}" if added else "")
              + (f"; vendored hooks: {vendored}" if vendored else ""))
        captured_any = True
    if not captured_any and not any(l.exists() for l in PROFILES.values()):
        sys.exit("port-settings: no live settings.json in any profile to capture")


def _resolve(cfg):
    env = _env_lines()
    for k, v in list(cfg.get("env", {}).items()):
        m = PLACEHOLDER.match(v) if isinstance(v, str) else None
        if m:
            if m.group(1) not in env:
                sys.exit(f"port-settings: {m.group(1)} not in {ENV_FILE} — add it first")
            cfg["env"][k] = env[m.group(1)]
    return cfg


def apply(force=False):
    # real-file captures first, symlink markers second (targets must exist)
    caps = {p: _capture_path(p) for p in PROFILES if _capture_path(p).exists()}
    if not caps:
        sys.exit("port-settings: no capture in the store — run capture on a configured machine")
    ordered = sorted(caps, key=lambda p: "__symlink_to__" in _read(caps[p]))
    for profile in ordered:
        live, cap = PROFILES[profile], _read(caps[profile])
        if live.exists() and not force:
            sys.exit(f"port-settings: live {live} exists — refusing without --force")
        if live.exists() or live.is_symlink():
            BACKUPS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, BACKUPS / f"settings.json.{profile}.{time.strftime('%Y%m%d-%H%M%S')}",
                         follow_symlinks=True)
            live.unlink()
        live.parent.mkdir(parents=True, exist_ok=True)
        if "__symlink_to__" in cap:
            live.symlink_to(PROFILES[cap["__symlink_to__"]])
            print(f"settings[{profile}]: symlink -> {cap['__symlink_to__']} restored")
            continue
        json.dump(_resolve(cap), open(live, "w"), indent=2, sort_keys=True)
        hooks_dst = live.parent / "hooks"
        if HOOKS_VENDOR.is_dir():
            hooks_dst.mkdir(parents=True, exist_ok=True)
            for f in HOOKS_VENDOR.iterdir():
                if f.is_file() and not (hooks_dst / f.name).exists():
                    shutil.copy2(f, hooks_dst / f.name)
        print(f"settings[{profile}]: applied {caps[profile]} -> {live}")


def check():
    """True (exit 0) when every profile's capture matches live, modulo secret
    placeholders. Staleness between resync ticks is informational, not fatal."""
    all_ok = True
    for profile, live in PROFILES.items():
        cap_path = _capture_path(profile)
        if not live.exists():
            continue
        if not cap_path.exists():
            print(f"settings --check[{profile}]: no capture yet — run: python3 scripts/port-settings.py capture")
            all_ok = False
            continue
        cap = _read(cap_path)
        if "__symlink_to__" in cap:
            ok = _symlinked_to(profile, live) == cap["__symlink_to__"]
            print(f"settings --check[{profile}]: symlink relationship "
                  + ("intact" if ok else "BROKEN — live no longer links to " + cap["__symlink_to__"]))
            all_ok &= ok
            continue
        sanitized_live, _ = _sanitize(_read(live))
        if sanitized_live == cap:
            print(f"settings --check[{profile}]: capture matches live")
            continue
        drift = sorted(k for k in set(sanitized_live) | set(cap)
                       if sanitized_live.get(k) != cap.get(k))
        print(f"settings --check[{profile}]: capture stale vs live in keys {drift} — next resync heals it")
        all_ok = False
    return all_ok


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "capture"
    if cmd == "capture":
        capture()
    elif cmd == "apply":
        apply(force="--force" in sys.argv)
    elif cmd == "check":
        sys.exit(0 if check() else 1)
    else:
        sys.exit(__doc__)
