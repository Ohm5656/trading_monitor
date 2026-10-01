import unittest

import cv2
import numpy as np

import v1_candle_detector as detector


class CandleDetectorTests(unittest.TestCase):
    def make_frame(self):
        frame = np.full((220, 500, 3), (36, 25, 21), dtype=np.uint8)
        expected = []

        for index, x in enumerate(range(310, 390, 8)):
            high = 74 + index * 2
            low = high + 42
            body_top = high + 9
            body_bottom = low - 8
            direction = "bullish" if index % 2 == 0 else "bearish"
            base_color = (
                detector.BULL_COLOR if direction == "bullish" else detector.BEAR_COLOR
            ).astype(np.int16)
            # Use slightly shifted colors to exercise color-distance matching.
            shift = np.array([4, -5, 3]) if direction == "bullish" else np.array([6, 2, -4])
            color = tuple(map(int, np.clip(base_color + shift, 0, 255)))

            cv2.line(frame, (x, high), (x, low), color, 1)
            cv2.rectangle(frame, (x - 1, body_top), (x + 1, body_bottom), color, -1)
            expected.append((x, high, low, body_top, body_bottom, direction))

        # This exact bear-color line crosses and temporarily joins candles.
        cv2.line(frame, (0, 110), (499, 110), (99, 99, 99), 1)

        # Target-colored UI-like objects in ignored regions must not survive.
        cv2.rectangle(frame, (20, 10), (24, 30), (245, 121, 49), -1)
        cv2.rectangle(frame, (100, 70), (104, 90), (99, 99, 99), -1)
        return frame, expected

    def test_extracts_geometry_direction_and_repairs_price_line_gap(self):
        frame, expected = self.make_frame()
        candles = detector.detect_candles(frame)

        self.assertEqual(len(candles), len(expected))
        self.assertEqual(detector.LAST_DEBUG.pitch, 8)
        self.assertIn(110, detector.LAST_DEBUG.horizontal_rows)

        for candle, expected_candle in zip(candles, expected, strict=True):
            x, high, low, body_top, body_bottom, direction = expected_candle
            self.assertEqual(candle["x"], x)
            self.assertEqual(candle["high"], high)
            self.assertEqual(candle["low"], low)
            self.assertEqual(candle["direction"], direction)
            # If the removed horizontal line lies exactly on a body edge,
            # the original edge is unknowable to within one pixel.
            self.assertLessEqual(abs(candle["body_top"] - body_top), 1)
            self.assertLessEqual(abs(candle["body_bottom"] - body_bottom), 1)

    def test_debug_boxes_outside_candles_do_not_change_detection(self):
        frame, _ = self.make_frame()
        original = detector.detect_candles(frame)
        with_debug = frame.copy()

        for candle in original:
            cv2.rectangle(
                with_debug,
                (candle["x1"] - 1, candle["high"] - 1),
                (candle["x2"] + 1, candle["low"] + 1),
                (0, 220, 255),
                1,
            )
            cv2.rectangle(
                with_debug,
                (candle["x1"] - 1, candle["body_top"] - 1),
                (candle["x2"] + 1, candle["body_bottom"] + 1),
                (255, 255, 0),
                1,
            )

        repeated = detector.detect_candles(with_debug)
        self.assertEqual(repeated, original)


if __name__ == "__main__":
    unittest.main()
