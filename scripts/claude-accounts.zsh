# Sourced from ~/.zshrc by `claude-account install`.
# `claude` and `work` go through claude-account, which picks the pool's account
# with the most headroom, checks ~/.claude for names the mirror recipe has not
# ruled on, and relaunches the conversation on the next account after a limit.
# Plain `claude` uses the pool of the account CLAUDE_CONFIG_DIR names (direnv
# in ~/dev sets the work directory), else the first pool in config.json.
export PATH="$HOME/.agent-home/lib/scripts:$PATH"
claude()  { claude-account run auto -- "$@"; }
work()    { cd ~/dev && claude-account run work -- "$@"; }
work1h()  { cd ~/dev && ENABLE_PROMPT_CACHING_1H=1 claude-account run work -- "$@"; }
