#!/bin/bash

cd "$(dirname "$0")" || exit 1

# The server's address lives in .env (DASHBOARD_REMOTE), not in this file.
REMOTE="$(sed -n 's/^DASHBOARD_REMOTE=//p' .env 2>/dev/null | tail -1)"
exec "./venv/bin/python3" "./management_app.py" --remote "$REMOTE"
