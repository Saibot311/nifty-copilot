"""A ceiling on paid calls.

Every Copilot question costs a model call plus the guards' calls, and the
endpoint had no limit: a paired phone, or any program on this Mac, could
loop it. A small in-process budget: so many a minute (a sliding window) and
so many a calendar day. One user, one process, so nothing to share."""

from collections import deque
from datetime import datetime, timedelta


class Budget:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute, self.per_day = per_minute, per_day
        self._recent: deque[datetime] = deque()
        self._day = None
        self._today = 0

    def take(self, now: datetime | None = None) -> int | None:
        """Spend one call. None if allowed; otherwise the seconds to wait. A
        refused call spends nothing."""
        now = now or datetime.now()
        if now.date() != self._day:
            self._day, self._today = now.date(), 0
        while self._recent and now - self._recent[0] >= timedelta(minutes=1):
            self._recent.popleft()
        if self._today >= self.per_day:
            midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo)
            return int((midnight - now).total_seconds()) + 1
        if len(self._recent) >= self.per_minute:
            return int((self._recent[0] + timedelta(minutes=1) - now).total_seconds()) + 1
        self._recent.append(now)
        self._today += 1
        return None
