#!/usr/bin/env python3
"""Mirror ~/.agent-home/memory into cortex as searchable notes.

Each memory file becomes one cortex note whose id is derived from the file's
path (url:agent-memory/<relative path>), so an edit replaces the earlier text
in place and a deleted file retires its note. MEMORY.md, the index, is not
mirrored, nor is a symlink or a file written by an automatic extractor
(UNTRUSTED_SOURCES). A file whose text looks like it holds a credential is
never sent. A withheld file's cortex copy, if any, is retired.

Notes land in the claude-memory folder with no origin URL. Cortex treats that
combination as an agent's own writing (trusted by the per-message lookup,
labelled "agent note", never an owner fact) and keeps it out of automatic fact
extraction.

State lives in .cortex-memory-sync.json beside the memory folder: a map from
relative path to the sha256 of the text last accepted by cortex. Run by
resync.sh. Needs CORTEX_BRAIN_URL and CORTEX_API_TOKEN; without them, or when
the box is unreachable, it reports and exits 0 so the rest of resync is
unaffected. Standard library only.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STORE = Path(os.environ.get("AGENT_HOME", Path.home() / ".agent-home"))
MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", STORE / "memory"))
STATE = Path(os.environ.get("CORTEX_MEMORY_STATE", STORE / ".cortex-memory-sync.json"))
FOLDER = "claude-memory"
ID_PREFIX = "agent-memory/"
TIMEOUT_S = 60

SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\."
    r"|\bbearer\s+[A-Za-z0-9._~+/-]{20,}"
    r"|\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{6,}@"
    r"|[A-Za-z0-9_]*(?:key|token|secret|password|passwd|credential)[A-Za-z0-9_]*"
    r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}",
    re.I,
)
# Written by a model reading its own sessions, which may quote outside content;
# cortex would label these trusted agent notes, so they stay out.
UNTRUSTED_SOURCES = {"codex-native-memory"}


def canonical_id(rel):
    return f"url:{ID_PREFIX}{rel}"


def frontmatter(text):
    """The name and metadata.type of a memory file's YAML header, '' when absent."""
    head = re.match(r"---\n(.*?)\n---\n", text, re.S)
    block = head.group(1) if head else ""
    name = re.search(r"^name:\s*(.+)$", block, re.M)
    kind = re.search(r"^\s+type:\s*(\S+)", block, re.M)
    return (name.group(1).strip() if name else ""), (kind.group(1) if kind else "")


def source(text):
    """The metadata.source of a memory file's YAML header, '' when absent."""
    head = re.match(r"---\n(.*?)\n---\n", text, re.S)
    found = re.search(r"^\s+source:\s*(\S+)", head.group(1), re.M) if head else None
    return found.group(1) if found else ""


def call(method, path, body=None):
    url = os.environ["CORTEX_BRAIN_URL"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['CORTEX_API_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.status


def deposit(rel, text):
    name, kind = frontmatter(text)
    call(
        "POST",
        "/v1/deposit",
        {
            "source_type": "note",
            "markdown": text,
            "title": name or Path(rel).stem,
            "ids": {"url": ID_PREFIX + rel},
            "folder": FOLDER,
            "tags": ["agent-memory"] + ([f"memory-type:{kind}"] if kind else []),
        },
    )


def retire(rel):
    """Delete the cortex copy; a note cortex no longer has counts as retired."""
    try:
        call("DELETE", "/v1/resources/" + urllib.parse.quote(canonical_id(rel), safe=":/"))
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise


def main():
    if not (os.environ.get("CORTEX_BRAIN_URL") and os.environ.get("CORTEX_API_TOKEN")):
        print("memory->cortex: CORTEX_BRAIN_URL/CORTEX_API_TOKEN unset, skipping")
        return 0
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    sent = retired = skipped = failed = 0
    files = {}
    root = MEMORY_DIR.resolve()
    for path in sorted(MEMORY_DIR.rglob("*.md")):
        rel = path.relative_to(MEMORY_DIR).as_posix()
        if rel == "MEMORY.md" or path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if source(text) in UNTRUSTED_SOURCES:
            skipped += 1
            print(f"memory->cortex: withheld {rel} (source {source(text)})")
            continue
        if SECRET.search(text):
            skipped += 1
            print(f"memory->cortex: withheld {rel} (credential-shaped text)")
            continue
        files[rel] = text
    reachable = True
    for rel, text in files.items():
        digest = hashlib.sha256(text.encode()).hexdigest()
        if state.get(rel) == digest:
            continue
        try:
            deposit(rel, text)
        except (urllib.error.URLError, OSError) as err:
            failed += 1
            print(f"memory->cortex: {rel}: {err}")
            if not isinstance(err, urllib.error.HTTPError):
                reachable = False  # box unreachable; retry on the next pass
                break
            continue
        state[rel] = digest
        sent += 1
    for rel in sorted(set(state) - set(files)) if reachable else []:
        try:
            retire(rel)
        except (urllib.error.URLError, OSError) as err:
            failed += 1
            print(f"memory->cortex: retire {rel}: {err}")
            continue
        del state[rel]
        retired += 1
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
    print(
        f"memory->cortex: sent {sent}, retired {retired}, withheld {skipped}, "
        f"failed {failed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
