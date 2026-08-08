#!/usr/bin/env python3
"""Codex native memory exporter. Codex's own memory feature writes durable
facts into each codex_home's memories_*.sqlite (table stage1_outputs:
thread_id, raw_memory, rollout_summary, source_updated_at, ...) — invisible
to every other harness unless exported. This flattens each row into a
one-file-per-fact markdown note in ~/.agent-home/memory/ (the same
frontmatter shape the remember plugin writes) plus an index line in
MEMORY.md. Decision: export, don't disable — durable facts must never live
only in a harness-native memory feature.

Idempotent the same way distill-codex.py is (see its STAMP dict, lines 27,
43-48): a persisted stamp keyed off what changed. distill-codex.py stamps a
whole session file by byte size because one file is one session; here one
sqlite file holds many facts, so the natural per-item granularity is a
(db path, thread_id) pair stamped with that row's source_updated_at — same
"skip if unchanged since last export" idea, applied at the level that
actually varies per fact instead of per file.

Run by resync.sh.
"""
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent))
import sync

MEMORY_DIR = sync.CANON / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
STAMP = sync.CANON / ".distill-codex-memory.json"


def _slug(thread_id):
    s = re.sub(r"[^a-z0-9]+", "-", thread_id.lower()).strip("-")
    return f"codex-memory-{s[:40]}"


def _iso(epoch):
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (TypeError, ValueError, OSError):
        return ""


def _rows(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        return con.execute(
            "select thread_id, raw_memory, rollout_summary, source_updated_at from stage1_outputs"
        ).fetchall()
    finally:
        con.close()


def write_note(row):
    """One stage1_outputs row -> a store markdown note + MEMORY.md index
    line. Returns the note's slug (without .md)."""
    thread_id, raw, summary = row["thread_id"], row["raw_memory"], row["rollout_summary"]
    slug = _slug(thread_id)
    desc = (summary or raw or thread_id).strip().splitlines()[0][:200]
    modified = _iso(row["source_updated_at"])
    note = MEMORY_DIR / f"{slug}.md"
    note.write_text(
        "---\n"
        f"name: {slug}\n"
        f"description: {desc}\n"
        "metadata: \n"
        "  node_type: memory\n"
        "  type: project\n"
        "  source: codex-native-memory\n"
        f"  threadId: {thread_id}\n"
        + (f"  modified: {modified}\n" if modified else "")
        + "---\n\n"
        f"{raw.strip()}\n"
    )
    have = MEMORY_INDEX.read_text() if MEMORY_INDEX.exists() else "# Memory Index\n"
    if f"]({slug}.md)" not in have:
        line = f"- [{desc}]({slug}.md) — exported from Codex native memory ({thread_id[:12]})"
        MEMORY_INDEX.write_text(have.rstrip() + "\n" + line + "\n")
    return slug


def main():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        stamps = json.load(open(STAMP))
    except (OSError, json.JSONDecodeError):
        stamps = {}
    exported = 0
    for home in sync.codex_homes():
        for db in sorted(Path(home).glob("memories_*.sqlite")):
            try:
                rows = _rows(db)
            except sqlite3.Error as e:
                print(f"  ! {db}: {e}", file=sys.stderr)
                continue
            for row in rows:
                key = f"{db}:{row['thread_id']}"
                if stamps.get(key) == row["source_updated_at"]:
                    continue  # already exported at this version
                slug = write_note(row)
                stamps[key] = row["source_updated_at"]
                exported += 1
                print(f"  exported {row['thread_id'][:12]} -> memory/{slug}.md")
    json.dump(stamps, open(STAMP, "w"))
    print(f"codex memory export: {exported} note(s)" + (" (nothing new)" if not exported else ""))


if __name__ == "__main__":
    main()
