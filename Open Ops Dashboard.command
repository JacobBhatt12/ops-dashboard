#!/bin/bash

cd "$(dirname "$0")" || exit 1

# The server's address lives in .env (DASHBOARD_REMOTE), not in this file.
REMOTE="$(sed -n 's/^DASHBOARD_REMOTE=//p' .env 2>/dev/null | tail -1)"

# Use the always-on server over Tailscale when it's reachable; otherwise
# (Tailscale off, server asleep) run the dashboard locally instead.
if [ -n "$REMOTE" ] && curl -s -o /dev/null -m 3 "$REMOTE/"; then
  exec "./venv/bin/python3" "./ops_dashboard.py" --remote "$REMOTE"
else
  echo "Remote dashboard ${REMOTE:-(DASHBOARD_REMOTE not set)} unreachable — starting it locally."
  exec "./venv/bin/python3" "./ops_dashboard.py"
fi
