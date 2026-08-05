#!/usr/bin/env python3
"""Codex → cortex session distillation. Claude Code distills via the cortex
plugin's SessionEnd hook and opencode via the session-distill plugin; Codex has
no hook system, so this sweep covers it: any session rollout quiet for 10+
minutes and not yet distilled is flattened to a user/assistant transcript and
POSTed to the brain. Same env contract, kill switch, and triviality thresholds
as the other two paths. Run by resync.sh; exits silently when CORTEX_BRAIN_URL
is unset (same as hooks/session_stop.sh).
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent))
import sync
from history import _codex_extract, _jsonl_turns

BRAIN = os.environ.get("CORTEX_BRAIN_URL", "").rstrip("/")
TOKEN = os.environ.get("CORTEX_API_TOKEN") or os.environ.get("API_TOKEN", "")
QUIET_S = int(os.environ.get("CORTEX_DISTILL_QUIET_MS", "600000")) // 1000
MIN_TURNS, MIN_CHARS = 6, 8_000  # mirrors cortex_brain.ingestion.session_distill
STAMP = sync.CANON / ".distill-codex.json"


def main():
    if not BRAIN or os.environ.get("CORTEX_SESSION_LOG_AUTO", "1").lower() in ("0", "false"):
        return
    try:
        stamps = json.load(open(STAMP))
    except (OSError, json.JSONDecodeError):
        stamps = {}
    now = time.time()
    for home in sync.codex_homes():
        for src in sorted(Path(home).glob("sessions/**/*.jsonl")):
            st = src.stat()
            if now - st.st_mtime < QUIET_S:
                continue  # session may still be running
            if stamps.get(str(src)) == st.st_size:
                continue  # already handled at this length
            turns = _jsonl_turns(src, _codex_extract)
            transcript = "\n\n".join(f"{r}: {t.strip()}" for r, t in turns if t.strip())
            if len(turns) < MIN_TURNS or len(transcript) < MIN_CHARS:
                stamps[str(src)] = st.st_size  # trivial; don't rescan forever
                continue
            req = urllib.request.Request(
                f"{BRAIN}/v1/session/distill",
                data=json.dumps({"transcript": transcript, "turn_count": len(turns)}).encode(),
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=30)
                stamps[str(src)] = st.st_size
                print(f"distilled codex session {src.stem}")
            except OSError as e:
                print(f"  ! distill failed for {src.name}: {e}", file=sys.stderr)
    json.dump(stamps, open(STAMP, "w"))


if __name__ == "__main__":
    main()
