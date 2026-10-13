#!/usr/bin/env python3
"""Self-check for scripts/sync-memory-to-cortex.py. Runs the script against a
local fake cortex and proves: files are deposited under a path-derived id,
MEMORY.md and credential-shaped files are never sent, an unchanged file is not
re-sent, an edit re-sends under the same id, and a deleted file is retired.
Run: python3 test_sync_memory_to_cortex.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "scripts" / "sync-memory-to-cortex.py"
CALLS = []


class Fake(BaseHTTPRequestHandler):
    def _record(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        CALLS.append((self.command, self.path, body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_DELETE = _record

    def log_message(self, *args):
        pass


def run(env):
    CALLS.clear()
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def main():
    server = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mem = tmp / "memory"
        mem.mkdir()
        (mem / "MEMORY.md").write_text("- [a](a.md)\n")
        (mem / "a.md").write_text("---\nname: a\nmetadata:\n  type: project\n---\nfirst\n")
        (mem / "leak.md").write_text("OPENAI_API_KEY=abcdefghijklmnop1234\n")
        env = dict(
            os.environ,
            MEMORY_DIR=str(mem),
            CORTEX_MEMORY_STATE=str(tmp / "state.json"),
            CORTEX_BRAIN_URL=f"http://127.0.0.1:{server.server_port}",
            CORTEX_API_TOKEN="t",
        )

        run(env)
        assert [(m, p) for m, p, _ in CALLS] == [("POST", "/v1/deposit")], CALLS
        body = CALLS[0][2]
        assert body["ids"] == {"url": "agent-memory/a.md"}
        assert body["title"] == "a" and body["folder"] == "claude-memory"
        assert "memory-type:project" in body["tags"]

        run(env)
        assert CALLS == [], "unchanged file must not be re-sent"

        (mem / "a.md").write_text("---\nname: a\n---\nsecond\n")
        run(env)
        assert [(m, p) for m, p, _ in CALLS] == [("POST", "/v1/deposit")]
        assert CALLS[0][2]["ids"] == {"url": "agent-memory/a.md"}
        assert "second" in CALLS[0][2]["markdown"]

        (mem / "a.md").unlink()
        run(env)
        assert [(m, p) for m, p, _ in CALLS] == [
            ("DELETE", "/v1/resources/url:agent-memory/a.md")
        ], CALLS
        run(env)
        assert CALLS == [], "retired file must not be retired twice"
    print("ok")


if __name__ == "__main__":
    main()
