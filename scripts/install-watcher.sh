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

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agent-home.sync</string>
  <key>ProgramArguments</key><array>
    <string>$(command -v python3)</string>
    <string>$PWD/sync.py</string>
  </array>
  <key>WatchPaths</key><array>
    <string>$HOME/.claude/plugins/installed_plugins.json</string>
    <string>$STORE/skills</string>
    <string>$STORE/commands</string>
  </array>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$STORE/.watcher.log</string>
  <key>StandardErrorPath</key><string>$STORE/.watcher.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "watcher installed: plugins/skills changes now auto-run sync (log: $STORE/.watcher.log)"
