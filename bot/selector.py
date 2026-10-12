"""
Picking today's batch.

Rules, in the order they are applied:

  1. Never contact a blocked address or a blocked person. Blocks come from
     Jake's manual list, from detected opt-out replies, and from hard bounces.
  2. Respect the minimum gap. With min_gap_days = 2, someone sent on Monday
     is eligible again on Wednesday, not Tuesday.
  3. Respect the lifetime cap, if one is configured.
  4. Fill the batch from the least-contacted prospects first, so never-touched
     people are exhausted before anyone hears from us a second time.
  5. Randomize within each tier, so the order is not the spreadsheet order and
     is different every day.
  6. Reorder the final batch so no two consecutive sends go to the same email
     domain. Three Marcus & Millichap contacts back to back inside one minute
     is a pattern their mail filter can see.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta


class Selection:
    def __init__(self, batch, stats):
        self.batch = batch
        self.stats = stats

    def __len__(self):
        return len(self.batch)


def select_batch(contacts, store, cfg, *, today=None, rng=None) -> Selection:
    today = today or date.today()
    rng = rng or random.Random()

    target = int(cfg["volume"]["daily_target"])
    min_gap = int(cfg["volume"]["min_gap_days"])
    max_touches = int(cfg["volume"].get("max_lifetime_touches", 0) or 0)
    ceiling = int(cfg["safety"]["max_batch_hard_ceiling"])

    if target > ceiling:
        raise ValueError(
            f"daily_target ({target}) exceeds max_batch_hard_ceiling ({ceiling}). "
            "If this is deliberate, raise the ceiling in config.yaml."
        )

    blocked_emails = store.blocked_emails()
    blocked_people = store.blocked_persons()
    last_sent = store.last_sent_map()
    touches = store.touch_counts()

    stats = defaultdict(int)
    eligible = []

    for c in contacts:
        if c.email in blocked_emails:
            stats["blocked_email"] += 1
            continue
        if c.person_key in blocked_people:
            stats["blocked_person"] += 1
            continue

        n = touches.get(c.person_key, 0)
        if max_touches and n >= max_touches:
            stats["lifetime_cap"] += 1
            continue

        last = last_sent.get(c.person_key)
        if last is not None and min_gap > 0:
            if (today - last).days < min_gap:
                stats["too_recent"] += 1
                continue

        eligible.append((n, c))

    stats["eligible"] = len(eligible)

    # Tier by touch count, shuffle inside each tier, then take from the
    # lowest tier upward.
    tiers = defaultdict(list)
    for n, c in eligible:
        tiers[n].append(c)
    for bucket in tiers.values():
        rng.shuffle(bucket)

    batch = []
    for n in sorted(tiers):
        if len(batch) >= target:
            break
        take = tiers[n][: target - len(batch)]
        batch.extend(take)
        stats[f"from_tier_{n}"] = len(take)

    if cfg["selection"].get("spread_same_domain", True):
        batch = _spread_domains(batch, rng)

    stats["selected"] = len(batch)
    stats["shortfall"] = max(0, target - len(batch))
    return Selection(batch, dict(stats))


def _spread_domains(batch, rng):
    """
    Reorder so consecutive sends rarely share an email domain.

    Greedy: repeatedly take from the largest remaining domain bucket whose
    domain differs from the one just placed.
    """
    buckets = defaultdict(list)
    for c in batch:
        buckets[c.domain].append(c)
    for b in buckets.values():
        rng.shuffle(b)

    pools = [b for b in buckets.values() if b]
    out = []
    while pools:
        pools.sort(key=len, reverse=True)
        placed = False
        for p in pools:
            if not out or p[0].domain != out[-1].domain:
                out.append(p.pop(0))
                placed = True
                break
        if not placed:
            # Only one domain left; nothing to interleave with.
            out.append(pools[0].pop(0))
        pools = [p for p in pools if p]
    return out


def adjacency_report(batch) -> int:
    return sum(1 for i in range(1, len(batch))
               if batch[i].domain == batch[i - 1].domain)


def plan_schedule(count, cfg, *, now=None, rng=None, until=None):
    """
    Randomized send times across the configured window, or from now to
    `until` (capped at end_hour) when given.

    Returns a list of datetimes. Gaps are jittered around the mean needed to
    fit `count` sends into the window, floored at min_gap_seconds.
    """
    from datetime import datetime
    now = now or datetime.now()
    rng = rng or random.Random()

    start_h = int(cfg["schedule"]["start_hour"])
    end_h = int(cfg["schedule"]["end_hour"])
    jitter = float(cfg["schedule"].get("jitter", 0.5))
    floor = int(cfg["schedule"].get("min_gap_seconds", 45))

    start = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=0, second=0, microsecond=0)
    if until is not None:
        end = min(end, until)
    if now > start:
        start = now
    window = max(60.0, (end - start).total_seconds())

    if count <= 1:
        return [start]

    mean_gap = window / count
    times, t = [], start
    for _ in range(count):
        times.append(t)
        gap = mean_gap * (1 + rng.uniform(-jitter, jitter))
        gap = max(floor, gap)
        t = t + timedelta(seconds=gap)
    # Jitter can add up past end_hour; squeeze the plan back inside the
    # window unless that would break the floor gap.
    span = (times[-1] - start).total_seconds()
    if span > window:
        scale = window / span
        if mean_gap * scale >= floor:
            times = [start + (x - start) * scale for x in times]
    return times
