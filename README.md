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
| **Skills** | ✅ every harness | store + enabled-plugin skills → `~/.agents/skills` |
| **Commands / prompts** | ✅ every harness | Claude + opencode + Codex command dirs unified |
| **MCP servers** | ✅ opencode + Codex | pulled from Claude (user + plugins) into `~/.agent-home/mcp.json`, distributed to each harness's native format. stdio ports cleanly; remote ports too (Codex needs `experimental_use_rmcp_client`); Claude-managed-OAuth servers port the definition but you re-auth in the target harness |
| **Agents** (subagents) | ✅ Claude + opencode + Codex | Claude-format is canonical; `port-agents.py` mechanically translates to opencode's agent format (description/tools/model via `models.json` aliases) and to Codex `[agents.<key>]` tables in `config.toml` (confirmed by a live smoke test — Codex has no `~/.codex/agents/` file convention). Only name/description/developer_instructions port to Codex; `model`/`model_reasoning_effort`/`sandbox_mode` are lossy — Claude's per-tool allowlists have no confirmed Codex mapping yet, so they're omitted rather than guessed, pending a logged-in Codex session |
| **Session state** (handoff) | ✅ every harness | `/handoff` writes `~/.agent-home/handoff.md`; every harness reads it at session start |
| **Session history** | ✅ every harness | `history.py` indexes Claude/Codex/opencode transcripts into `~/.agent-home/history/`, searchable from any agent |
| **Secrets / env** | ✅ every harness | `~/.agent-home/env` sourced by every shell via one `~/.zshenv` line |
| **Workflows** | ✅ across Claude profiles | Claude-Code-specific (the Workflow tool) |
| **Plugins** | ✅ decomposed | a plugin = skills + commands + **MCP servers** + hooks + subagents. The first three now port to every harness (see their rows). What doesn't: the plugin *runtime* (marketplaces, its hooks — Claude-specific event JSON, machine-local install cache). So you get a plugin's tools and skills in opencode/Codex, just not its Claude-only hook wiring. |
| **Hooks / settings.json** | ❌ by design | machine/account-specific (absolute paths, model, permissions, keychain); opencode hooks are TS functions, Codex hooks a different shape — semantic re-author, not sync. Whether Codex expands `${CLAUDE_PLUGIN_ROOT}` in a hook command at runtime is still unconfirmed (#13, #19) — needs a logged-in interactive session to observe; a hook-carrying plugin also needs a one-time first-run trust grant before Codex will run its hooks at all (see "Manual steps" in #19's PR) |

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
- **opencode** (>=1.18) logs into OpenRouter and your **ChatGPT Pro/Plus**
  plan natively with `opencode auth login`; both land as entries in
  `~/.local/share/opencode/auth.json`, and `make doctor` checks for them.
  Separately — and only if `claude_in_opencode: true` — it reuses your Claude
  Code login via the `opencode-claude-auth` plugin. **Verified working on
  this machine**: opencode ran `claude-haiku` through the Max membership with
  no API key present.
- **LiteLLM** (`litellm/config.yaml`) is parked history, not wired into
  either harness. It was the router that fronted `chatgpt/*` and
  `openrouter/*` on one local endpoint before opencode and Codex gained
  native auth (retired 2026-08-06); `make litellm` still starts it manually
  if you want a local OpenAI-compatible endpoint for something else.

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

## Component ownership (rulesync vs store scripts)

[rulesync](https://github.com/dyoshikawa/rulesync) (16.8.0, pinned; `npm i -g rulesync`)
is used as a **parts supplier**, not as the architecture. `~/.agent-home` stays the
canonical store in its own format; `resync.sh` stays the pipeline. For each asset
class rulesync covers, this trial ran rulesync against real store content in a
scratch harness home (`$HOME` overridden, never a live `~/.claude`/`~/.codex`/
`~/.config/opencode`) and adopted it only where it beat the existing script. No
class cleared that bar this round, so `resync.sh` is unchanged. The reasoning for
every class below is a specific run, not a feature-table read.

| Class | Verdict | One-line reason |
|---|---|---|
| MCP generation | **ours** (`port-mcp.py`) | rulesync's `--global` MCP write replaced the entire `~/.codex/config.toml` and `~/.config/opencode/opencode.jsonc`, deleting unrelated sections; `port-mcp.py` merges only its own keys |
| Subagents — Claude Code | **ours** (nothing to generate) | the store's `agents/*.md` already is Claude's native subagent format |
| Subagents — opencode | **ours** (`port-agents.py`) | rulesync writes to `~/.config/opencode/agents/` (plural); the real, running opencode reads `~/.config/opencode/agent/` (singular) and never loads the rulesync path |
| Subagents — Codex TOML | **ours** (`port-agents.py`) | confirmed by a live smoke test (issue #20): codex-cli 0.144.1 has no `~/.codex/agents/*.toml` convention at all — `agents.<key>` roles are a table inside `config.toml` itself, the model's own `spawn_agent` tool picks from them. rulesync's `~/.codex/agents/*.toml` target is confirmed dead |
| Skills / commands placement | **ours** (`sync.py` symlinks) | rulesync copies a file per harness; our symlinks are one shared file every harness reads live, no regenerate step |
| Rules (AGENTS.md fan-out) | **ours** (`sync.py` symlinks) | rulesync reproduced AGENTS.md byte-for-byte with no per-tool transform, which a symlink already does for free |
| Hooks emission | **ours** (#13 shim path) | rulesync's `hooks` feature merges into a harness's own global settings file; #13 needs vendored-plugin manifests and marketplace indexes, which rulesync's `hooks` feature never touches |
| `rulesync import` as return path | **ours** (`sync.py` adopt / `port-mcp.py` adopt) | import lands in rulesync's own schema, a second hop before our canonical schema, and its Codex MCP import silently produced nothing against config rulesync itself had just generated |
| `claudecode-plugin` packaging (#12/#13 probe) | **ours** (#13 shim generator stays required) | rulesync never writes plugin manifests or marketplace indexes; run with its default `--delete` against a real vendored plugin, it would have deleted the plugin's real skills and hooks and replaced them with unrelated source |

### MCP generation — measured destructive, not adopted

`rulesync generate -f mcp --global` does not read `CODEX_HOME` or
`CLAUDE_CONFIG_DIR` — it only reads `$HOME`. To trial it at all without touching a
live home, the scratch run overrode `$HOME` wholesale rather than pointing rulesync
at one Codex account's real home, something `sync.py`'s `codex_homes()` loop already
does natively for every configured `chatgpt-sub` account.

The destructive part is measured, not inferred. The scratch `~/.codex/config.toml`
started as a copy of the real file: `forced_login_method = "chatgpt"`, a
`[model_providers.litellm]` block, a `[profiles.litellm]` block, and
`[features] experimental_use_rmcp_client = true`, plus the four `[mcp_servers.*]`
blocks. After `rulesync generate -f mcp --global`, only the four `[mcp_servers.*]`
blocks remained — every other line was gone. The same run against a scratch copy of
`~/.config/opencode/opencode.jsonc` dropped `$schema`, the `opencode-claude-auth`
plugin entry, the `model` field, and `skills.paths`, leaving only the `mcp` key.
`port-mcp.py`'s `generate_codex()` rewrites only its own `[mcp_servers.*]` blocks
with a regex and leaves every other line untouched; `generate_opencode()` merges
into the `mcp` key of the existing JSON object and leaves `$schema`/`plugin`/
`model`/`skills` alone.

rulesync's remote-MCP output for Codex also dropped the `auth = "oauth"` line
`port-mcp.py` writes for OAuth-only remote servers (Slack, Cortex) — without it,
Codex has no configured way to authenticate those two servers. Round-tripping the
same file back with `rulesync import --targets codexcli --features mcp --global`
printed "Successfully loaded 1 codexcli MCP files" and then "No files imported for
enabled features: mcp," writing nothing: rulesync's own Codex MCP output is not
valid input for rulesync's own importer.

### Subagents — split verdict per target

The store's two subagents (`cortex-file-scout.md`, `plugin-validator.md`) already
match Claude Code's native subagent frontmatter exactly, so there is nothing to
generate for the Claude Code leg; rulesync's `claudecode` subagent output was a
byte-identical re-derivation of the same source.

For opencode, `rulesync generate -f subagents --global` wrote
`~/.config/opencode/agents/cortex-file-scout.md` (plural directory). `opencode
agent list`, run live on this machine, shows `cortex-file-scout (subagent)` and
`plugin-validator (subagent)` loaded from the singular `~/.config/opencode/agent/`
directory — the one `port-agents.py` writes to. The plural directory rulesync
targets is never read by the installed opencode, so a rulesync-generated opencode
subagent would silently do nothing. Separately, rulesync's subagent frontmatter has
no equivalent to `port-agents.py`'s model-alias resolution (Claude's `model: haiku`
resolved through `~/.agent-home/models.json` to opencode's real model id) or its
Claude-tool-name-to-opencode-boolean-map translation (`tools: Read, Grep, Glob` →
`tools: {read: true, grep: true, ...}`); each would need a hand-written per-target
override block per agent instead of the one mechanical translation
`port-agents.py` already does for both of the store's agents.

For Codex, rulesync did generate `~/.codex/agents/cortex-file-scout.toml`
(`name`/`description`/`developer_instructions`) — a capability the store has never
had; the existing README states plainly that "Codex has no subagent model." But
codex-cli 0.144.1's own `--help` and `codex features list` show no `agent`
subcommand and no documented `.codex/agents/` convention, so this trial could not
confirm Codex actually reads that directory. This is flagged as a wave-2 smoke test
(drop one generated `.toml` into a real `~/.codex/agents/`, start a session, confirm
it is invocable), not adopted now, because it is unconfirmed rather than because it
lost to an existing script. Even if confirmed, wiring it would need the same
per-account `$HOME`-override loop the MCP trial needed, since rulesync's `--global`
mode still would not read `CODEX_HOME` directly — that alone means it would not
meet the ticket's "trivial wiring" bar for adoption even after confirmation.

`rulesync import --targets codexcli --features subagents --global` did correctly
re-parse both generated Codex/Claude subagents back into
`.rulesync/subagents/*.md`. That output is rulesync's own schema, not the store's
`agents/*.md` schema, so using `import` as the return path adds a translation hop
our own `sync.py` `adopt()` does not need — `adopt()` merges native harness content
directly into the store's schema in one step, keeping conflicting content instead
of overwriting it (`name.from-<harness>`), a safety property this trial did not see
rulesync's `import` attempt.

### Skills, commands, and rules — copies vs live symlinks

rulesync's `skills`, `commands`, and `rules` features all write one file (or file
tree) per harness: `.claude/skills/<name>/`, `.config/opencode/skills/<name>/`,
`.agents/skills/<name>/` in `--global` mode for skills, similarly for commands, and
a full content copy into `.claude/CLAUDE.md` / `.codex/AGENTS.md` /
`.config/opencode/AGENTS.md` for rules (measured byte-identical to the source
AGENTS.md, 108/108 lines, `diff`-clean — a correct but valueless transform, since
the content needs no per-tool change).

`sync.py`'s `build_skill_links()` and `build_command_links()` make one symlink per
skill/command into `~/.agents/skills` and `~/.agents/commands`, which every harness
then points at, and the three `AGENTS.md` fan-out targets in `sync.py`'s `HARNESS`
map are themselves plain symlinks back to the one canonical `AGENTS.md`. Editing a
skill, a command, or `AGENTS.md` is visible in every harness immediately; a
rulesync-copied version is stale the moment the source changes until `rulesync
generate` runs again. This is the exact tradeoff the ticket named going in —
rulesync copies, ours are live — and for assets that need no per-tool
transformation, liveness wins with no offsetting benefit from copying.

### Hooks — different problem than #13 solves

`rulesync generate -f hooks --global` merges non-destructively into an existing
`~/.claude/settings.json`: a scratch `settings.json` seeded with `model`,
`autoMemoryDirectory`, `enabledPlugins`, and `permissions` kept every one of those
keys after generation added only a `hooks` key. It also wrote fresh
`~/.codex/hooks.json` and `~/.config/opencode/plugins/rulesync-hooks.js` files.

That mechanism solves a different problem than issue #13's shim generator needs.
#13 needs each vendored plugin under `~/.agent-home/plugins/` to carry its own
`.claude-plugin/plugin.json` manifest (with a `"hooks"` key when the plugin ships
hooks), a `.codex-plugin/plugin.json` counterpart, a byte-identical hidden
`.mcp.json`, and two marketplace index files at the store root. rulesync's `hooks`
feature never touches any of those — it only writes into a harness's own direct
global config, not into a plugin's manifest. The store's actual hooks (the
dedupe-reads hook active in this very session, the watcher's health checks) are
Nick's-machine-specific shell scripts living in `~/.claude/settings.json` by design;
the existing README already documents this as intentionally unported ("machine/
account-specific... semantic re-author, not sync"). rulesync's cross-tool
hook-event translation stays a future option for hooks we'd author from scratch
across tools, not something adopted now.

### `claudecode-plugin` packaging probe (#12/#13)

Tested against a scratch copy of the real, vendored `ponytail` 4.8.3 plugin (which
already ships both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`,
per #13's own problem statement). rulesync's own docs state the `claudecode-plugin`
target "manages the selected component files but does not create or modify plugin
metadata, marketplace catalogs" — confirmed: `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, and `.codex-plugin/plugin.json` were untouched
(identical MD5 before and after).

With the default `--delete` reconciliation rulesync ships with, the same run's
dry-run output showed it would have **deleted** ponytail's five real skill
directories (`ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`,
`ponytail-review`) and its `hooks/hooks.json`, replacing them with whatever
unrelated `.rulesync/` source happened to be active in the working directory —
because ponytail's vendored bytes, per issue #12's decision, are not sourced from a
`.rulesync/` tree. Running this target against any of the 26 plugins vendored under
#12 as they stand today would corrupt them. Making it safe would mean hand-authoring
a full `.rulesync/` source per plugin that exactly reproduces its skills, commands,
agents, MCP servers, and hooks — a re-authoring project, not the thin mapping this
ticket's own bar requires ("If a class needs more than a thin mapping, that class is
a NO"). Issue #13's shim generator remains fully necessary regardless of whether
this target is ever used.
