#!/usr/bin/env python3
"""Self-check for scripts/distill-codex-memory.py (issue #21). Builds a
scratch memories_1.sqlite with the REAL Codex schema (confirmed against the
live ~/.codex/memories_1.sqlite, which has 0 rows) and proves: a row exports
to a one-file-per-fact note + MEMORY.md index line, a second run is a no-op,
and a changed source_updated_at re-exports. Run: python3 test_distill_codex_memory.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE stage1_outputs (
    thread_id TEXT PRIMARY KEY,
    source_updated_at INTEGER NOT NULL,
    raw_memory TEXT NOT NULL,
    rollout_summary TEXT NOT NULL,
    rollout_slug TEXT,
    generated_at INTEGER NOT NULL,
    usage_count INTEGER,
    last_usage INTEGER,
    selected_for_phase2 INTEGER NOT NULL DEFAULT 0,
    selected_for_phase2_source_updated_at INTEGER
);
"""


def _make_db(path, thread_id="thread-abc-123", source_updated_at=1000,
             raw_memory="Nick prefers tabs over spaces in Go files.",
             rollout_summary="Editor preference discussion"):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "insert into stage1_outputs (thread_id, source_updated_at, raw_memory, rollout_summary, generated_at) "
        "values (?, ?, ?, ?, ?)",
        (thread_id, source_updated_at, raw_memory, rollout_summary, source_updated_at))
    con.commit()
    con.close()


def _run(home, store):
    env = dict(os.environ, HOME=str(home), AGENT_HOME=str(store))
    return subprocess.run([sys.executable, str(REPO / "scripts/distill-codex-memory.py")],
                           cwd=REPO, env=env, capture_output=True, text=True)


def test_export_creates_note_and_index_line():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-codexmem-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    (store / "memory").mkdir(parents=True)
    (store / "memory" / "MEMORY.md").write_text("# Memory Index\n")
    _make_db(home / ".codex" / "memories_1.sqlite")

    r = _run(home, store)
    assert r.returncode == 0, r.stderr
    assert "exported" in r.stdout, r.stdout

    notes = list((store / "memory").glob("codex-memory-*.md"))
    assert len(notes) == 1, notes
    text = notes[0].read_text()
    assert "threadId: thread-abc-123" in text
    assert "Nick prefers tabs over spaces in Go files." in text
    assert "description: Editor preference discussion" in text

    index = (store / "memory" / "MEMORY.md").read_text()
    assert f"]({notes[0].name})" in index

    r2 = _run(home, store)
    assert r2.returncode == 0, r2.stderr
    assert "0 note(s)" in r2.stdout or "nothing new" in r2.stdout, r2.stdout
    notes_after = list((store / "memory").glob("codex-memory-*.md"))
    assert len(notes_after) == 1  # no duplicate note
    index_after = (store / "memory" / "MEMORY.md").read_text()
    assert index_after.count(f"]({notes[0].name})") == 1  # no duplicate index line

    shutil.rmtree(scratch)


def test_changed_row_reexports():
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-codexmem-update-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    (store / "memory").mkdir(parents=True)
    db = home / ".codex" / "memories_1.sqlite"
    _make_db(db, thread_id="thread-x", source_updated_at=1, raw_memory="first version")
    r1 = _run(home, store)
    assert r1.returncode == 0, r1.stderr

    con = sqlite3.connect(db)
    con.execute("update stage1_outputs set source_updated_at = 2, raw_memory = 'second version' where thread_id = 'thread-x'")
    con.commit()
    con.close()

    r2 = _run(home, store)
    assert r2.returncode == 0, r2.stderr
    assert "exported" in r2.stdout, r2.stdout  # re-exported: source_updated_at changed
    notes = list((store / "memory").glob("codex-memory-*.md"))
    assert len(notes) == 1
    assert "second version" in notes[0].read_text()
    shutil.rmtree(scratch)


def test_live_schema_zero_rows_is_a_noop():
    """Sanity check against the SAME schema the live ~/.codex/memories_1.sqlite
    uses, with 0 rows — the exporter must do nothing, not error."""
    scratch = Path(tempfile.mkdtemp(prefix="agent-home-codexmem-empty-"))
    home, store = scratch / "home", scratch / "store"
    home.mkdir()
    (store / "memory").mkdir(parents=True)
    db = home / ".codex" / "memories_1.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.commit()
    con.close()

    r = _run(home, store)
    assert r.returncode == 0, r.stderr
    assert "0 note(s)" in r.stdout, r.stdout
    assert list((store / "memory").glob("codex-memory-*.md")) == []
    shutil.rmtree(scratch)


if __name__ == "__main__":
    test_export_creates_note_and_index_line()
    test_changed_row_reexports()
    test_live_schema_zero_rows_is_a_noop()
    print("distill-codex-memory self-check: PASS")
