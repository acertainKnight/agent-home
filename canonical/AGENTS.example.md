# Global agent instructions (starter)

This file becomes `CLAUDE.md` / `AGENTS.md` in every harness via `sync.py`.
Replace with your own. `install.sh` copies it to `canonical/AGENTS.md` (which is
gitignored) if you don't have one yet.

## Persistent memory (all harnesses)
- Long-term memory lives at `~/.claude/auto-memory/` (one markdown file per fact,
  indexed by `MEMORY.md`).
- If this harness does not load it automatically (Claude Code does), read
  `~/.claude/auto-memory/MEMORY.md` at the start of the session and open the
  linked files relevant to the task.
- Save new durable facts there in the same one-file-per-fact format and add an
  index line to `MEMORY.md`.
