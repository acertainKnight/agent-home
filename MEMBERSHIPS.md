# Memberships → any harness (state of play, researched 2026-07-11)

Goal: use the Anthropic Max and OpenAI (ChatGPT) subscriptions from any coding
harness at no extra cost, alongside third-party APIs and local models.
Deep-research report: 109-agent verified sweep; key findings below with sources.

## The asymmetry that decides the whole design

**OpenAI: sanctioned.** Codex CLI (and IDE/web/desktop Codex) officially signs in
with your ChatGPT account (`codex login`, `forced_login_method = "chatgpt"`).
Usage draws on plan limits (rolling 5-hour window), zero per-token billing.
[help.openai.com/articles/11369540, developers.openai.com/codex/auth]

**Anthropic: no sanctioned third-party path.** Claude Pro/Max OAuth tokens are
restricted to official Anthropic clients. Anthropic began enforcing against
unofficial OAuth wrappers ~Jan 2026 (legal/compliance clarification Feb 19 2026;
opencode issue #6930 "…violates ToS & Results in Ban"). The community plugins
(opencode-anthropic-auth, opencode-claude-auth ~1.1k★, opencode-with-claude)
work but their own READMEs warn of bans, especially for automated/heavy loops.
**Default: Claude stays in Claude Code (`claude_in_opencode: false`).** It's an
explicit per-user opt-in to reuse a Claude subscription in opencode (via
opencode-claude-auth). Nick has opted in for his own account; teammates decide
for themselves. Keep it to light interactive use — no automated loops.

## The architecture

```
Claude Max ──── Claude Code (official client; personal + work config dirs)
ChatGPT sub ─┬─ Codex CLI (official `codex login`)            ← zero risk
             └─ LiteLLM `chatgpt/` provider (device-code OAuth) ← gray zone, no
                │                                    documented enforcement
                └─→ exposes OpenAI-compatible endpoint → opencode / anything
OpenRouter ──── opencode (already authed), Codex CLI (custom model_provider)
Local (Ollama/LM Studio) ── opencode + Codex CLI built-in provider IDs
```

- **"Run both memberships from one harness"**: Codex CLI is that harness today —
  ChatGPT login natively, plus `model_providers` pointing at any
  OpenAI-compatible endpoint (OpenRouter, LiteLLM, Ollama, LM Studio).
  opencode is the same once LiteLLM fronts the ChatGPT subscription.
  Claude Max can only join via ToS-violating shims — excluded by choice.
- **LiteLLM** (installed via `uv tool install 'litellm[proxy]'`) is the mixing
  board: `chatgpt/*` models on subscription OAuth, `openrouter/*` and local
  models by key/no-auth, one endpoint at `http://localhost:4000`. Config:
  `litellm/config.yaml` in this repo. Known caveat: the chatgpt provider is
  newish and community reports flag flakiness (litellm #27175).
  It also documents forwarding a Claude Max OAuth token
  (`forward_client_headers_to_llm_api: true`) — documented, but Anthropic-side
  ToS exposure is unchanged, so unused here.
- **No opencode fork needed**: auth shims live in opencode's plugin system and
  in LiteLLM, both of which update independently of opencode core.

## One-time logins (interactive, run yourself)

```
codex login                      # browser OAuth with the ChatGPT account
litellm --config ~/Documents/python/agent-home/litellm/config.yaml
# first chatgpt/* request triggers a device-code flow; follow the URL it prints
```

## Sources (primary)

- https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- https://developers.openai.com/codex/auth · /codex/config-advanced · /codex/config-reference
- https://docs.litellm.ai/docs/providers/chatgpt
- https://docs.litellm.ai/docs/tutorials/claude_code_max_subscription
- https://github.com/ex-machina-co/opencode-anthropic-auth · griffinmartin/opencode-claude-auth · ianjwhite99/opencode-with-claude
- https://github.com/anomalyco/opencode/issues/6930 · BerriAI/litellm#13380 · BerriAI/litellm#27175

## Multiple accounts, any provider (the account model)

Accounts are provider-agnostic — define as many as you want in
`config.json.accounts`, each switchable in any harness. Three `provider` types:

- **`anthropic-sub`** (Claude Max/Pro): `config_dir` (a `CLAUDE_CONFIG_DIR`, e.g.
  `~/.claude` personal, `~/.claude-work` work) + optional `keychain`. This mirrors
  exactly how you already run two Claude Code profiles.
- **`chatgpt-sub`** (ChatGPT/Codex): `codex_home` (its own `CODEX_HOME`, e.g.
  `~/.codex` and `~/.codex-work`) so multiple Codex logins don't collide — exactly
  like the Claude two-config-dir split — + a `port` for that account's LiteLLM
  instance. `make install` auto-detects `~/.codex*` dirs and lets you add more;
  sync links the store into every Codex home, and each is logged in with
  `CODEX_HOME=<dir> codex login`, switched with `CODEX_HOME=<dir> codex`.
- **`openai-key`** (OpenRouter and any OpenAI-compatible key): `env_key` + `base_url`.

**One universal primitive** — `scripts/claude-token.sh <account>` returns a live
subscription bearer token for any `anthropic-sub` account (keychain→file, refresh
guidance), never printing it elsewhere. `scripts/verify-claude-membership.sh
<account>` proves any Claude account runs on its membership, not API credits.

**Switching per harness:**
- *Claude accounts in Claude Code* — already native: `claude` vs
  `CLAUDE_CONFIG_DIR=~/.claude-work claude`.
- *Claude accounts in opencode* — opencode-claude-auth auto-detects multiple
  keychain credentials; log each account in once
  (`CLAUDE_CONFIG_DIR=<dir> claude`) and both appear. (Ban-risk opt-in.)
- *ChatGPT/Codex accounts* — each is its own `CODEX_HOME` (`~/.codex`,
  `~/.codex-work`, …): `CODEX_HOME=<dir> codex login` once each, switch with
  `CODEX_HOME=<dir> codex`. `make install` sets up and logs in every one. To reach
  those same accounts from *other* harnesses, run one LiteLLM instance per account
  with its own `CHATGPT_TOKEN_DIR` on its `port`; each appears as `chatgpt/*`
  models a harness selects by pointing at that port.
- *Key providers* — a LiteLLM model group per key; select by model name.

**Tested here (2026-07-11):** `claude-personal` verified live on the Max
subscription (`sk-ant-oat*`, `MEMBERSHIP OK`, `unified-5h` headers), and reused in
opencode via the plugin. **Pending a login (not testable until then):**
`claude-work` (no token on this machine yet — `CLAUDE_CONFIG_DIR=~/.claude-work
claude` to activate) and any second ChatGPT account.
