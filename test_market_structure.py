import json
import tempfile
import unittest
from pathlib import Path

from marker_manager import MarkerManager
from market_structure import (
    StructureEvent,
    SwingPoint,
    classify_swings,
    detect_structure_events,
    detect_swings,
)
from structure_notifications import JsonlEventLogger, StructureEventMonitor, publish_new_events


def candle(index, high, low, close=None):
    close = (high + low) // 2 if close is None else close
    open_y = close + 2
    return {
        "x": 100 + index * 8,
        "x1": 99 + index * 8,
        "x2": 101 + index * 8,
        "high": high,
        "low": low,
        "body_top": min(open_y, close),
        "body_bottom": max(open_y, close),
        "direction": "bullish" if close < open_y else "bearish",
    }


class SwingTests(unittest.TestCase):
    def test_detects_and_classifies_pixel_space_swings(self):
        highs = [105, 100, 90, 100, 105, 100, 85, 100, 105, 100, 95]
        lows = [110, 112, 115, 118, 125, 116, 110, 117, 120, 115, 110]
        candles = [candle(i, high, low) for i, (high, low) in enumerate(zip(highs, lows))]

        swings = classify_swings(detect_swings(candles, left=2, right=2))
        summary = [(swing.index, swing.kind, swing.label) for swing in swings]

        self.assertEqual(
            summary,
            [
                (2, "high", None),
                (4, "low", None),
                (6, "high", "HH"),
                (8, "low", "HL"),
            ],
        )


class StructureEventTests(unittest.TestCase):
    def make_sequence(self):
        closes = [110, 105, 110, 98, 100, 105, 88, 100, 100, 114, 110, 112, 120, 120, 127, 115, 103]
        candles = [candle(i, close - 5, close + 5, close) for i, close in enumerate(closes)]
        swings = [
            SwingPoint(1, "high", candles[1]["x"], 100, "HH"),
            SwingPoint(2, "low", candles[2]["x"], 120, "HL"),
            SwingPoint(4, "high", candles[4]["x"], 90, "HH"),
            SwingPoint(5, "low", candles[5]["x"], 115, "HL"),
            SwingPoint(7, "low", candles[7]["x"], 112, "HL"),
            SwingPoint(8, "high", candles[8]["x"], 92, "LH"),
            SwingPoint(10, "low", candles[10]["x"], 118, "LL"),
            SwingPoint(11, "high", candles[11]["x"], 108, "LH"),
            SwingPoint(13, "low", candles[13]["x"], 125, "LL"),
            SwingPoint(15, "high", candles[15]["x"], 105, "HH"),
        ]
        return candles, swings

    def test_bos_counter_and_choch_reset(self):
        candles, swings = self.make_sequence()
        events = detect_structure_events(
            candles,
            swings,
            confirmation_right=0,
            break_buffer=1,
        )
        summary = [
            (event.event_type, event.direction, event.count, event.break_index)
            for event in events
        ]
        self.assertEqual(
            summary,
            [
                ("BOS", "bullish", 1, 3),
                ("BOS", "bullish", 2, 6),
                ("CHoCH", "bearish", 0, 9),
                ("BOS", "bearish", 1, 12),
                ("BOS", "bearish", 2, 14),
                ("CHoCH", "bullish", 0, 16),
            ],
        )

    def test_marker_delete_and_notification_overlap(self):
        candles, swings = self.make_sequence()
        events = detect_structure_events(candles, swings, confirmation_right=0, break_buffer=1)

        manager = MarkerManager(max_markers=3)
        markers = manager.sync(events)
        self.assertEqual(len(markers), 3)
        deleted = manager.delete_at(markers[-1].x2, markers[-1].y)
        self.assertIsNotNone(deleted)
        self.assertEqual(len(manager.sync(events)), 2)

        monitor = StructureEventMonitor()
        self.assertEqual(monitor.update(events[:4]), [])
        self.assertEqual(monitor.update(events[:4]), [])
        self.assertEqual(monitor.update(events[:5]), [events[4]])
        # Simulate the oldest visible event scrolling off the chart.
        self.assertEqual(monitor.update(events[2:]), [events[5]])
        self.assertEqual(monitor.update([]), [])
        self.assertEqual(monitor.update(events[2:]), [])

    def test_jsonl_event_log_contains_data_not_images(self):
        candles, swings = self.make_sequence()
        event = detect_structure_events(candles, swings, confirmation_right=0)[0]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            publish_new_events([event], JsonlEventLogger(path), notifier=None)
            record = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(record["event_type"], "BOS")
        self.assertIn("detected_at", record)
        self.assertNotIn("screenshot", record)


if __name__ == "__main__":
    unittest.main()
