#!/bin/bash
# Reload the Mac agency-search job once the search that's running finishes,
# so a schedule change never kills a search halfway through.
P="$HOME/Library/LaunchAgents/com.theraweb.agencysync.plist"
while pgrep -f "agencyfinder.sync" >/dev/null; do sleep 30; done
launchctl bootout "gui/$(id -u)/com.theraweb.agencysync" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$P"
echo "$(date) reloaded com.theraweb.agencysync" >> "$(dirname "$0")/../logs/agencysync.log"
