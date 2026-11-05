"""Per-campaign budgets and alternating send order."""
from collections import deque
import math


def campaign(contact) -> str:
    return "agency" if getattr(contact, "template", "") == "agency" else "client"


def sent_count(store, day, stream: str) -> int:
    op = "=" if stream == "agency" else "<>"
    return store.conn.execute(
        f"SELECT COUNT(*) FROM sends WHERE sent_on=? AND template {op} 'agency'",
        (day.isoformat(),)).fetchone()[0]


def budget(target: int, already: int, hours_left: int | None = None) -> int:
    remaining = max(0, min(150, int(target)) - already)
    return math.ceil(remaining / max(1, hours_left)) if hours_left is not None else remaining


def alternate(clients, agencies, last_stream=None):
    queues = {"client": deque(clients), "agency": deque(agencies)}
    turn = "client" if last_stream == "agency" or last_stream is None else "agency"
    result = []
    seen = set()
    while queues["client"] or queues["agency"]:
        if not queues[turn]:
            turn = "agency" if turn == "client" else "client"
        item = queues[turn].popleft()
        if item.email not in seen:
            result.append(item)
            seen.add(item.email)
            turn = "agency" if turn == "client" else "client"
    return result
