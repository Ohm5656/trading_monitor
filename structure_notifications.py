"""Local-only event logging and notification deduplication."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from market_structure import StructureEvent


class StructureEventMonitor:
    """Find newly appended structure events without alerting at startup."""

    def __init__(self) -> None:
        self._previous: list[tuple[str, str, int]] | None = None

    @staticmethod
    def _maximum_overlap(
        previous: list[tuple[str, str, int]],
        current: list[tuple[str, str, int]],
    ) -> int:
        maximum = min(len(previous), len(current))
        for length in range(maximum, -1, -1):
            if length == 0 or previous[-length:] == current[:length]:
                return length
        return 0

    def update(self, events: Iterable[StructureEvent]) -> list[StructureEvent]:
        current_events = list(events)
        current_keys = [event.semantic_key for event in current_events]

        if self._previous is None:
            self._previous = current_keys
            return []

        # A transient bad frame must not turn the full recovered history into
        # a burst of "new" alerts. Keep the last good sequence while empty.
        if not current_keys:
            return []

        overlap = self._maximum_overlap(self._previous, current_keys)
        if self._previous and overlap == 0:
            # Symbol/timeframe/zoom changed: establish a new baseline instead
            # of notifying every historical structure on the new chart.
            self._previous = current_keys
            return []

        new_events = current_events[overlap:]
        self._previous = current_keys
        return new_events


class JsonlEventLogger:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def write(self, event: StructureEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = event.to_dict()
        record["detected_at"] = datetime.now(timezone.utc).isoformat()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def windows_sound_notification() -> None:
    """Play a local Windows notification sound without extra dependencies."""
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except (ImportError, RuntimeError):
        pass


def publish_new_events(
    events: Iterable[StructureEvent],
    logger: JsonlEventLogger | None,
    notifier: Callable[[], None] | None,
) -> None:
    published = False
    for event in events:
        if logger is not None:
            logger.write(event)
        published = True
    if published and notifier is not None:
        notifier()
