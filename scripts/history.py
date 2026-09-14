#!/usr/bin/env python3
"""Cross-harness transcript index: pull past sessions from every harness into
~/.agent-home/history/ as plain markdown, so any agent can answer "what did we
decide about X last week?" no matter which harness the conversation happened in.

  ./history.py index            (re)index — incremental, skips unchanged sources
  ./history.py search <query>   case-insensitive regex over the indexed history
  ./history.py latest           newest transcript, any harness -> ~/.agent-home/handoff-auto.md
  ./history.py handoffs [--deliver [cwd]]
                                index open per-session handoffs -> ~/.agent-home/handoffs/INDEX.md;
                                --deliver also prints the ones for this cwd (session-start hook)

Sources: Claude Code project transcripts (every account's CLAUDE_CONFIG_DIR),
Codex CLI session rollouts (every CODEX_HOME), opencode's sqlite store,
cursor-agent transcripts (~/.cursor/projects/*/agent-transcripts/).
Best-effort by design: a source that's missing or unreadable is skipped.
"""
import json
import os
import re
import sqlite3
import sys
import time
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


def _cursor_extract(rec):
    # {"role": "user"|"assistant", "message": {"content": [{"type":"text",...}, ...]}}
    role = rec.get("role")
    if role not in ("user", "assistant"):
        return []
    msg = rec.get("message") or {}
    return [(role, t) for t in _texts(msg.get("content"))]


def _cursor_transcripts():
    """~/.cursor/projects/<project>/agent-transcripts/<chatId>/<chatId>.jsonl —
    one file per chat, single profile (no per-account CONFIG_DIR concept for
    cursor-agent, unlike Claude/Codex)."""
    return sorted((Path.home() / ".cursor/projects").glob("*/agent-transcripts/*/*.jsonl"))


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

    # cursor-agent: one jsonl transcript per chat
    for src in _cursor_transcripts():
        if src.stat().st_size > MAX_SRC_BYTES or not fresh(src):
            skipped += 1
            continue
        dest = HIST / "cursor" / f"{src.stem}.md"
        done += _write_session(dest, f"cursor session {src.stem}",
                               _jsonl_turns(src, _cursor_extract))

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


def _opencode_latest_session():
    """(mtime, header, turns) for the newest opencode session, or None."""
    db = Path.home() / ".local/share/opencode/opencode.db"
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        row = con.execute(
            "select m.session_id, max(m.time_created) from message m"
            " join part p on p.message_id = m.id"
            " where json_extract(p.data,'$.type')='text' group by m.session_id"
            " order by 2 desc limit 1").fetchone()
        if not row:
            con.close()
            return None
        sid, ts_ms = row
        rows = con.execute(
            "select json_extract(m.data,'$.role'), p.data from message m"
            " join part p on p.message_id = m.id"
            " where m.session_id=? and json_extract(p.data,'$.type')='text'"
            " order by m.time_created, p.time_created", (sid,)).fetchall()
        con.close()
    except sqlite3.Error:
        return None
    turns = [(role, json.loads(pdata).get("text", "")) for role, pdata in rows
             if role in ("user", "assistant") and json.loads(pdata).get("text", "").strip()]
    return ts_ms / 1000, f"opencode session {sid}", turns


def latest():
    """Newest transcript across every harness -> ~/.agent-home/handoff-auto.md
    (last ~30 turns, generated-at + source-harness header). Claude Code
    flushes its transcript live, so this reflects a session still in progress."""
    candidates = []  # (mtime, header, lazy turns getter) — only the winner reads its content

    claude_dirs = {Path.home() / ".claude", Path.home() / ".claude-work"}
    claude_dirs |= {Path(a["config_dir"]).expanduser() for a in sync._accounts()
                    if a.get("provider", "anthropic-sub") == "anthropic-sub" and a.get("config_dir")}
    for cdir in claude_dirs:
        for src in cdir.glob("projects/*/*.jsonl"):
            st = src.stat()
            if st.st_size > MAX_SRC_BYTES:
                continue
            candidates.append((st.st_mtime, f"claude session {src.stem} ({src.parent.name})",
                                lambda src=src: _jsonl_turns(src, _claude_extract)))

    for home in sync.codex_homes():
        for src in Path(home).glob("sessions/**/*.jsonl"):
            st = src.stat()
            if st.st_size > MAX_SRC_BYTES:
                continue
            candidates.append((st.st_mtime, f"codex session {src.stem}",
                                lambda src=src: _jsonl_turns(src, _codex_extract)))

    for src in _cursor_transcripts():
        st = src.stat()
        if st.st_size > MAX_SRC_BYTES:
            continue
        candidates.append((st.st_mtime, f"cursor session {src.stem}",
                            lambda src=src: _jsonl_turns(src, _cursor_extract)))

    oc = _opencode_latest_session()
    if oc:
        oc_mtime, oc_header, oc_turns = oc
        candidates.append((oc_mtime, oc_header, lambda t=oc_turns: t))

    if not candidates:
        print("history latest: no transcripts found")
        return

    mtime, header, get_turns = max(candidates, key=lambda c: c[0])
    turns = get_turns()[-30:]
    dest = sync.CANON / "handoff-auto.md"
    lines = [f"# auto-handoff (generated {time.strftime('%F %T')}, source: {header})", ""]
    for role, text in turns:
        lines.append(f"**{role}**: {text.strip()[:MAX_TURN_CHARS]}\n")
    dest.write_text("\n".join(lines))
    print(f"history latest: {len(turns)} turn(s) from {header} -> {dest}")


