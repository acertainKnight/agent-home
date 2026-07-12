#!/usr/bin/env python3
"""Cross-harness transcript index: pull past sessions from every harness into
~/.agent-home/history/ as plain markdown, so any agent can answer "what did we
decide about X last week?" no matter which harness the conversation happened in.

  ./history.py index            (re)index — incremental, skips unchanged sources
  ./history.py search <query>   case-insensitive regex over the indexed history

Sources: Claude Code project transcripts (every account's CLAUDE_CONFIG_DIR),
Codex CLI session rollouts (every CODEX_HOME), opencode's sqlite store.
Best-effort by design: a source that's missing or unreadable is skipped.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sync

HIST = sync.CANON / "history"
STAMPS = HIST / ".stamps.json"
MAX_SRC_BYTES = 50_000_000  # skip pathological transcript files
MAX_TURN_CHARS = 2000


def _stamps():
    try:
        return json.load(open(STAMPS))
    except (OSError, json.JSONDecodeError):
        return {}


def _texts(content):
    """Plain text out of a message content field (string or block list)."""
    if isinstance(content, str):
        return [content] if content.strip() else []
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("text") and b.get("type") in ("text", "input_text", "output_text"):
                out.append(b["text"])
    return out


def _write_session(dest, header, turns):
    """turns = [(role, text)]; skip empty sessions."""
    if not turns:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {header}", ""]
    for role, text in turns:
        text = text.strip()[:MAX_TURN_CHARS]
        lines.append(f"**{role}**: {text}\n")
    dest.write_text("\n".join(lines))
    return True


def _jsonl_turns(path, extract):
    turns = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        turns += extract(rec)
    return turns


def _claude_extract(rec):
    if rec.get("type") not in ("user", "assistant") or rec.get("isMeta"):
        return []
    msg = rec.get("message") or {}
    return [(rec["type"], t) for t in _texts(msg.get("content"))]


def _codex_extract(rec):
    # rollout lines vary by version; accept anything message-shaped with a role
    payload = rec.get("payload", rec)
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return []
    role = payload.get("role")
    if role not in ("user", "assistant"):
        return []
    return [(role, t) for t in _texts(payload.get("content"))]


def index():
    HIST.mkdir(parents=True, exist_ok=True)
    stamps, done, skipped = _stamps(), 0, 0

    def fresh(src):
        st = src.stat()
        key = str(src)
        if stamps.get(key) == [st.st_mtime, st.st_size]:
            return False
        stamps[key] = [st.st_mtime, st.st_size]
        return True

    # Claude Code: every anthropic-sub account's config dir (+ the defaults)
    claude_dirs = {Path.home() / ".claude", Path.home() / ".claude-work"}
    claude_dirs |= {Path(a["config_dir"]).expanduser() for a in sync._accounts()
                    if a.get("provider", "anthropic-sub") == "anthropic-sub" and a.get("config_dir")}
    for cdir in claude_dirs:
        for src in sorted(cdir.glob("projects/*/*.jsonl")):
            if src.stat().st_size > MAX_SRC_BYTES or not fresh(src):
                skipped += 1
                continue
            dest = HIST / "claude" / f"{src.parent.name}--{src.stem}.md"
            done += _write_session(dest, f"claude session {src.stem} ({src.parent.name})",
                                   _jsonl_turns(src, _claude_extract))

    # Codex CLI: session rollouts per CODEX_HOME
    for home in sync.codex_homes():
        for src in sorted(Path(home).glob("sessions/**/*.jsonl")):
            if src.stat().st_size > MAX_SRC_BYTES or not fresh(src):
                skipped += 1
                continue
            dest = HIST / "codex" / f"{src.stem}.md"
            done += _write_session(dest, f"codex session {src.stem}",
                                   _jsonl_turns(src, _codex_extract))

    # opencode: sqlite (message.data has role; part.data has the text blocks)
    db = Path.home() / ".local/share/opencode/opencode.db"
    if db.exists() and fresh(db):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            rows = con.execute(
                "select m.session_id, json_extract(m.data,'$.role'), p.data"
                " from message m join part p on p.message_id = m.id"
                " where json_extract(p.data,'$.type')='text'"
                " order by m.session_id, m.time_created, p.time_created").fetchall()
            con.close()
            sessions = {}
            for sid, role, pdata in rows:
                if role in ("user", "assistant"):
                    text = json.loads(pdata).get("text", "")
                    if text.strip():
                        sessions.setdefault(sid, []).append((role, text))
            for sid, turns in sessions.items():
                done += _write_session(HIST / "opencode" / f"{sid}.md", f"opencode session {sid}", turns)
        except sqlite3.Error as e:
            print(f"  ! opencode db unreadable ({e}); skipped", file=sys.stderr)

    json.dump(stamps, open(STAMPS, "w"))
    print(f"history: {done} session(s) indexed, {skipped} unchanged → {HIST}")


def search(query):
    try:
        pat = re.compile(query, re.IGNORECASE)
    except re.error as e:
        sys.exit(f"bad regex {query!r}: {e}")
    hits = 0
    for f in sorted(HIST.rglob("*.md")):
        for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if pat.search(line):
                print(f"{f.relative_to(HIST)}:{i}: {line.strip()[:200]}")
                hits += 1
                if hits >= 50:
                    print("… (50-hit cap; narrow the query)")
                    return
    if not hits:
        print(f"no matches for {query!r} in {HIST} (run 'index' first?)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        if len(sys.argv) < 3:
            sys.exit("usage: history.py search <query>")
        search(" ".join(sys.argv[2:]))
    else:
        index()
