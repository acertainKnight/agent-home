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
**Decision: do not shim Claude Max into other harnesses. Claude Code stays the
Claude-membership harness.** Revisit if Anthropic ships an official program.

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
