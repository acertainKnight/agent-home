#!/usr/bin/env python3
"""Self-check for scripts/claude-account: pool pick order, exhausted skip,
reset-time parsing, mirror links, unknown-name detection, resume args.
Run: python3 test_claude_account.py"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
d = Path(tempfile.mkdtemp())
os.environ["AGENT_HOME"] = str(d / ".agent-home")
os.environ["AGENT_HOME_CONFIG"] = str(d / ".agent-home/config.json")
os.environ["CLAUDE_ACCOUNT_BASE"] = str(d / ".claude")
spec = importlib.util.spec_from_loader("ca", importlib.machinery.SourceFileLoader("ca", str(REPO / "scripts" / "claude-account")))
ca = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ca)

(d / ".agent-home").mkdir()
(d / ".claude").mkdir()
for n in ("skills", "projects", "plugins"):
    (d / ".claude" / n).mkdir()
(d / ".claude" / "settings.json").write_text("{}")
(d / ".claude" / "scheduled-tasks").mkdir()
(d / ".claude" / "settings.json.bak").write_text("{}")
(d / ".claude" / "sessions").mkdir()
json.dump({"accounts": [
    {"name": "claude-personal", "provider": "anthropic-sub", "config_dir": str(d / ".claude"), "spill_to": ["work"]},
    {"name": "claude-work", "provider": "anthropic-sub", "config_dir": str(d / ".claude-work"), "spill_to": ["personal"]},
    {"name": "claude-work-2", "provider": "anthropic-sub", "config_dir": str(d / ".claude-work-2")},
    {"name": "openrouter", "provider": "openai-key"},
]}, open(d / ".agent-home/config.json", "w"))

# pools derive from the name suffix; a trailing number is not a pool
assert ca.pools() == ["personal", "work"], ca.pools()
assert [a["name"] for a in ca.accounts() if a["pool"] == "work"] == ["claude-work", "claude-work-2"]
assert ca.by_name("work-2")["dir"] == d / ".claude-work-2"

# pick: config order with no readings; headroom wins once readings exist
assert ca.pick("work")["name"] == "claude-work"
ca._write_json(ca.STATE / "feed/claude-work.json", {"rate_limits": {"seven_day": {"used_percentage": 80}}, "at": time.time()})
ca._write_json(ca.STATE / "feed/claude-work-2.json", {"rate_limits": {"seven_day": {"used_percentage": 20}}, "at": time.time()})
assert ca.pick("work")["name"] == "claude-work-2"
assert ca.pick("work", exclude=["claude-work-2"])["name"] == "claude-work"
ca._write_json(ca.STATE / "exhausted/claude-work-2.json", {"until": time.time() + 3600})
assert ca.pick("work")["name"] == "claude-work"
ca._write_json(ca.STATE / "exhausted/claude-work.json", {"until": time.time() + 3600})
assert ca.pick("work") is None
assert [c["pool"] for c in ca.candidates_for(ca.by_name("claude-work"))] == ["personal"]

# reset parsing
now = dt.datetime(2026, 9, 13, 20, 0)  # a Sunday
t = ca.parse_reset("You've hit your session limit · resets 4:20am (America/Mexico_City)", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 14, 4, 20), dt.datetime.fromtimestamp(t)
t = ca.parse_reset("You've hit your weekly limit · resets Mon 12:00am", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 14, 0, 0)
t = ca.parse_reset("resets Sun 9pm", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 13, 21, 0)
assert ca.parse_reset("no time here", now) is None

# mirror: shared items linked into every non-default dir; real files untouched
(d / ".claude-work").mkdir()
(d / ".claude-work" / "plugins").mkdir()  # a real folder must not be replaced
ca.mirror()
assert (d / ".claude-work/skills").resolve() == (d / ".claude/skills").resolve()
assert (d / ".claude-work-2/settings.json").resolve() == (d / ".claude/settings.json").resolve()
assert not (d / ".claude-work/plugins").is_symlink()
assert not (d / ".claude-work/sessions").exists()  # private item never linked

# unknown names: recipe rulings and private patterns
assert ca.unknown_names() == ["scheduled-tasks"], ca.unknown_names()
ca.rule("scheduled-tasks", share=True)
assert ca.unknown_names() == []
assert (d / ".claude-work/scheduled-tasks").is_symlink()

# resume args keep flags and values, drop prompt / rc / earlier resume
assert ca._resume_args(["rc"], "sid") == ["--resume", "sid", "--remote-control"]
assert ca._resume_args(["--permission-mode", "acceptEdits", "do the thing", "-c"], "sid") == \
    ["--resume", "sid", "--permission-mode", "acceptEdits"]
assert ca._resume_args(["--resume", "old", "--model", "opus"], "sid") == ["--resume", "sid", "--model", "opus"]

# env: the default account launches with the variable unset, never set to its path
assert "CLAUDE_CONFIG_DIR" not in ca.env_for(ca.by_name("claude-personal"), {"CLAUDE_CONFIG_DIR": "x"})
assert ca.env_for(ca.by_name("claude-work"), {})["CLAUDE_CONFIG_DIR"] == str(d / ".claude-work")
assert ca.account_of_env({})["name"] == "claude-personal"
assert ca.account_of_env({"CLAUDE_CONFIG_DIR": str(d / ".claude-work-2")})["name"] == "claude-work-2"
print("claude-account self-check ok")

# login: a new account gets pool, directory, mirror links and the email/plan recorded
stub = d / "claude-stub"
stub.write_text('#!/bin/bash\nif [ "$1 $2" = "auth status" ]; then echo \'{"loggedIn": true, "email": "third@example.com", "subscriptionType": "max"}\'; fi\nexit 0\n')
stub.chmod(0o755)
ca.CLAUDE_BIN = str(stub)
assert ca._next_name("work") == "claude-work-3"
assert ca._next_name("consulting") == "claude-consulting"
assert ca.login(None, "work") == 0
entry = next(e for e in json.load(open(d / ".agent-home/config.json"))["accounts"] if e["name"] == "claude-work-3")
assert entry["login"] == "third@example.com" and entry["plan"] == "max" and entry["pool"] == "work", entry
assert entry["spill_to"] == ["personal"]  # inherited from the pool's siblings
assert (d / ".claude-work-3/projects").resolve() == (d / ".claude/projects").resolve()
assert ca.login("claude-work-3", None) == 0  # re-sign an existing account
print("login self-check ok")
