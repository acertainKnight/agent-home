---
description: Write a cross-harness session handoff to ~/.agent-home/handoff.md
---

Overwrite `~/.agent-home/handoff.md` with a handoff for the work in this session, written so ANY harness (Claude Code, opencode, Codex, …) can pick it up cold in a fresh session:

```markdown
# Handoff — <today's date, harness name>

**Task**: what we're doing and why
**Where**: working directory, repo, branch
**State**: what's done, what's verified, current blocker if any
**Decisions**: choices made this session the next session must not re-litigate
**Next steps**: ordered and concrete
**Files**: the paths that matter
```

Rules: under 60 lines, plain markdown, absolute paths, NO secrets/tokens. If arguments were given ($ARGUMENTS), focus the handoff on that topic. Confirm with the file path when written.
