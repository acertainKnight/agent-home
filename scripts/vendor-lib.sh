#!/usr/bin/env bash
# Vendor the runnable pipeline (sync.py, scripts/) into $STORE/lib, preserving
# relative layout (lib/sync.py, lib/scripts/*). macOS TCC gives EPERM to every
# process in the launchd tree that opens a file under ~/Documents, no matter
# how many indirection layers sit between the launchd entrypoint and the file
# — so the watcher can't run the repo copy at all. $STORE is a dot-folder,
# outside that protection; the watcher execs this mirror instead.
set -euo pipefail
cd "$(dirname "$0")/.."
STORE="${AGENT_HOME:-$HOME/.agent-home}"
mkdir -p "$STORE/lib"
rsync -a --delete --exclude='__pycache__/' sync.py "$STORE/lib/sync.py"
rsync -a --delete --exclude='__pycache__/' scripts/ "$STORE/lib/scripts/"
echo "vendored pipeline -> $STORE/lib"