HANDOFFS = sync.CANON / "handoffs"


def _handoff_meta(path):
    """(meta, body) from a handoff file. The header is `key: value` lines
    between `---` markers; session id defaults to the filename, status to open."""
    text = path.read_text(errors="replace")
    meta, body = {}, text
    if text.startswith("---"):
        head, sep, rest = text[3:].partition("\n---")
        if sep:
            body = rest
            for line in head.splitlines():
                k, colon, v = line.partition(":")
                if colon:
                    meta[k.strip()] = v.strip()
    meta.setdefault("session", path.stem)
    meta.setdefault("status", "open")
    return meta, body.strip()


def _open_handoffs():
    items = []
    for f in sorted(HANDOFFS.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        meta, body = _handoff_meta(f)
        if meta["status"] == "open":
            items.append((f, meta, body))
    items.sort(key=lambda i: i[1].get("updated", ""), reverse=True)
    return items


def handoffs(deliver_cwd=None):
    """Open handoffs -> handoffs/INDEX.md, grouped by cwd, newest first.
    With deliver_cwd, also print every open handoff whose cwd is that folder,
    a parent of it, or inside it (worktrees), for a session-start hook."""
    HANDOFFS.mkdir(parents=True, exist_ok=True)
    items = _open_handoffs()
    by_cwd = {}
    for f, meta, body in items:
        by_cwd.setdefault(meta.get("cwd", "?"), []).append((f, meta))
    lines = [f"# Open handoffs (generated {time.strftime('%F %T')}; regenerated by `history.py handoffs`)", ""]
    for cwd in sorted(by_cwd):
        lines.append(f"## {cwd}")
        for f, meta in by_cwd[cwd]:
            lines.append(f"- {meta.get('topic', f.stem)} — updated {meta.get('updated', '?')}"
                         f" — {meta.get('harness', '?')} — `{f.name}`")
        lines.append("")
    (HANDOFFS / "INDEX.md").write_text("\n".join(lines))
    if deliver_cwd is None:
        print(f"history handoffs: {len(items)} open -> {HANDOFFS / 'INDEX.md'}")
        return
    if not items:
        return
    here = Path(deliver_cwd).resolve()

    def related(cwd):
        p = Path(cwd).expanduser().resolve() if cwd else None
        return p is not None and (p == here or p in here.parents or here in p.parents)

    mine = [(f, meta, body) for f, meta, body in items if related(meta.get("cwd"))]
    if mine:
        print(f"=== OPEN HANDOFFS for {here} ({len(mine)}). If one matches the ask, say you are"
              f" resuming from it; close it with `/handoff done` when the work is finished. ===")
        for f, meta, body in mine:
            print(f"\n--- {meta.get('topic', f.stem)} | session {meta['session']} | {meta.get('harness', '?')}"
                  f" | updated {meta.get('updated', '?')} | {f}")
            print(body)
    others = len(items) - len(mine)
    if others:
        print(f"\n({others} other open handoff(s) in other folders: {HANDOFFS / 'INDEX.md'})")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        if len(sys.argv) < 3:
            sys.exit("usage: history.py search <query>")
        search(" ".join(sys.argv[2:]))
    elif len(sys.argv) > 1 and sys.argv[1] == "latest":
        latest()
    elif len(sys.argv) > 1 and sys.argv[1] == "handoffs":
        if "--deliver" in sys.argv:
            rest = [a for a in sys.argv[2:] if a != "--deliver"]
            cwd = rest[0] if rest else None
            if cwd is None and not sys.stdin.isatty():
                # Claude Code session-start hooks pass {"cwd": ..., "session_id": ...} on stdin
                try:
                    cwd = json.loads(sys.stdin.read() or "{}").get("cwd")
                except json.JSONDecodeError:
                    cwd = None
            handoffs(cwd or os.getcwd())
        else:
            handoffs()
    else:
        index()
