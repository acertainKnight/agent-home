# Global agent instructions (starter)

This file becomes `CLAUDE.md` / `AGENTS.md` in every harness via `sync.py`.
Replace with your own. `install.sh` copies it to `~/.agent-home/AGENTS.md` if you
don't have one yet.

## Persistent memory (all harnesses)
- Long-term memory lives at `~/.claude/auto-memory/` (one markdown file per fact,
  indexed by `MEMORY.md`).
- If this harness does not load it automatically (Claude Code does), read
  `~/.claude/auto-memory/MEMORY.md` at the start of the session and open the
  linked files relevant to the task.
- Save new durable facts there in the same one-file-per-fact format and add an
  index line to `MEMORY.md`.

## Session handoff (all harnesses)
- At session start, if `~/.agent-home/handoff.md` exists, read it. If it
  describes unfinished work relevant to what the user is asking, say you are
  resuming from it; if it is clearly stale or completed, ignore it.
- When asked to hand off (the `/handoff` command), or when ending a session
  mid-task, overwrite `~/.agent-home/handoff.md` with: date, task, state,
  decisions made, next steps, key file paths. Never include secrets or tokens.

## Model aliases
- `~/.agent-home/models.json` maps friendly model names (opus/sonnet/haiku/gpt)
  to each harness's real model id. When the user names a model by alias and this
  harness doesn't recognize it, resolve it there.

## Cross-harness history
- Past sessions from every harness are indexed as markdown under
  `~/.agent-home/history/`. To recall prior work ("what did we decide about
  X?"), search that directory before saying you don't know.
