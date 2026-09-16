#!/bin/bash

# Scheduled jobs do not have an interactive terminal. Keep this launcher
# manual-only even if a stale cron entry still points to it.
if [[ ! -t 1 ]]; then
    exit 0
fi

"/Users/you/Desktop/THERAWEB/Management App /venv/bin/python3" "/Users/you/Desktop/THERAWEB/Management App /management_app.py"
