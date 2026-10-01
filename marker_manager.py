"""In-memory structure markers for the transparent overlay."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from market_structure import StructureEvent


@dataclass(frozen=True)
class Marker:
    id: str
    marker_type: str
    direction: str
    count: int
    x1: int
    x2: int
    y: int
    label: str
    alpha: int = 255


class MarkerManager:
    def __init__(self, max_markers: int = 100, max_deleted_ids: int = 500):
        if max_markers < 1:
            raise ValueError("max_markers must be >= 1")
        self.max_markers = max_markers
        self.max_deleted_ids = max_deleted_ids
        self.markers: list[Marker] = []
        self._deleted_ids: set[str] = set()
        self._deleted_order: deque[str] = deque()

    def sync(self, events: Iterable[StructureEvent]) -> list[Marker]:
        visible_events = list(events)[-self.max_markers :]
        total = len(visible_events)
        markers: list[Marker] = []

        for position, event in enumerate(visible_events):
            if event.marker_id in self._deleted_ids:
                continue

            # Keep old context readable but visually subordinate.
            age_fraction = (position + 1) / max(1, total)
            alpha = int(90 + 165 * age_fraction)
            markers.append(
                Marker(
                    id=event.marker_id,
                    marker_type=event.event_type,
                    direction=event.direction,
                    count=event.count,
                    x1=min(event.start_x, event.end_x),
                    x2=max(event.start_x, event.end_x),
                    y=event.level_y,
                    label=event.display_label,
                    alpha=alpha,
                )
            )

        self.markers = markers
        return markers

    def delete(self, marker_id: str) -> bool:
        if marker_id in self._deleted_ids:
            return False

        self._deleted_ids.add(marker_id)
        self._deleted_order.append(marker_id)
        self.markers = [marker for marker in self.markers if marker.id != marker_id]

        while len(self._deleted_order) > self.max_deleted_ids:
            expired = self._deleted_order.popleft()
            self._deleted_ids.discard(expired)
        return True

    def delete_at(self, x: int, y: int, tolerance: int = 8) -> Marker | None:
        # Newest markers win if several lines overlap.
        for marker in reversed(self.markers):
            if marker.x1 - tolerance <= x <= marker.x2 + tolerance:
                if abs(marker.y - y) <= tolerance:
                    self.delete(marker.id)
                    return marker
        return None

    def clear_deleted(self) -> None:
        self._deleted_ids.clear()
        self._deleted_order.clear()
