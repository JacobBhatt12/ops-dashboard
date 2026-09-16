#!/bin/bash
# Quick look at what the bot has done.
cd "$(dirname "$0")/.."
PY=".venv/bin/python3"; [ -x "$PY" ] || PY=python3
"$PY" - <<'PYEOF'
import sqlite3, sys
sys.path.insert(0,'.')
from bot.config import Config
db = sqlite3.connect(Config.load().path("state_db")); db.row_factory=sqlite3.Row
print("Last 10 run days:")
for r in db.execute("SELECT sent_on, COUNT(*) n, SUM(source='bot') bot FROM sends GROUP BY sent_on ORDER BY sent_on DESC LIMIT 10"):
    print(f"  {r['sent_on']}  {r['n']:4} sent  ({r['bot']} by bot)")
print("\nBlocks by source:")
for r in db.execute("SELECT source, COUNT(*) n FROM blocks GROUP BY source"):
    print(f"  {r['source']:8} {r['n']}")
print("\nMost recent blocks:")
for r in db.execute("SELECT added_at, email, reason FROM blocks ORDER BY added_at DESC LIMIT 8"):
    print(f"  {r['added_at'][:16]}  {r['email']:40} {r['reason']}")
t = db.execute("SELECT COUNT(*) FROM sends").fetchone()[0]
p = db.execute("SELECT COUNT(DISTINCT person_key) FROM sends").fetchone()[0]
print(f"\nLifetime: {t} sends to {p} people")
PYEOF
