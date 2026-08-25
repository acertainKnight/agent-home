#!/usr/bin/env python3
"""Self-check for the merge engine: union, identical-dedup, conflict-keep-both,
instruction concatenation. Run: python3 test_merge.py"""
import tempfile, shutil
from pathlib import Path
import sync


def w(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s)


def main():
    tmp = Path(tempfile.mkdtemp())
    store = tmp / "store" / "commands"
    # store already has a.md and shared.md
    w(store / "a.md", "AAA")
    w(store / "shared.md", "SHARED")
    # a source harness dir: new b.md, identical shared.md, conflicting a.md
    src = tmp / "opencode" / "command"
    w(src / "b.md", "BBB")
    w(src / "shared.md", "SHARED")          # identical -> dropped
    w(src / "a.md", "DIFFERENT")            # conflict -> kept as a.from-opencode.md

    sync.merge_into_store(store, src, "opencode")

    names = sorted(p.name for p in store.iterdir())
    assert names == ["a.from-opencode.md", "a.md", "b.md", "shared.md"], names
    assert (store / "a.md").read_text() == "AAA"                       # original wins
    assert (store / "a.from-opencode.md").read_text() == "DIFFERENT"   # conflict preserved
    assert (store / "b.md").read_text() == "BBB"                       # unioned in
    assert not src.exists()                                            # source consumed

    # re-sweep with the conflict name already taken: identical -> dropped,
    # different -> refreshes the preserved copy (never nests or crashes)
    w(src / "a.md", "DIFFERENT")
    sync.merge_into_store(store, src, "opencode")
    assert (store / "a.from-opencode.md").read_text() == "DIFFERENT"
    w(src / "a.md", "NEWER")
    sync.merge_into_store(store, src, "opencode")
    assert (store / "a.from-opencode.md").read_text() == "NEWER"
    assert sorted(p.name for p in store.iterdir()) == ["a.from-opencode.md", "a.md", "b.md", "shared.md"]

    # instruction file merge
    ag = tmp / "store" / "AGENTS.md"
    w(ag, "base rules")
    other = tmp / "codex" / "AGENTS.md"
    w(other, "codex-only rule")
    sync.merge_into_store(ag, other, "codex")
    txt = ag.read_text()
    assert "base rules" in txt and "codex-only rule" in txt and "merged from codex" in txt, txt
    # idempotent: merging same content again doesn't duplicate
    w(other, "codex-only rule")
    sync.merge_into_store(ag, other, "codex")
    assert ag.read_text().count("codex-only rule") == 1

    shutil.rmtree(tmp)
    print("merge self-check: PASS")


if __name__ == "__main__":
    main()
