#!/usr/bin/env python3
"""Self-check for scripts/claude-account: pool pick order, exhausted skip,
reset-time parsing, mirror links, unknown-name detection, resume args.
Run: python3 test_claude_account.py"""
import datetime as dt
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
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

# pick: config order, whatever the headroom readings say; exhausted skipped
assert ca.pick("work")["name"] == "claude-work"
ca._write_json(ca.STATE / "feed/claude-work.json", {"rate_limits": {"seven_day": {"used_percentage": 80}}, "at": time.time()})
ca._write_json(ca.STATE / "feed/claude-work-2.json", {"rate_limits": {"seven_day": {"used_percentage": 20}}, "at": time.time()})
assert ca.pick("work")["name"] == "claude-work"
assert ca.pick("work", exclude=["claude-work"])["name"] == "claude-work-2"
ca._write_json(ca.STATE / "exhausted/claude-work.json", {"until": time.time() + 3600})
assert ca.pick("work")["name"] == "claude-work-2"
ca._write_json(ca.STATE / "exhausted/claude-work-2.json", {"until": time.time() + 3600})
assert ca.pick("work") is None
assert [c["pool"] for c in ca.candidates_for(ca.by_name("claude-work"))] == ["personal"]

# next_account: own pool first, then the spill pool, then nothing; earliest reset across all
assert ca.next_account("work")["name"] == "claude-personal"
ca._write_json(ca.STATE / "exhausted/claude-personal.json", {"until": time.time() + 7200})
assert ca.next_account("work") is None
assert ca.next_account("personal") is None
assert abs(ca.earliest_reset() - (time.time() + 3600)) < 5
note = {"session_id": "sid", "from": "claude-work", "pool": "work", "next": "claude-personal",
        "until": time.time() + 3600, "text": "You've hit your session limit · resets 7pm", "created": time.time()}
msg = ca.resume_message(note, ca.by_name("claude-personal"))
assert msg.startswith("[claude-account] This conversation moved from claude-work to claude-personal")
assert "resumeFromRunId" in msg and "Do not ask whether to continue." in msg
(ca.STATE / "exhausted/claude-personal.json").unlink()

# clear drops the mark; prefer reorders the pool in config.json
assert ca.clear("work-2") == 0
assert ca.pick("work")["name"] == "claude-work-2"
assert ca.clear("claude-work") == 0
assert ca.pick("work")["name"] == "claude-work"
assert ca.prefer("work-2") == 0
assert [a["name"] for a in ca.accounts() if a["pool"] == "work"] == ["claude-work-2", "claude-work"]
assert ca.pick("work")["name"] == "claude-work-2"
assert ca.prefer("work") == 0
assert [a["name"] for a in ca.accounts() if a["pool"] == "work"] == ["claude-work", "claude-work-2"]
assert ca.prefer("nobody") == 1

# reset parsing
now = dt.datetime(2026, 9, 13, 20, 0)  # a Sunday
t = ca.parse_reset("You've hit your session limit · resets 4:20am (America/Mexico_City)", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 14, 4, 20), dt.datetime.fromtimestamp(t)
t = ca.parse_reset("You've hit your weekly limit · resets Mon 12:00am", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 14, 0, 0)
t = ca.parse_reset("resets Sun 9pm", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 13, 21, 0)
t = ca.parse_reset("You've hit your weekly limit · resets Sep 16 at 1pm (America/New_York)", now)
assert dt.datetime.fromtimestamp(t) == dt.datetime(2026, 9, 16, 13, 0)
t = ca.parse_reset("resets Jan 2 at 1pm", dt.datetime(2026, 12, 31, 10, 0))
assert dt.datetime.fromtimestamp(t) == dt.datetime(2027, 1, 2, 13, 0)
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
# the starting message goes first, ahead of --remote-control's optional name slot
assert ca._resume_args(["rc"], "sid", "moved") == ["moved", "--resume", "sid", "--remote-control"]
assert ca._resume_args(["--dangerously-skip-permissions"], "sid", "moved") == \
    ["moved", "--resume", "sid", "--dangerously-skip-permissions"]

