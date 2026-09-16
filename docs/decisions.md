# Design decisions and trial records

Why the machinery is shaped the way it is: each section records a trial run
against real content and the verdict it produced. Issue numbers (#12, #13,
#22, #23, ...) refer to this repository's GitHub issue tracker. The user-facing
manual is [README.md](../README.md).

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
machine-specific shell scripts living in `~/.claude/settings.json` by design;
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

## opencode hook parity (#22)

Claude Code hooks are event-JSON in `settings.json`; opencode hooks are TypeScript
functions (`@opencode-ai/plugin`) — a straight copy was never possible. `hooks/opencode/
agent-home-hooks.ts` re-implements six Claude-side behaviors on opencode's own hook
points, symlinked (by `sync.py`) into `~/.config/opencode/plugins/agent-home-hooks.ts`.
Every behavior reads its on/off state from `~/.agent-home/plugins/enabled.json` — the
same store-owned list `sync.py` uses to decide which plugins' skills/commands port —
so disabling a plugin in Claude Code silences its opencode counterpart too.

| # | Claude behavior | opencode hook point | How |
|---|---|---|---|
| 1 | SessionStart context injections (ponytail, explanatory-output-style, superpowers) | `experimental.chat.system.transform` | fires every request, not just once — reuses ponytail's own `ponytail-instructions.js`/`ponytail-config.js` (vendored under `plugins/ponytail/hooks/`); explanatory-output-style is a fixed string; superpowers reads its `using-superpowers/SKILL.md` |
| 2 | MEMORY.md auto-load | same hook | reads `~/.agent-home/memory/MEMORY.md` fresh every call — true auto-load, not the AGENTS.md "please read" instruction |
| 3 | remember capture (UserPromptSubmit + PostToolUse) | `chat.message` + `tool.execute.after` | **reduced, not ported** — remember's real pipeline (`scripts/post-tool-hook.sh`) counts new lines in Claude Code's own on-disk session JSONL transcript, which opencode never writes; bridging to it would silently no-op. Instead: every prompt and non-read tool call is appended to `~/.agent-home/memory/staging/opencode.ndjson` (gitignored runtime output) — a durable trace, not auto-consolidation into MEMORY.md |
| 4 | cortex SessionStart (context.brief) | `event` on `session.created` | fetches `/v1/context/brief` once per session (2s timeout, same contract as `hooks/session_start.sh`), delivered on the session's first system-prompt transform |
| 4b | cortex SessionEnd (distill) | already solved | **not reimplemented here** — `plugins/cortex/hooks/opencode/session-distill.ts` already does this via debounced `session.idle`; left untouched |
| 5 | dedupe_reads.py (PreToolUse on Read) | `tool.execute.before` | bridges to the real `~/.claude/hooks/dedupe_reads.py` (a personal hook, not store-vendored) so both harnesses share one dedup decision; throws to block, matching opencode's documented "mutate args or throw" contract; fails open if the script is missing or errors |
| 6 | security-guidance PostToolUse (pattern warnings) | `tool.execute.after` | bridges to the real, fully store-vendored `security_reminder_hook.py` for the fast synchronous Edit/Write pattern check. **Not ported**: the git-commit/push LLM review — that path is Claude-only `asyncRewake` (a delayed background review that re-wakes the conversation later, can take minutes), which has no opencode analog for a finished `tool.execute.after` call |

Known, accepted loss: ponytail's statusline badge. opencode's status bar isn't
plugin-extensible — no workaround exists.

A real bug surfaced while wiring this up, worth recording: opencode's plugin loader
(measured on 1.18.14) calls **every named export** of a file inside a `plugins/`
directory as if it were a plugin factory, passing it the `PluginInput` object — a
second named export (e.g. a helper function) gets invoked the same way and throws,
taking the whole plugin down (and, transitively, the session — an unrelated
`tool.execute.before`/`experimental.chat.system.transform` hook failing to load
crashed every prompt in testing). `agent-home-hooks.ts` therefore exports **only**
`default`; every testable helper lives in `agent-home-hooks-lib.ts`, which is never
itself placed in a `plugins/` directory. The test suite asserts this shape directly
so the constraint can't silently regress. Separately, and unrelated to this plugin:
`session-distill.ts` (a pre-existing opencode plugin)
also fails to load under this same opencode version with a different error (`{} is
not iterable`) — a pre-existing opencode/version issue, not something this ticket
introduced or was in scope to fix.

Verified live against a real `opencode run` session: ponytail injection (model
reported "Ponytail mode level 'full'"), MEMORY.md auto-load (model quoted a real
memory-file fact), dedupe-reads (second `Read` of the same file blocked with the
real script's exact message), security-guidance (pattern warning appeared inline
in the tool output), and remember capture (prompt + tool lines landed in the
staging NDJSON). cortex's context.brief fetch was verified by contract/code review
only — a live check would need the real `CORTEX_API_TOKEN`, which this work
deliberately never reads or prints.

## Cursor harness (#23)

Cursor is now a wired target: `cursor-agent` (the CLI; installed here via `brew
install --cask cursor-cli`), `sync.py`, `install.sh`, `port-mcp.py`, a new
`scripts/port-hooks-cursor.py`, `doctor.sh`, and `history.py` all know about it.

**Instructions and skills.** `sync.py` links `~/.agent-home/AGENTS.md` to
`~/.cursor/AGENTS.md` and `~/.agents/skills` to `~/.cursor/skills`. The AGENTS.md
link is a **best-effort global fallback, not a confirmed read path**: `cursor-agent`'s
own docs confirm it reads `AGENTS.md`/`CLAUDE.md` at a project's root, but say
nothing about a global `~/.cursor/AGENTS.md`. Cursor's skill docs, by contrast,
explicitly say it auto-detects `~/.agents/skills` directly — so the skills link is
belt-and-suspenders, not the only path. Confirming (or ruling out) the global
AGENTS.md read needs a live `cursor-agent` session; see Manual steps.

**`~/.cursor/skills-cursor` retired.** This was a disjoint, stale skill sync (last
run mid-June, per its own `.sync-manifest.json`) from before agent-home existed.
Added `HOME / ".cursor/skills-cursor"` to `sync.py`'s `SKILL_SWEEP` list — the
same generic "import real skill dirs, never delete the source" mechanism that
already covers `~/.codex/skills` — and ran it: all 21 of its skills (`automate`,
`babysit`, `canvas`, `create-hook`, …) were unique (zero name collisions with the
94 already in the store) and moved into `~/.agent-home/skills/`, so they now travel
to every harness the same way. Left a `README.md` breadcrumb in the now-empty
`skills-cursor/` directory explaining the move, per the ticket's "don't delete"
instruction.

**MCP.** `port-mcp.py` gained `generate_cursor()`/`check_cursor()`, joining the
same `--check` drift surface `check_opencode()`/`check_codex()` already use, called
from `apply`/`check` alongside the existing two. Cursor's `~/.cursor/mcp.json` uses
the `{"mcpServers": {name: {command,args,env}}}` shape for stdio and
`{"mcpServers": {name: {url,headers}}}` for remote — the same vocabulary Claude's
own `~/.claude.json` uses, no `"type"` key the way opencode's shape needs. Live-
verified: `cursor-agent mcp list` (works without login — it's a local read) against
the generated file printed all 4 canonical servers (`snowflake: ready`, `slack:
Error: Connection failed`, `imessage: Error: Connection failed`, `cortex:
requires_authentication`) — proof Cursor's own CLI parses the emitted file
correctly, even though full connection requires credentials this session never
touches.

**Hooks.** `scripts/port-hooks-cursor.py` is new: it reads every **enabled**
vendored plugin's `hooks/hooks.json` (Claude's per-event, grouped-by-matcher
shape) and flattens it into `~/.cursor/hooks.json` (Cursor's schema-version-1,
flat-per-event shape: `{"version":1,"hooks":{"<event>":[{"command":"...",
"matcher":"..."}]}}`, matching the reference `hooks-cursor.json` superpowers
already ships). Event mapping: `SessionStart→sessionStart`,
`SessionEnd→sessionEnd`, `UserPromptSubmit→beforeSubmitPrompt`,
`PreToolUse→preToolUse`, `PostToolUse→postToolUse`, `Stop→stop`,
`SubagentStop→subagentStop`. `Notification` has no Cursor equivalent and is
skipped. A hook gated by Claude's `"if"` key (a command-CONTENT matcher — e.g.
security-guidance's `Bash(git commit:*)` gate on its `PostToolUse` hook) is also
skipped: Cursor's own `matcher` only matches the tool NAME, so translating one
would fire the hook on every `Bash` call instead of just commits, which is a
behavior change, not a port.

Building this surfaced a real, pre-existing vendoring gap, unrelated to Cursor:
`vendor-plugins.py`'s `CONTENT_DIRS` only copies `skills/hooks/commands/agents`,
but **two plugins' `hooks.json` reference scripts OUTSIDE those directories** —
`explanatory-output-style`'s `SessionStart` hook points at
`hooks-handlers/session-start.sh` (a sibling of `hooks/`, never vendored), and
`remember`'s `SessionStart`/`UserPromptSubmit`/`PostToolUse` hooks all point at
`scripts/*.sh` (also never vendored). Every Claude-format hook these two plugins
ship references a file that doesn't exist anywhere under
`~/.agent-home/plugins/`. This affects the **existing** `.claude-plugin`/
`.codex-plugin` shims too (#12/#13), not just this ticket's emitter — it just
happened to surface here first. `port-hooks-cursor.py` defends itself against it
(`_missing_referenced_files` skips any command whose referenced path doesn't
exist on disk, rather than emitting a hook that would silently fail every time it
fires) but does not fix the underlying vendoring gap — widening `CONTENT_DIRS`
is a `vendor-plugins.py` change, out of this ticket's scope. Filed as a follow-up
worth a look, not fixed here. On this machine, filtering these out left 7 working
hooks across 5 events (`sessionStart`×3, `sessionEnd`×1, `beforeSubmitPrompt`×1,
`postToolUse`×1, `stop`×1) from cortex, security-guidance, and superpowers —
explanatory-output-style and remember currently contribute nothing portable to
Cursor until that gap is closed.

**Vendored AP-layout plugins in Cursor — investigated, not confirmed working.**
The ticket's problem statement states Cursor "loads [Agent Plugins 1.0.0] without
changes." A real, cached Cursor marketplace checkout on this machine
(`~/.cursor/plugins/cache/cursor-public/superpowers/<sha>/`) contradicts that: it
ships a `.cursor-plugin/plugin.json` manifest, a THIRD manifest directory
alongside the `.claude-plugin/` and `.codex-plugin/` ours already generates —
not a `.claude-plugin/` Cursor reads directly. Confirming this needed either (a)
`cursor-agent plugin marketplace add <gitUrl>`, which requires both an
authenticated session (`cursor-agent login`, interactive OAuth) and a
git-clonable URL (not a bare local path — untested whether `file://` works), or
(b) dropping a plugin into `~/.cursor/plugins/local/` (empty on this machine,
presumably also wants `.cursor-plugin/plugin.json`) and confirming via the
Cursor.app GUI (fully interactive, no CLI equivalent found). Neither has a
non-interactive path, so nothing was attempted live — see Manual steps. Extending
`vendor-plugins.py` to also generate a `.cursor-plugin/plugin.json` (mechanically
the same shape as the existing `.codex-plugin` generator) would be the fix if the
marketplace path turns out to be the one that matters; sizing that is a
follow-up, not part of this ticket.

**Not done, explicitly out of scope for this ticket:** a `.cursor-plugin`
manifest generator (see above — investigation only), and any change to
`vendor-plugins.py`'s `CONTENT_DIRS` (the un-vendored-script gap above).
