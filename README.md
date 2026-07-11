# agent-home

One canonical store for everything that should follow you across AI coding
harnesses — global instructions, skills, subagents, slash commands, long-term
memory — plus a wiring layer so your **paid memberships** (Claude Max, ChatGPT)
work in whichever harness you open. Switch harnesses and nothing changes except
the harness: same skills, same memory, same models, no extra cost.

## Quick start (new machine / teammate)

```bash
git clone <this-repo> ~/Documents/python/agent-home
cd ~/Documents/python/agent-home
cp config.example.json config.json      # edit: which harnesses, opt-ins
./install.sh                            # symlinks + provider configs (idempotent)
# then the interactive logins it prints:
codex login                             # ChatGPT account → Codex CLI (sanctioned)
litellm --config litellm/config.yaml    # complete the device-code URL once
./scripts/verify-claude-membership.sh   # proves Claude runs on membership, not credits
```

`config.json` is per-user and gitignored; everything else is committed and shared.

## Layout

```
canonical/
  AGENTS.md    global instructions (single source; becomes CLAUDE.md everywhere)
  skills/      Agent Skills (SKILL.md format — the open standard all harnesses read)
  agents/      subagent definitions
  commands/    slash commands
  memory/      long-term memory (one file per fact + MEMORY.md index)
  mcp/         (reserved) canonical MCP server definitions
sync.py        idempotent linker; --adopt for first-time import, --status to inspect
```

## What reads what

| Harness | Instructions | Skills | Memory |
|---|---|---|---|
| Claude Code (personal) | `~/.claude/CLAUDE.md` → `canonical/AGENTS.md` | `~/.claude/skills` → `canonical/skills` | `~/.claude/auto-memory` → `canonical/memory` (native auto-load) |
| Claude Code (work) | `~/.claude-work/CLAUDE.md` → `canonical/AGENTS.md` | shares `~/.claude/skills` | via AGENTS.md instruction |
| opencode | `~/.config/opencode/AGENTS.md` → `canonical/AGENTS.md` (also reads `~/.claude/CLAUDE.md` natively) | `~/.claude/skills` + `~/.agents/skills` (native) | via AGENTS.md instruction |
| Codex CLI | `~/.codex/AGENTS.md` → `canonical/AGENTS.md` | `~/.agents/skills` (native) | via AGENTS.md instruction |
| anything else | point it at `canonical/AGENTS.md` | `~/.agents/skills` is the emerging default | via AGENTS.md instruction |

`~/.agents/skills` is *generated* by `sync.py`: per-skill symlinks for every canonical
skill plus every **enabled Claude Code plugin's** skills (95 at last run). Claude Code
plugins themselves (hooks, MCP, marketplaces) are architecturally Claude-specific and
cannot port; their skills are the portable part, and this is how they travel.

The memory bridge is an instruction block at the bottom of `canonical/AGENTS.md`:
harnesses without native memory are told to read `~/.claude/auto-memory/MEMORY.md`
at session start and to write new facts in the same format. Claude Code loads it
natively (`autoMemoryDirectory` in settings.json).

## Routine

- New skill/memory/instruction edits happen anywhere → they're already in the repo
  (everything is a symlink into it). `git commit` here to snapshot; push to a
  **private** remote if you want it off-machine (memory contains private notes).
- After installing/enabling a Claude Code plugin: run `./sync.py` to refresh
  `~/.agents/skills`.
- New machine: clone, run `./sync.py --adopt`, done.

## Memberships (model access)

The design in one line: **Claude Max stays in Claude Code; the ChatGPT
subscription is exposed as a local OpenAI-compatible endpoint (LiteLLM :4000)
that every harness can consume; OpenRouter and local models ride the same
endpoint.** So from opencode or Codex you can mix Claude + GPT + OpenRouter +
Ollama in one session.

- **Codex CLI** signs into your **ChatGPT account** officially (`codex login`),
  and its `~/.codex/config.toml` also defines `litellm` and `openrouter`
  providers (`codex --profile litellm`). Fully sanctioned.
- **LiteLLM** (`litellm/config.yaml`) fronts `chatgpt/*` (subscription OAuth),
  `openrouter/*` (key), and local models on one endpoint. Verified booting; the
  ChatGPT provider is newish (some flakiness reported upstream).
- **opencode** consumes that endpoint (`litellm/*` models) and — only if
  `claude_in_opencode: true` — reuses your Claude Code login via the
  `opencode-claude-auth` plugin. **Verified working on this machine**: opencode
  ran `claude-haiku` through the Max membership with no API key present.

### ⚠ Claude subscription in non-Anthropic harnesses = ban risk

`claude_in_opencode` defaults to **false** for exactly this reason. Anthropic's
ToS restricts Pro/Max subscription OAuth to official clients, and they have
enforced with account suspensions since Jan 2026 (heavy/automated loops are the
documented trigger). The `opencode-claude-auth` route works today but is
unsanctioned. Turn it on only for your own account with eyes open; leave it off
for shared/team installs. Full sourcing in MEMBERSHIPS.md.

### Proving it's the membership, not API credits

`scripts/verify-claude-membership.sh` reads your Claude Code OAuth token (never
prints it), confirms it's an `sk-ant-oat*` **subscription** token (an API key is
`sk-ant-api*` and is the only thing that can bill credits), makes one real
request, and shows the `anthropic-ratelimit-unified-*` headers — the Max plan's
5-hour/7-day pools, not API metering. Ran clean here: "MEMBERSHIP OK".
