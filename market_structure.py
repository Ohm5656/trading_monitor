"""Pure market-structure calculations using candle pixel coordinates.

Screen coordinates are inverted versus price: a smaller y is a higher price.
The module deliberately contains no capture, GUI, broker, or order logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Iterable, Literal, Mapping


SwingKind = Literal["high", "low"]
Direction = Literal["bullish", "bearish"]
EventType = Literal["BOS", "CHoCH"]


@dataclass(frozen=True)
class SwingPoint:
    index: int
    kind: SwingKind
    x: int
    y: int
    label: str | None = None

    @property
    def display_label(self) -> str:
        if self.label:
            return self.label
        return "Swing High" if self.kind == "high" else "Swing Low"


@dataclass(frozen=True)
class StructureEvent:
    event_type: EventType
    direction: Direction
    count: int
    break_index: int
    swing_index: int
    start_x: int
    end_x: int
    level_y: int
    break_y: int

    @property
    def display_label(self) -> str:
        if self.event_type == "BOS":
            return f"BOS #{self.count}"
        return f"{self.direction.title()} CHoCH"

    @property
    def semantic_key(self) -> tuple[str, str, int]:
        return self.event_type, self.direction, self.count

    @property
    def marker_id(self) -> str:
        return (
            f"{self.event_type}:{self.direction}:{self.count}:"
            f"{self.swing_index}:{self.break_index}"
        )

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def _int(candle: Mapping[str, int | str], key: str) -> int:
    return int(candle[key])


def candle_close_y(candle: Mapping[str, int | str]) -> int:
    """Return the close pixel using body direction."""
    if candle["direction"] == "bullish":
        return _int(candle, "body_top")
    return _int(candle, "body_bottom")


def detect_swings(
    candles: list[Mapping[str, int | str]],
    left: int = 2,
    right: int = 2,
) -> list[SwingPoint]:
    """Detect strict pivot highs/lows from candle wick pixels."""
    if left < 1 or right < 1:
        raise ValueError("left and right pivot windows must both be >= 1")
    if len(candles) < left + right + 1:
        return []

    swings: list[SwingPoint] = []
    for index in range(left, len(candles) - right):
        candle = candles[index]
        neighbors = candles[index - left : index] + candles[index + 1 : index + right + 1]
        high = _int(candle, "high")
        low = _int(candle, "low")

        # Strict comparisons intentionally reject equal-height plateaus. This
        # avoids two adjacent candles claiming the same structural pivot.
        if all(high < _int(other, "high") for other in neighbors):
            swings.append(
                SwingPoint(index, "high", _int(candle, "x"), high)
            )

        if all(low > _int(other, "low") for other in neighbors):
            swings.append(
                SwingPoint(index, "low", _int(candle, "x"), low)
            )

    swings.sort(key=lambda swing: (swing.index, swing.kind))
    return swings


def classify_swings(
    swings: Iterable[SwingPoint],
    equality_tolerance: int = 1,
) -> list[SwingPoint]:
    """Classify pivots as HH/LH and HL/LL in pixel-price space."""
    if equality_tolerance < 0:
        raise ValueError("equality_tolerance must be >= 0")

    previous: dict[SwingKind, SwingPoint] = {}
    classified: list[SwingPoint] = []

    for swing in sorted(swings, key=lambda item: (item.index, item.kind)):
        prior = previous.get(swing.kind)
        label: str | None = None

        if prior is not None and swing.kind == "high":
            label = "HH" if swing.y < prior.y - equality_tolerance else "LH"
        elif prior is not None:
            label = "LL" if swing.y > prior.y + equality_tolerance else "HL"

        current = replace(swing, label=label)
        classified.append(current)
        previous[swing.kind] = current

    return classified


def _infer_initial_trend(
    latest_high: SwingPoint | None,
    latest_low: SwingPoint | None,
) -> Direction | None:
    if latest_high is None or latest_low is None:
        return None
    if latest_high.label == "HH" and latest_low.label == "HL":
        return "bullish"
    if latest_high.label == "LH" and latest_low.label == "LL":
        return "bearish"
    return None


def detect_structure_events(
    candles: list[Mapping[str, int | str]],
    swings: Iterable[SwingPoint],
    confirmation_right: int = 2,
    break_buffer: int = 1,
) -> list[StructureEvent]:
    """Detect close-confirmed BOS/CHoCH events and directional BOS counts.

    A pivot becomes usable only after ``confirmation_right`` candles. Once a
    trend exists, breaking its continuation level is BOS; breaking the
    opposite protected level is CHoCH and resets the BOS counter.
    """
    if confirmation_right < 0:
        raise ValueError("confirmation_right must be >= 0")
    if break_buffer < 0:
        raise ValueError("break_buffer must be >= 0")

    confirmations: dict[int, list[SwingPoint]] = {}
    for swing in swings:
        confirm_index = swing.index + confirmation_right
        confirmations.setdefault(confirm_index, []).append(swing)

    latest_high: SwingPoint | None = None
    latest_low: SwingPoint | None = None
    trend: Direction | None = None
    bos_count = 0
    broken_levels: set[tuple[SwingKind, int]] = set()
    events: list[StructureEvent] = []

    for index, candle in enumerate(candles):
        for swing in confirmations.get(index, ()):
            if swing.kind == "high":
                latest_high = swing
            else:
                latest_low = swing

        if trend is None:
            inferred = _infer_initial_trend(latest_high, latest_low)
            if inferred is not None:
                trend = inferred
                bos_count = 0

        if trend is None:
            continue

        close_y = candle_close_y(candle)

        high_is_fresh = (
            latest_high is not None
            and index > latest_high.index
            and ("high", latest_high.index) not in broken_levels
        )
        low_is_fresh = (
            latest_low is not None
            and index > latest_low.index
            and ("low", latest_low.index) not in broken_levels
        )
        breaks_high = (
            high_is_fresh and close_y < latest_high.y - break_buffer
        )
        breaks_low = (
            low_is_fresh and close_y > latest_low.y + break_buffer
        )

        event_type: EventType | None = None
        direction: Direction | None = None
        level: SwingPoint | None = None

        if trend == "bullish":
            if breaks_low:
                event_type, direction, level = "CHoCH", "bearish", latest_low
                trend, bos_count = "bearish", 0
            elif breaks_high:
                event_type, direction, level = "BOS", "bullish", latest_high
                bos_count += 1
        else:
            if breaks_high:
                event_type, direction, level = "CHoCH", "bullish", latest_high
                trend, bos_count = "bullish", 0
            elif breaks_low:
                event_type, direction, level = "BOS", "bearish", latest_low
                bos_count += 1

        if event_type is None or direction is None or level is None:
            continue

        broken_levels.add((level.kind, level.index))
        events.append(
            StructureEvent(
                event_type=event_type,
                direction=direction,
                count=bos_count if event_type == "BOS" else 0,
                break_index=index,
                swing_index=level.index,
                start_x=level.x,
                end_x=_int(candle, "x"),
                level_y=level.y,
                break_y=close_y,
            )
        )

    return events


def analyze_market_structure(
    candles: list[Mapping[str, int | str]],
    swing_left: int = 2,
    swing_right: int = 2,
    equality_tolerance: int = 1,
    break_buffer: int = 1,
) -> tuple[list[SwingPoint], list[StructureEvent]]:
    swings = classify_swings(
        detect_swings(candles, swing_left, swing_right),
        equality_tolerance,
    )
    events = detect_structure_events(
        candles,
        swings,
        confirmation_right=swing_right,
        break_buffer=break_buffer,
    )
    return swings, events
