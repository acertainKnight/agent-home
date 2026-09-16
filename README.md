# agent-home

One canonical store for everything that should follow you across AI coding
harnesses — global instructions, skills, subagents, slash commands, long-term
memory — plus a wiring layer so your **paid memberships** (Claude Max, ChatGPT)
work in whichever harness you open. Switch harnesses and nothing changes except
the harness: same skills, same memory, same models, no extra cost.

**macOS only.** The watcher, the Remote Control launch agent, notifications,
the Claude credential lookup and the iMessage fallback use launchd, AppleScript,
the Keychain and the Messages database. The Python and shell scripts run
elsewhere, but nothing here is tested outside macOS.

## This repo holds only code

Your actual content — skills, memory, instructions — lives in the **`~/.agent-home`
dot-folder** (like `~/.claude`), not here. This repo is just the machinery that
builds the unified system and links `~/.agent-home` into each harness. Nothing
personal is ever committed here, so it's safe to share as-is.

```
install.sh     interactive setup — asks which harnesses you use / want set up
sync.py        idempotent linker (~/.agent-home → harnesses); --adopt, --status
litellm/       LiteLLM proxy config — parked, not wired in; opencode/codex use native auth (see Memberships)
templates/     per-harness config templates, AGENTS.example.md, /handoff command
scripts/       claude-token.sh, verify/quota, port-mcp.py, port-agents.py,
               doctor.sh, history.py, install-watcher.sh
config.example.json   template only (never used as defaults)

~/.agent-home/  ← EVERYTHING per-user (not in this repo)
  config.json   your harness + account choices (written by install.sh)
  AGENTS.md     global instructions (becomes CLAUDE.md/AGENTS.md everywhere)
  mcp.json      canonical MCP servers (distributed to each harness)
  models.json   model-alias map (opus/sonnet/… → each harness's model id)
  env           shared secrets/env (sourced by every shell; chmod 600)
  handoff.md    cross-harness session handoff (written by /handoff)
  history/      indexed transcripts from every harness (searchable)
  skills/ agents/ commands/ memory/ workflows/
```

## Quick start (new machine / teammate)

```bash
git clone <this-repo> ~/Documents/python/agent-home
cd ~/Documents/python/agent-home
make install     # (or: just install)  — the whole guided walkthrough
```

`make install` runs one interactive walkthrough that: picks which harnesses you
**currently use** (merges their existing skills/memory/instructions/commands into
`~/.agent-home`) and which to **set up** (links the store into them), wires the
model providers, then **logs in and verifies every account** in `config.json`.

Other targets (`make help` lists them):

| command | does |
|---|---|
| `make install` | full walkthrough (merge + wire + logins) |
| `make login` | log in & verify every account (re-runnable) |
| `make doctor` | health-check everything; prints the exact fix per problem |
| `make status` | show every symlink's state |
| `make verify ACCOUNT=work` | prove one account runs on membership, not credits |
| `make quota` | every account's headroom: Claude 5h/7d pools, Codex 5h/weekly usage, OpenRouter credits |
| `make sync` | re-merge after adding a skill/plugin |
| `make history` / `make history q="regex"` | index / search past sessions from every harness |
| `make agents` | regenerate opencode agents from your Claude subagents |
| `make watcher` | auto-run sync when plugins/skills change (launchd) |
| `make litellm` | OPTIONAL, parked: start the LiteLLM router (:4000) — not the default model path, see Memberships |

No `just`/`make`? `./install.sh` is the same walkthrough; `--login`, `--status`,
`--watcher`, `--yes` are the sub-modes.

### What travels, and what can't

