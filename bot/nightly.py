"""Refill client and agency queues sequentially on the small server.

Each finder runs in its own process so DuckDB / Chromium memory is released
before the other starts. Existing nightly cron should invoke this module.
"""
import subprocess
import sys

from bot.config import ROOT
from agencyfinder import settings as agencies
from leadfinder import settings as leads


def main():
    failed = False
    if leads.load()["nightly_enabled"]:
        failed |= subprocess.run([sys.executable, "-m", "leadfinder.run", "nightly"], cwd=ROOT).returncode != 0
    if agencies.load()["nightly_enabled"]:
        failed |= subprocess.run([sys.executable, "-m", "agencyfinder.run", "nightly"], cwd=ROOT).returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
