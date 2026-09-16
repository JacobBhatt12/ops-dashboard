#!/bin/bash
# Stop the scheduled job. Leaves the database and logs in place.
PLIST="$HOME/Library/LaunchAgents/com.nimble.emailsender.plist"
launchctl unload "$PLIST" 2>/dev/null && rm -f "$PLIST" && echo "Scheduled job removed." || echo "No job was installed."
