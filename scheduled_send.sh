#!/bin/bash

# Launched by launchd (see ops_dashboard.py's schedule endpoints) — sends
# the monthly report to every configured client contact automatically, then
# texts the owner a summary. No TTY is available here, so this intentionally
# does NOT share run_thera_agent.sh's interactive-only guard.

cd "$(dirname "$0")" || exit 1
exec "./venv/bin/python3" "./monthly_agent.py"