# env: the default account launches with the variable unset, never set to its path
assert "CLAUDE_CONFIG_DIR" not in ca.env_for(ca.by_name("claude-personal"), {"CLAUDE_CONFIG_DIR": "x"})
assert ca.env_for(ca.by_name("claude-work"), {})["CLAUDE_CONFIG_DIR"] == str(d / ".claude-work")
assert ca.account_of_env({})["name"] == "claude-personal"
assert ca.account_of_env({"CLAUDE_CONFIG_DIR": str(d / ".claude-work-2")})["name"] == "claude-work-2"

# limit messages: "hit" and "reached" both count; the server's own throttling does not
assert ca.LIMIT_RE.search("You've reached your Fable limit. Run /usage-credits to continue")
assert not ca.LIMIT_RE.search("API Error: Server is temporarily limiting requests (not your usage limit)")

# live usage check: the latest reset among limits at 100%, None when all have room
import contextlib
import urllib.request
_script, _urlopen = ca.SCRIPT, urllib.request.urlopen
(d / "bin").mkdir()
(d / "bin/claude-token.sh").write_text("#!/bin/sh\nprintf tok\n")
(d / "bin/claude-token.sh").chmod(0o755)
ca.SCRIPT = d / "bin/claude-account"
soon, later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=h) for h in (2, 30))
usage = {"limits": [
    {"kind": "weekly_all", "percent": 40, "resets_at": later.isoformat()},
    {"kind": "weekly_scoped", "percent": 100, "resets_at": later.isoformat()},
    {"kind": "session", "percent": 100, "resets_at": soon.isoformat()},
    {"kind": "weekly_all", "percent": 100, "resets_at": "2020-01-01T00:00:00+00:00"},  # stale reading
]}
urllib.request.urlopen = lambda req, timeout: contextlib.nullcontext(io.BytesIO(json.dumps(usage).encode()))
assert ca.live_until(ca.by_name("claude-work")) == later.timestamp()
usage["limits"] = usage["limits"][3:]
assert ca.live_until(ca.by_name("claude-work")) is None
usage["limits"] = [{"kind": "weekly_all", "percent": 40, "resets_at": later.isoformat()}]
usage["limits"] = usage["limits"][:1]
assert ca.live_until(ca.by_name("claude-work")) is None
ca.SCRIPT, urllib.request.urlopen = _script, _urlopen

# pick: an unmarked account the live check finds used up is marked and skipped
_live = ca.live_until
ca.live_until = lambda a: time.time() + 600 if a["name"] == "claude-work" else None
assert ca.pick("work")["name"] == "claude-work-2"
assert ca._read_json(ca.STATE / "exhausted/claude-work.json")["text"].startswith("usage check:")
(ca.STATE / "exhausted/claude-work.json").unlink()
ca.live_until = _live

# status line: below 100% it clears only the marks it wrote, never a per-model limit
os.environ["CLAUDE_CONFIG_DIR"] = str(d / ".claude-work")
low = json.dumps({"rate_limits": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}})
for text, kept in (("You've reached your Fable limit.", True), ("status line: window at 100%", False)):
    ca._write_json(ca.STATE / "exhausted/claude-work.json", {"until": time.time() + 600, "text": text})
    sys.stdin = io.StringIO(low)
    ca.feed([])
    assert (ca.STATE / "exhausted/claude-work.json").exists() == kept, text
sys.stdin = sys.__stdin__
(ca.STATE / "exhausted/claude-work.json").unlink(missing_ok=True)
del os.environ["CLAUDE_CONFIG_DIR"]
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

# limit-hit: the hook marks the account, writes the handoff note with the spill account
# when its own pool is out, and announces; the kill step is skipped for an unknown tty
import io
import subprocess
import sys
os.environ["CLAUDE_ACCOUNT_TTY"] = "ttysTEST"
ca.notify = lambda text: None
for n in ("claude-personal", "claude-work", "claude-work-2", "claude-work-3"):
    (ca.STATE / f"exhausted/{n}.json").unlink(missing_ok=True)
