"""When to post. A flow says 'N posts a day between 10:00 and 22:00'; we spread N slots across the window
with a little deterministic jitter (so it looks human and is identical on every run of the same day)."""
import datetime, random, zoneinfo
from .util import UTC

MAX_PER_DAY = 100          # Instagram's published limit per 24h per account


def tzinfo(name):
    try:
        return zoneinfo.ZoneInfo(name or "Asia/Kolkata")
    except Exception:
        return zoneinfo.ZoneInfo("Asia/Kolkata")


def _hm(v, default):
    try:
        if isinstance(v, (int, float)):
            return int(v * 60)
        h, m = str(v).split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return default


def day_slots(sched, tz, day, route_id=""):
    """Slot datetimes (UTC) for local date `day`."""
    n = max(1, min(int(sched.get("per_day", 10) or 10), MAX_PER_DAY))
    a = _hm(sched.get("start", "10:00"), 600)
    b = _hm(sched.get("end", "22:00"), 1320)
    b = max(b, a + 60)
    b = min(b, 24 * 60 - 1)
    a = min(a, b - 60) if b - 60 < a else a
    gap = (b - a) / n
    jit = max(0.0, min(float(sched.get("jitter", 0.25)), 0.45))
    rng = random.Random(f"{route_id}|{day.isoformat()}")
    minute_marks = []
    for k in range(n):
        m = a + gap * (k + 0.5) + rng.uniform(-jit, jit) * gap
        minute_marks.append(max(a, min(b, m)))
    minute_marks.sort()
    mingap = float(sched.get("min_gap_min", 0) or 0)
    for i in range(1, n):
        if minute_marks[i] - minute_marks[i - 1] < mingap:
            minute_marks[i] = minute_marks[i - 1] + mingap
    base = datetime.datetime.combine(day, datetime.time(0, 0), tzinfo=tz)
    return [(base + datetime.timedelta(minutes=m)).astimezone(UTC) for m in minute_marks]


def due_count(sched, tz, now_utc, posted_today, route_id=""):
    """How many posts this flow may make right now (slots that have passed minus posts already made today)."""
    day = now_utc.astimezone(tz).date()
    slots = day_slots(sched, tz, day, route_id)
    passed = sum(1 for s in slots if s <= now_utc)
    return max(0, min(passed, len(slots)) - posted_today), slots


def next_slot(sched, tz, now_utc, posted_today, route_id=""):
    day = now_utc.astimezone(tz).date()
    slots = day_slots(sched, tz, day, route_id)
    pending = slots[posted_today:] if posted_today < len(slots) else []
    future = [s for s in pending if s > now_utc]
    if future:
        return future[0]
    if pending:   # a post is due now
        return now_utc
    return day_slots(sched, tz, day + datetime.timedelta(days=1), route_id)[0]
