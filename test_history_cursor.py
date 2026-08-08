#!/usr/bin/env python3
"""Self-check for scripts/history.py's cursor-agent transcript reader
(issue #23): _cursor_extract's role filtering and text extraction, on the
same rec shape real ~/.cursor/projects/*/agent-transcripts/*.jsonl files use.
Run: python3 test_history_cursor.py"""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("history", REPO / "scripts" / "history.py")
hist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hist)


def test_extracts_user_and_assistant_text():
    rec = {"role": "user", "message": {"content": [{"type": "text", "text": "fix the CI"}]}}
    assert hist._cursor_extract(rec) == [("user", "fix the CI")]


def test_ignores_tool_use_blocks():
    rec = {"role": "assistant", "message": {"content": [
        {"type": "text", "text": "investigating"},
        {"type": "tool_use", "name": "Glob", "input": {"glob_pattern": "**/*.yml"}},
    ]}}
    assert hist._cursor_extract(rec) == [("assistant", "investigating")]


def test_ignores_non_user_assistant_roles():
    assert hist._cursor_extract({"role": "system", "message": {"content": [{"type": "text", "text": "x"}]}}) == []


def test_empty_content_list_yields_no_turn():
    assert hist._cursor_extract({"role": "user", "message": {"content": []}}) == []


def test_missing_message_is_safe():
    assert hist._cursor_extract({"role": "user"}) == []


if __name__ == "__main__":
    test_extracts_user_and_assistant_text()
    test_ignores_tool_use_blocks()
    test_ignores_non_user_assistant_roles()
    test_empty_content_list_yields_no_turn()
    test_missing_message_is_safe()
    print("history cursor self-check: PASS")