ca._write_json(ca.STATE / "exhausted/claude-work-2.json", {"until": time.time() + 3600})
ca._write_json(ca.STATE / "exhausted/claude-work-3.json", {"until": time.time() + 3600})
payload = {"session_id": "s1", "cwd": "/tmp", "last_assistant_message": "You've hit your session limit · resets 11:59pm"}
os.environ["CLAUDE_CONFIG_DIR"] = str(d / ".claude-work")
sys.stdin = io.StringIO(json.dumps({**payload, "agent_id": "a1"}))
assert ca.limit_hit() == 0
assert not ca.exhausted_until("claude-work")  # a subagent's failure marks nothing
assert not ca.handoff_path("ttysTEST").exists()
sys.stdin = io.StringIO(json.dumps(payload))
assert ca.limit_hit() == 0
sys.stdin = sys.__stdin__
assert ca.exhausted_until("claude-work")
note = ca._read_json(ca.handoff_path("ttysTEST"))
assert note["from"] == "claude-work" and note["next"] == "claude-personal", note
assert "moved from claude-work to claude-personal" in ca.resume_message(note, ca.by_name("claude-personal"))
ca.handoff_path("ttysTEST").unlink()
del os.environ["CLAUDE_CONFIG_DIR"]
print("limit-hit self-check ok")

# reply window: the announcement lists every account with headroom, default first; a reply
# picks by number or name; a single option or no reply keeps the default
(ca.STATE / "exhausted/claude-work-3.json").unlink()
os.environ["CLAUDE_CONFIG_DIR"] = str(d / ".claude-work")
sys.stdin = io.StringIO(json.dumps(payload))
assert ca.limit_hit() == 0
sys.stdin = sys.__stdin__
del os.environ["CLAUDE_CONFIG_DIR"]
note = ca._read_json(ca.handoff_path("ttysTEST"))
assert note["next"] == "claude-work-3" and note["choices"] == ["claude-work-3", "claude-personal"], note
ca.handoff_path("ttysTEST").unlink()
ca._write_json(ca.STATE / "exhausted/claude-work-3.json", {"until": time.time() + 3600})
assert ca.parse_choice("2", ["a", "b"]) == "b" and ca.parse_choice(" B ", ["a", "b"]) == "b"
assert ca.parse_choice("3", ["a", "b"]) is None and ca.parse_choice("thanks", ["a", "b"]) is None
blob = b"\x08NSString\x01\x94\x84\x01+\x81" + (300).to_bytes(2, "little") + b"x" * 300 + b"\x86"
assert ca._typedstream_text(blob) == "x" * 300 and ca._typedstream_text(b"NSString\x01+\x02hi") == "hi"
assert ca._typedstream_text(b"NSString\x01") == "" and ca._typedstream_text(b"NSString+") == ""
assert "Reply" not in ca.choice_prompt(["a"]) and "1 a (default), 2 b" in ca.choice_prompt(["a", "b"])
assert ca.await_choice({"choices": ["a"], "created": time.time()}) is None
ca.imessage_replies = lambda since: ["sure", "2"]
assert ca.await_choice({"choices": ["claude-personal", "claude-work-3"], "created": time.time()})["name"] == "claude-work-3"
ca.imessage_replies = lambda since: []
ca.CHOICE_WINDOW = 1
assert ca.await_choice({"choices": ["claude-personal", "claude-work-3"], "created": time.time()}) is None
print("reply-window self-check ok")

# run loop: the stub Claude hits the limit on its first launch; the loop relaunches the same
# session on the spill account with the starting message first, then exits when no note follows
for n in ("claude-personal", "claude-work"):
    (ca.STATE / f"exhausted/{n}.json").unlink(missing_ok=True)
