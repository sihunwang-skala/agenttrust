"""Injectable clock so expiry logic is testable deterministically."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class Clock:
    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + self._offset

    def advance(self, seconds: float) -> None:  # tests only
        self._offset += timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
