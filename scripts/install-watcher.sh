#!/usr/bin/env bash
# Auto-resync: a launchd agent that re-runs sync.py whenever Claude plugins or
# store skills/commands change, so ~/.agents/skills never goes stale and new
# content appears in every harness without remembering `make sync`.
#
#   ./install-watcher.sh              install/refresh the watcher
#   ./install-watcher.sh --uninstall  remove it
set -euo pipefail
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
PLIST="$HOME/Library/LaunchAgents/com.agent-home.sync.plist"

[ "$(uname)" = "Darwin" ] || {
  echo "watcher is launchd-based (macOS). On Linux, run sync on a timer instead:"
  echo "  crontab: */15 * * * * python3 $PWD/sync.py"
  exit 0
}

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "watcher removed"
  exit 0
fi

# launchd agents can't read ANY file under ~/Documents — macOS TCC blocks it
# ("Operation not permitted", exit 126) for every process in the launchd tree,
# no matter how many indirection layers sit between the launcher and the file
# actually opened. So the store vendors its own runtime copy of the pipeline
# (sync.py, scripts/) into $STORE/lib, and the launcher runs that copy —
# nothing it opens is under ~/Documents anymore.
./scripts/vendor-lib.sh

mkdir -p "$STORE/bin"
cat > "$STORE/bin/resync.sh" <<EOF
#!/usr/bin/env bash
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:\$PATH"
cd "$STORE/lib"
exec scripts/resync.sh "\$@"
EOF
chmod +x "$STORE/bin/resync.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agent-home.sync</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$STORE/bin/resync.sh</string>
  </array>
  <key>WatchPaths</key><array>
    <string>$HOME/.claude/plugins/installed_plugins.json</string>
    <string>$STORE/skills</string>
    <string>$STORE/commands</string>
    <string>$STORE/agents</string>
    <string>$HOME/.codex/skills</string>
    <string>$HOME/.agents/skills</string>
  </array>
  <key>StartInterval</key><integer>300</integer>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$STORE/.watcher.log</string>
  <key>StandardErrorPath</key><string>$STORE/.watcher.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.agent-home.sync"
echo "watcher installed: full resync on plugin/store changes + every 5min (log: $STORE/.watcher.log)"
