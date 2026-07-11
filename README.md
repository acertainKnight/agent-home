# agent-home

One canonical store for everything that should follow you across AI coding
harnesses — global instructions, skills, subagents, slash commands, long-term
memory — plus a wiring layer so your **paid memberships** (Claude Max, ChatGPT)
work in whichever harness you open. Switch harnesses and nothing changes except
the harness: same skills, same memory, same models, no extra cost.

## This repo holds only code

Your actual content — skills, memory, instructions — lives in the **`~/.agent-home`
dot-folder** (like `~/.claude`), not here. This repo is just the machinery that
builds the unified system and links `~/.agent-home` into each harness. Nothing
personal is ever committed here, so it's safe to share as-is.

```
install.sh     interactive setup — asks which harnesses you use / want set up
sync.py        idempotent linker (~/.agent-home → harnesses); --adopt, --status
litellm/       LiteLLM proxy config (ChatGPT sub + OpenRouter + local)
templates/     per-harness config templates + AGENTS.example.md starter
scripts/       verify-claude-membership.sh (proves membership, not API credits)
config.json    per-user, gitignored (written by install.sh)

~/.agent-home/  ← YOUR content (not in this repo)
  AGENTS.md     global instructions (becomes CLAUDE.md/AGENTS.md everywhere)
  skills/ agents/ commands/ memory/
```

## Quick start (new machine / teammate)

```bash
git clone <this-repo> ~/Documents/python/agent-home
cd ~/Documents/python/agent-home
./install.sh                            # interactive: pick harnesses to import from / set up
# then the logins it prints:
codex login                             # ChatGPT account → Codex CLI (sanctioned)
litellm --config litellm/config.yaml    # complete the device-code URL once
./scripts/verify-claude-membership.sh   # proves Claude runs on membership, not credits
```

`install.sh` asks two things: which harnesses you **currently use** (it imports
their existing skills/memory/instructions/commands into `~/.agent-home`) and
which to **set up** (it links the store into them). Re-runnable anytime; `--yes`
reuses your saved `config.json`, `--status` just inspects.

### Full merge — nothing is left behind

`--adopt` doesn't just copy Claude Code's config; it **unions every source
harness's native content** into the store: Claude commands (`~/.claude/commands`),
opencode commands (`~/.config/opencode/command`), Codex prompts
(`~/.codex/prompts`), and native skill dirs all merge into one place, then link
back so a command written once shows up everywhere. Same-named-but-different
files are kept side by side as `name.from-<harness>` (never silently dropped);
divergent instruction files (`CLAUDE.md` vs `AGENTS.md`) are concatenated under a
`merged from <harness>` header. Both Claude accounts (personal `~/.claude` + work
`~/.claude-work`) are sources. See `test_merge.py` for the guarantees.

## What reads what

| Harness | Instructions | Skills | Memory |
|---|---|---|---|
| Claude Code (personal) | `~/.claude/CLAUDE.md` → `~/.agent-home/AGENTS.md` | `~/.claude/skills` → `~/.agent-home/skills` | `~/.claude/auto-memory` → `~/.agent-home/memory` (native auto-load) |
| Claude Code (work) | `~/.claude-work/CLAUDE.md` → `~/.agent-home/AGENTS.md` | shares `~/.claude/skills` | via AGENTS.md instruction |
| opencode | `~/.config/opencode/AGENTS.md` → `~/.agent-home/AGENTS.md` (also reads `~/.claude/CLAUDE.md` natively) | `~/.claude/skills` + `~/.agents/skills` (native) | via AGENTS.md instruction |
| Codex CLI | `~/.codex/AGENTS.md` → `~/.agent-home/AGENTS.md` | `~/.agents/skills` (native) | via AGENTS.md instruction |
| anything else | point it at `~/.agent-home/AGENTS.md` | `~/.agents/skills` is the emerging default | via AGENTS.md instruction |

`~/.agents/skills` is *generated* by `sync.py`: per-skill symlinks for every store
skill plus every **enabled Claude Code plugin's** skills (95 at last run). Claude Code
plugins themselves (hooks, MCP, marketplaces) are architecturally Claude-specific and
cannot port; their skills are the portable part, and this is how they travel.

The memory bridge is an instruction block in `~/.agent-home/AGENTS.md`: harnesses
without native memory are told to read `~/.claude/auto-memory/MEMORY.md` at
session start and write new facts in the same format. Claude Code loads it
natively (`autoMemoryDirectory` in settings.json).

## Routine

- Edit a skill/memory/instruction in any harness → it's already in `~/.agent-home`
  (everything symlinks there). To back up or sync YOUR content across YOUR
  machines, `git init` a **private** repo inside `~/.agent-home` and push it.
- After installing/enabling a Claude Code plugin: run `./sync.py` to refresh
  `~/.agents/skills`.
- New machine: clone this repo, `./install.sh`, done.

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

### Multiple accounts (Claude, ChatGPT, or any provider)

`config.json.accounts` is provider-agnostic — list as many as you want and switch
between them in any harness. `anthropic-sub` accounts point at a `CLAUDE_CONFIG_DIR`
(exactly like your `~/.claude` vs `~/.claude-work` split), `chatgpt-sub` accounts
each get their own token dir + LiteLLM port, `openai-key` accounts a key + base URL.
Full per-provider switching guide in MEMBERSHIPS.md.

### Proving it's the membership, not API credits

`scripts/verify-claude-membership.sh [account]` reads that account's OAuth token
(never prints it), confirms it's an `sk-ant-oat*` **subscription** token (an API
key is `sk-ant-api*` and is the only thing that can bill credits), makes one real
request, and shows the `anthropic-ratelimit-unified-*` headers — the Max plan's
5-hour/7-day pools, not API metering. Ran clean here for `claude-personal`:
"MEMBERSHIP OK". `scripts/claude-token.sh <account>` is the underlying token
primitive any harness/provider can call.