log = d / "launches.log"
(d / "payload.json").write_text(json.dumps(payload))
stub.write_text(
    "#!/bin/bash\n"
    f'echo "${{CLAUDE_CONFIG_DIR:-unset}}|$*" >> "{log}"\n'
    f'if [ "$(wc -l < "{log}" | tr -d " ")" = 1 ]; then\n'
    f"  \"{REPO / 'scripts' / 'claude-account'}\" limit-hit < \"{d / 'payload.json'}\"\n"
    "fi\nexit 0\n")
ca.my_tty = lambda: "ttysTEST"
sys.stdin = io.StringIO("")
assert ca.run("work", ["--permission-mode", "acceptEdits"]) == 0
sys.stdin = sys.__stdin__
def launches():
    return [l for l in log.read_text().splitlines() if l.startswith(("unset|", f"{d / '.claude-work'}|"))]
assert launches()[0] == f"{d / '.claude-work'}|--permission-mode acceptEdits", launches()
assert launches()[1].startswith("unset|[claude-account] This conversation moved from claude-work to claude-personal"), launches()
assert log.read_text().rstrip().endswith("--resume s1 --permission-mode acceptEdits"), log.read_text()
assert len(launches()) == 2, launches()

# two accounts have headroom: without a reply the loop takes the default after the window;
# a reply naming the other account relaunches there instead
for reply, moved_to in (([], "claude-work-3"), (["2"], "claude-personal")):
    log.unlink()
    for n in ("claude-personal", "claude-work", "claude-work-3"):
        (ca.STATE / f"exhausted/{n}.json").unlink(missing_ok=True)
    ca.imessage_replies = lambda since, reply=reply: reply
    sys.stdin = io.StringIO("")
    assert ca.run("work", []) == 0
    sys.stdin = sys.__stdin__
    assert f"This conversation moved from claude-work to {moved_to}" in log.read_text(), log.read_text()
ca.imessage_replies = lambda since: []
ca._write_json(ca.STATE / "exhausted/claude-work-3.json", {"until": time.time() + 3600})
print("reply-window run-loop self-check ok")

# every account out: the loop sleeps until the earliest reset, then relaunches
log.unlink()
(ca.STATE / "exhausted/claude-work.json").unlink()
_sleep = time.sleep
time.sleep = lambda s: _sleep(min(s, 4))  # the loop's 60 s floor would only slow the check
ca._write_json(ca.STATE / "exhausted/claude-personal.json", {"until": time.time() + 3})
ca._write_json(ca.STATE / "exhausted/claude-work-2.json", {"until": time.time() + 3600})
ca._write_json(ca.STATE / "exhausted/claude-work-3.json", {"until": time.time() + 3600})
t0 = time.time()
sys.stdin = io.StringIO("")
assert ca.run("work", []) == 0
sys.stdin = sys.__stdin__
assert launches()[0].startswith(str(d / ".claude-work") + "|") and launches()[1].startswith("unset|[claude-account]"), launches()
assert time.time() - t0 >= 3, "should have waited for the personal reset"
print("run-loop self-check ok")

# auth: runs directly on the caller's directory even when the pool would pick another
auth_stub = d / "claude-auth-stub"
auth_stub.write_text('#!/bin/bash\necho "${CLAUDE_CONFIG_DIR:-unset}|$*"\n')
auth_stub.chmod(0o755)
for n in ("claude-personal", "claude-work"):
    (ca.STATE / f"exhausted/{n}.json").unlink(missing_ok=True)
r = subprocess.run([str(REPO / "scripts" / "claude-account"), "run", "auto", "--", "auth", "login"],
                   env={**os.environ, "CLAUDE_ACCOUNT_BIN": str(auth_stub), "CLAUDE_CONFIG_DIR": str(d / ".claude-work-2")},
                   capture_output=True, text=True, check=True)
assert r.stdout.strip() == f"{d / '.claude-work-2'}|auth login", r.stdout
print("auth pass-through self-check ok")