| Thing | Shared via agent-home? | Notes |
|---|---|---|
| **Instructions** (CLAUDE.md/AGENTS.md) | ✅ every harness | merged, one source |
| **Memory** (auto-memory) | ✅ | native in Claude Code; AGENTS.md bridge elsewhere |
| **Skills** | ✅ every harness incl. Cursor | store + enabled-plugin skills → `~/.agents/skills`, also linked to `~/.cursor/skills` (#23) |
| **Commands / prompts** | ✅ every harness | Claude + opencode + Codex command dirs unified |
| **MCP servers** | ✅ opencode + Codex + Cursor | union-adopted from every harness plus hand-curated connectors into `~/.agent-home/mcp.json` (Agent Plugins spec vocabulary), distributed to each harness's native format. stdio ports cleanly; remote ports too (Codex needs `experimental_use_rmcp_client`); Claude-managed-OAuth servers port the definition but you re-auth in the target harness. Cursor's `~/.cursor/mcp.json` uses the same `mcpServers` shape Claude's own `~/.claude.json` does (#23) |
| **Agents** (subagents) | ✅ Claude + opencode + Codex | Claude-format is canonical; `port-agents.py` mechanically translates to opencode's agent format (description/tools/model via `models.json` aliases) and to Codex `[agents.<key>]` tables in `config.toml` (confirmed by a live smoke test — Codex has no `~/.codex/agents/` file convention). Only name/description/developer_instructions port to Codex; `model`/`model_reasoning_effort`/`sandbox_mode` are lossy — Claude's per-tool allowlists have no confirmed Codex mapping yet, so they're omitted rather than guessed, pending a logged-in Codex session |
| **Session state** (handoff) | ✅ every harness | `/handoff` writes `~/.agent-home/handoff.md`; every harness reads it at session start |
| **Session history** | ✅ every harness incl. Cursor | `history.py` indexes Claude/Codex/opencode/cursor-agent transcripts into `~/.agent-home/history/`, searchable from any agent (#23) |
| **Secrets / env** | ✅ every harness | `~/.agent-home/env` sourced by every shell via one `~/.zshenv` line |
| **Workflows** | ✅ across Claude profiles | Claude-Code-specific (the Workflow tool) |
| **Plugins** | ✅ decomposed | a plugin = skills + commands + **MCP servers** + hooks + subagents. The first three now port to every harness (see their rows). What doesn't: the plugin *runtime* (marketplaces, its hooks — Claude-specific event JSON, machine-local install cache). So you get a plugin's tools and skills in opencode/Codex, just not its Claude-only hook wiring. |
| **Hooks** | ✅ Codex via plugin manifests (trust-gated) · ⚠️ opencode: TS re-author (#22) · ✅ Cursor: translated emitter (#23) | Codex reads Claude's `hooks.json` schema through each vendored plugin's `.codex-plugin` manifest — a one-time interactive trust grant is required before hooks fire, and `${CLAUDE_PLUGIN_ROOT}` runtime expansion is still unconfirmed (see "Manual steps" in #19's PR). opencode hooks are TS functions, so a straight copy is never right: `hooks/opencode/agent-home-hooks.ts` re-implements six Claude hook behaviors on opencode's own hook points — see "opencode hook parity" below. Cursor gets `scripts/port-hooks-cursor.py`, which flattens vendored plugins' Claude-format `hooks.json` into `~/.cursor/hooks.json` for the events Cursor supports — see "Cursor harness" below. |
| **settings.json** | ❌ by design (see #16) | machine/account-specific: absolute paths, model, permissions, keychain |

### Non-breaking

Re-running is safe on an already-set-up machine: content dirs are **merged**, not
replaced (union; a same-named-but-different file is kept as `name.from-<harness>`,
never overwritten), logins/credentials are never touched, `~/.codex/config.toml`
is only written if absent, and `opencode.jsonc` is **merged** into (your other
providers/settings/keys are preserved; an unparseable file is backed up first).

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
| Cursor (cursor-agent CLI) | `~/.cursor/AGENTS.md` → `~/.agent-home/AGENTS.md` (unconfirmed global path — cursor-agent's CONFIRMED read is project-root AGENTS.md; see "Cursor harness" below) | `~/.cursor/skills` → `~/.agents/skills` (Cursor also auto-detects `~/.agents/skills` directly, per its own docs) | via AGENTS.md instruction |
| anything else | point it at `~/.agent-home/AGENTS.md` | `~/.agents/skills` is the emerging default | via AGENTS.md instruction |

`~/.agents/skills` is *generated* by `sync.py`: per-skill symlinks for every store
skill plus every **enabled Claude Code plugin's** skills (115 at last run — 21 of
those came from `~/.cursor/skills-cursor`, a stale pre-agent-home sync tool's
output, swept into the store by issue #23; see "Cursor harness" below). Claude Code
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
- Leaving mid-task? `/handoff` (any harness) → next session in ANY harness picks
  it up. Wondering what a past session decided? `make history q="..."`.
- After installing/enabling a Claude Code plugin: run `./sync.py` to refresh
  `~/.agents/skills` — or `make watcher` once and it happens automatically.
- Something feels off? `make doctor` names the problem and the fix.
- New machine: clone this repo, `./install.sh`, done.

## Memberships (model access)

The design in one line: **Claude Max stays in Claude Code; opencode and Codex
CLI each authenticate natively** — no proxy in between. So from opencode or
Codex you can mix ChatGPT + OpenRouter + Claude-via-plugin in one session
without running a local router.

- **Codex CLI** signs into your **ChatGPT account** officially (`codex login`).
  Fully sanctioned.
- **opencode** (>=1.18) logs into OpenRouter, your **ChatGPT Pro/Plus** plan,
  and your **Anthropic Pro/Max** plan natively with `opencode auth login`;
  each lands as an entry in `~/.local/share/opencode/auth.json`, and
  `make doctor` checks for them. The Anthropic login is sanctioned again —
  Anthropic reinstated third-party subscription use in May/June 2026 (a
  metered credit-pool billing model was announced, then deferred with advance
  notice promised; dated history in MEMBERSHIPS.md). **Verified on this
  machine 2026-08-07**: opencode ran `claude-haiku-4-5` on the Max login with
  no restriction error.
- **LiteLLM** (`litellm/config.yaml`) is parked history, not wired into
  either harness. It was the router that fronted `chatgpt/*` and
  `openrouter/*` on one local endpoint before opencode and Codex gained
  native auth (retired 2026-08-06); `make litellm` still starts it manually
  if you want a local OpenAI-compatible endpoint for something else.

### Claude subscription outside Claude Code — sanctioned again (2026-08-07)

Anthropic blocked subscription OAuth in third-party tools from Jan 2026 and cut
it fully on Apr 4, then **reinstated it in May/June 2026** (with a metered
credit-pool billing model announced but deferred — MEMBERSHIPS.md carries the
dated history and sources). The supported path is opencode's **native**
`opencode auth login` → Anthropic. The old `opencode-claude-auth` shim behind
`claude_in_opencode` is therefore legacy: the code stays (wire-opencode.py
still honors the flag, and removes the shim plugin when it's false), but the
installer no longer offers it and it should stay `false`. Two standing
cautions: keep heavy automated loops in Claude Code, and re-check the
economics when the deferred credit-pool billing activates (third-party usage
will then draw a metered allowance at API rates, not the flat Max quota).

### Multiple accounts (Claude, ChatGPT, or any provider)

`config.json.accounts` is provider-agnostic — list as many as you want and switch
between them in any harness. `anthropic-sub` accounts point at a `CLAUDE_CONFIG_DIR`
(exactly like your `~/.claude` vs `~/.claude-work` split), `chatgpt-sub` accounts
each get their own token dir + LiteLLM port, `openai-key` accounts a key + base URL.
Full per-provider switching guide in MEMBERSHIPS.md.

### Claude accounts: pools and automatic switching

`scripts/claude-account` treats the anthropic-sub entries of `config.json` as
accounts grouped into pools (`pool`, default: the name suffix, so
`claude-work-2` is in `work`). `~/.claude` is the default account and is always
launched with `CLAUDE_CONFIG_DIR` unset; every other account is a directory
that mirrors `~/.claude` by symlink (recipe: `~/.agent-home/claude-mirror.json`).

- `claude-account install` writes the shell snippet (`claude`, `work`, `work1h`
  become wrappers), the `StopFailure` hook and the status-line feed into
  `~/.claude/settings.json`, and the Remote Control launch agent.
- `claude-account login` signs in a new account end to end: it asks for the pool,
  names and creates the directory with all mirror links, runs Claude's own
  `auth login`, and records the email and plan in `config.json`.
  `claude-account login <name>` re-signs an existing account.
- Every launch checks `~/.claude` for names the recipe has not ruled on and asks
  share / keep private / later. `sync.py` re-links the mirror on each run.
- A pool drains its accounts in `config.json` order: every launch takes the
  first account that is not marked exhausted. `claude-account prefer <name>`
  moves an account to the front of its pool.
- On a usage limit the hook records the account as exhausted until the reset
  time in the limit message, ends the limited process, and the wrapper
  relaunches on the next account with `--resume <id>`. The status-line feed
  also marks an account exhausted when a window reads 100% and clears the mark
  once it reads under. When the pool is out, a terminal picker (or an iMessage
  question when nobody is at the terminal) offers the `spill_to` pools, the
  built-in wait, or quit.
- `claude-account status` shows login, plan, headroom and exhaustion per account
  in pool order. `claude-account clear <name>` drops a wrong exhausted mark.

### Proving it's the membership, not API credits

`scripts/verify-claude-membership.sh [account]` reads that account's OAuth token
(never prints it), confirms it's an `sk-ant-oat*` **subscription** token (an API
key is `sk-ant-api*` and is the only thing that can bill credits), makes one real
request, and shows the `anthropic-ratelimit-unified-*` headers — the Max plan's
5-hour/7-day pools, not API metering. Ran clean here for `claude-personal`:
"MEMBERSHIP OK". `scripts/claude-token.sh <account>` is the underlying token
primitive any harness/provider can call.

## Harness notes and design history

- `hooks/opencode/agent-home-hooks.ts` re-implements the Claude Code hook
  behaviors on opencode's hook points; `sync.py` links it into
  `~/.config/opencode/plugins/`.
- Cursor (`cursor-agent`) is a wired target for instructions, skills, MCP and
  hooks (`scripts/port-hooks-cursor.py`).
- The trial runs behind these choices, including why rulesync is used as a
  parts supplier and not as the pipeline, are in
  [docs/decisions.md](docs/decisions.md).
