#!/bin/bash

# Scheduled jobs do not have an interactive terminal. Keep this launcher
# manual-only even if a stale cron entry still points to it.
if [[ ! -t 1 ]]; then
    exit 0
fi

cd "$(dirname "$0")" || exit 1
exec "./venv/bin/python3" "./ops_dashboard.py"
