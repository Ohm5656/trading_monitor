"""Real-time TradingView candle extraction and transparent debug overlay.

The detector keeps every captured frame in memory. It never saves screenshots;
the only drawing is performed by the transparent PyQt overlay.
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np
from mss import MSS

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


# =====================================================
# Calibration - keep screen/theme dependent values here
# =====================================================

DEBUG = True
DEBUG_DRAW_NUMBERS = False
CAPTURE_INTERVAL_MS = 250

# Price scale on the right is intentionally outside this region.
REGION = {
    "left": 70,
    "top": 100,
    "width": 1450,
    "height": 700,
}

# TradingView candle colors in BGR order (OpenCV uses BGR, not RGB).
BULL_COLOR = np.array([245, 121, 49], dtype=np.int16)
BEAR_COLOR = np.array([99, 99, 99], dtype=np.int16)

# Per-channel BGR distance is tolerant of anti-aliasing and uses OpenCV's
# optimized inRange implementation for stable real-time performance.
BULL_COLOR_DISTANCE = 28
BEAR_COLOR_DISTANCE = 20

# Mask out known non-chart UI inside REGION.
CHART_TOP_CROP = 60
TOOLBAR_HEIGHT = 120
TOOLBAR_WIDTH = 280
CHART_RIGHT_CROP = 0

# A long target-colored row is a price/current-price line, not a candle.
HORIZONTAL_LINE_MIN_PIXELS = 100
HORIZONTAL_LINE_MIN_FRACTION = 0.07

# Candle/component limits. Width 1 is allowed for doji/very narrow candles.
MIN_CANDLE_WIDTH = 1
MAX_CANDLE_WIDTH = 12
MIN_CANDLE_HEIGHT = 4
MAX_CANDLE_HEIGHT = 220
MIN_CANDLE_AREA = 4

# Fill a one-pixel vertical gap caused by anti-aliasing or a removed price line.
VERTICAL_CLOSE_GAP = 1

# A body row is wider than the central one-pixel wick.
BODY_ROW_FILL_RATIO = 0.60
MIN_BODY_ROW_WIDTH = 2

# Use the regular TradingView x-grid only to reject isolated false positives.
# Missing candles are not invented because their high/low cannot be inferred.
USE_SPACING_FILTER = True
MIN_CANDIDATES_FOR_SPACING = 8
MIN_CANDLE_PITCH = 3
MAX_CANDLE_PITCH = 30
MAX_SPACING_MULTIPLE = 3

# Windows 10 2004+ can omit this overlay from screen-capture APIs. This is
# essential once structure lines are drawn across the chart.
WDA_EXCLUDEFROMCAPTURE = 0x00000011


@dataclass(frozen=True)
class DetectionDebug:
    pitch: int | None
    raw_candidates: int
    rejected_candidates: int
    horizontal_rows: tuple[int, ...]


LAST_DEBUG = DetectionDebug(None, 0, 0, ())


def exclude_window_from_capture(widget: QWidget) -> bool:
    """Ask Windows to keep an overlay out of MSS/Desktop Duplication frames."""
    try:
        hwnd = int(widget.winId())
        return bool(
            ctypes.windll.user32.SetWindowDisplayAffinity(
                hwnd,
                WDA_EXCLUDEFROMCAPTURE,
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def make_color_mask(
    frame: np.ndarray,
    color: np.ndarray,
    max_distance: int,
) -> np.ndarray:
    """Return a mask using a maximum per-channel distance in BGR space."""
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("frame must be a BGR image with shape (height, width, 3)")

    lower = np.clip(color - max_distance, 0, 255).astype(np.uint8)
    upper = np.clip(color + max_distance, 0, 255).astype(np.uint8)
    return cv2.inRange(frame, lower, upper)


def _remove_ui(mask: np.ndarray) -> None:
    """Remove known TradingView UI areas from a mask in place."""
    height, width = mask.shape
    mask[: min(CHART_TOP_CROP, height), :] = 0
    mask[: min(TOOLBAR_HEIGHT, height), : min(TOOLBAR_WIDTH, width)] = 0

    if CHART_RIGHT_CROP > 0:
        mask[:, max(0, width - CHART_RIGHT_CROP) :] = 0


def build_candle_masks(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Create cleaned bull/bear masks while preserving vertical candle shape."""
    bull_mask = make_color_mask(frame, BULL_COLOR, BULL_COLOR_DISTANCE)
    bear_mask = make_color_mask(frame, BEAR_COLOR, BEAR_COLOR_DISTANCE)

    _remove_ui(bull_mask)
    _remove_ui(bear_mask)

    combined = cv2.bitwise_or(bull_mask, bear_mask)
    row_counts = np.count_nonzero(combined, axis=1)
    line_threshold = max(
        HORIZONTAL_LINE_MIN_PIXELS,
        int(round(frame.shape[1] * HORIZONTAL_LINE_MIN_FRACTION)),
    )
    horizontal_rows_array = np.flatnonzero(row_counts >= line_threshold)

    if horizontal_rows_array.size:
        bull_mask[horizontal_rows_array, :] = 0
        bear_mask[horizontal_rows_array, :] = 0

    if VERTICAL_CLOSE_GAP > 0:
        kernel_height = VERTICAL_CLOSE_GAP * 2 + 1
        vertical_kernel = np.ones((kernel_height, 1), dtype=np.uint8)
        bull_mask = cv2.morphologyEx(
            bull_mask,
            cv2.MORPH_CLOSE,
            vertical_kernel,
        )
        bear_mask = cv2.morphologyEx(
            bear_mask,
            cv2.MORPH_CLOSE,
            vertical_kernel,
        )

    return bull_mask, bear_mask, tuple(map(int, horizontal_rows_array))


def _longest_consecutive_run(values: np.ndarray) -> tuple[int, int] | None:
    """Return inclusive bounds of the longest consecutive integer run."""
    if values.size == 0:
        return None

    split_points = np.flatnonzero(np.diff(values) > 1) + 1
    runs = np.split(values, split_points)
    longest = max(runs, key=len)
    return int(longest[0]), int(longest[-1])


def _body_bounds(
    component_mask: np.ndarray,
    y_offset: int,
) -> tuple[int, int]:
    """Separate the wide body rows from the one-pixel wick rows."""
    row_widths = np.count_nonzero(component_mask, axis=1)
    maximum_width = int(row_widths.max(initial=0))

    if maximum_width <= 1:
        # A one-pixel doji has no reliable visual body/wick distinction.
        densest_y = int(np.argmax(row_widths)) + y_offset
        return densest_y, densest_y

    body_row_width = max(
        MIN_BODY_ROW_WIDTH,
        int(np.ceil(maximum_width * BODY_ROW_FILL_RATIO)),
    )
    body_rows = np.flatnonzero(row_widths >= body_row_width)
    run = _longest_consecutive_run(body_rows)

    if run is None:
        densest_y = int(np.argmax(row_widths)) + y_offset
        return densest_y, densest_y

    return run[0] + y_offset, run[1] + y_offset


def _components_to_candles(
    mask: np.ndarray,
    direction: str,
) -> list[dict[str, int | str]]:
    """Turn same-color connected components into candle records."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask,
        connectivity=8,
    )
    candles: list[dict[str, int | str]] = []

    for label in range(1, count):
        x, y, width, height, area = map(int, stats[label])

        if not MIN_CANDLE_WIDTH <= width <= MAX_CANDLE_WIDTH:
            continue
        if not MIN_CANDLE_HEIGHT <= height <= MAX_CANDLE_HEIGHT:
            continue
        if area < MIN_CANDLE_AREA:
            continue

        local_labels = labels[y : y + height, x : x + width]
        component_mask = local_labels == label
        body_top, body_bottom = _body_bounds(component_mask, y)
        center_x = x + (width - 1) // 2

        candles.append(
            {
                "x": center_x,
                "x1": x,
                "x2": x + width - 1,
                "high": y,
                "low": y + height - 1,
                "body_top": body_top,
                "body_bottom": body_bottom,
                "width": width,
                "height": height,
                "direction": direction,
            }
        )

    return candles


def _estimate_candle_pitch(candles: list[dict[str, int | str]]) -> int | None:
    """Estimate the dominant distance between neighboring candle centers."""
    if len(candles) < MIN_CANDIDATES_FOR_SPACING:
        return None

    centers = np.array(sorted(int(candle["x"]) for candle in candles))
    distances = np.diff(centers)
    distances = distances[
        (distances >= MIN_CANDLE_PITCH) & (distances <= MAX_CANDLE_PITCH)
    ]
    if distances.size == 0:
        return None

    histogram = np.bincount(distances, minlength=MAX_CANDLE_PITCH + 1)
    return int(np.argmax(histogram[MIN_CANDLE_PITCH:]) + MIN_CANDLE_PITCH)


def _has_grid_neighbor(center: int, centers: np.ndarray, pitch: int) -> bool:
    tolerance = max(1, int(round(pitch * 0.25)))
    distances = np.abs(centers - center)

    for multiple in range(1, MAX_SPACING_MULTIPLE + 1):
        expected = pitch * multiple
        if np.any(np.abs(distances - expected) <= tolerance * multiple):
            return True
    return False


def _filter_by_spacing(
    candles: list[dict[str, int | str]],
) -> tuple[list[dict[str, int | str]], int | None]:
    """Reject only isolated candidates; never synthesize missing OHLC data."""
    pitch = _estimate_candle_pitch(candles)
    if pitch is None or not USE_SPACING_FILTER:
        return candles, pitch

    centers = np.array([int(candle["x"]) for candle in candles])
    filtered = [
        candle
        for candle in candles
        if _has_grid_neighbor(int(candle["x"]), centers, pitch)
    ]
    return filtered, pitch


def detect_candles(frame: np.ndarray) -> list[dict[str, int | str]]:
    """Extract candle pixel geometry, sorted from left to right."""
    global LAST_DEBUG

    bull_mask, bear_mask, horizontal_rows = build_candle_masks(frame)
    candidates = _components_to_candles(bull_mask, "bullish")
    candidates.extend(_components_to_candles(bear_mask, "bearish"))
    candidates.sort(key=lambda candle: int(candle["x"]))

    candles, pitch = _filter_by_spacing(candidates)
    candles.sort(key=lambda candle: int(candle["x"]))

    LAST_DEBUG = DetectionDebug(
        pitch=pitch,
        raw_candidates=len(candidates),
        rejected_candidates=len(candidates) - len(candles),
        horizontal_rows=horizontal_rows,
    )
    return candles


class CandleOverlay(QWidget):
    """Click-through transparent overlay for real-time detector diagnostics."""

    def __init__(self) -> None:
        super().__init__()
        self.candles: list[dict[str, int | str]] = []
        self.processing_ms = 0.0
        self.error_message = ""
        self.capture_excluded = False
        self.sct = MSS()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.capture_excluded = exclude_window_from_capture(self)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_detection)
        self.timer.start(CAPTURE_INTERVAL_MS)

    def update_detection(self) -> None:
        started = time.perf_counter()
        try:
            screenshot = self.sct.grab(REGION)
            frame = np.asarray(screenshot)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            self.candles = detect_candles(frame)
            self.error_message = ""
        except Exception as error:  # Keep the overlay alive for calibration.
            self.candles = []
            self.error_message = f"{type(error).__name__}: {error}"

        self.processing_ms = (time.perf_counter() - started) * 1000.0
        print(
            f"\rDetected candles: {len(self.candles):3d} | "
            f"{self.processing_ms:6.1f} ms",
            end="",
            flush=True,
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not DEBUG:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        candle_pen = QPen(QColor(255, 220, 0), 1)
        body_pen = QPen(QColor(0, 255, 255), 1)
        number_font = QFont("Arial", 7)

        for number, candle in enumerate(self.candles, start=1):
            x1 = REGION["left"] + int(candle["x1"])
            x2 = REGION["left"] + int(candle["x2"])
            high = REGION["top"] + int(candle["high"])
            low = REGION["top"] + int(candle["low"])
            body_top = REGION["top"] + int(candle["body_top"])
            body_bottom = REGION["top"] + int(candle["body_bottom"])

            # Draw one pixel outside the detected pixels. MSS also sees this
            # overlay, so painting directly on a 3 px candle would hide its
            # source color from the next detection cycle and cause flicker.
            painter.setPen(candle_pen)
            painter.drawRect(
                x1 - 1,
                high - 1,
                max(1, x2 - x1 + 2),
                max(1, low - high + 2),
            )

            painter.setPen(body_pen)
            painter.drawRect(
                x1 - 1,
                body_top - 1,
                max(1, x2 - x1 + 2),
                max(1, body_bottom - body_top + 2),
            )

            if DEBUG_DRAW_NUMBERS:
                painter.setFont(number_font)
                painter.setPen(QColor(255, 255, 0))
                painter.drawText(x1, max(REGION["top"] + 8, high - 2), str(number))

        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))
        pitch_text = "?" if LAST_DEBUG.pitch is None else str(LAST_DEBUG.pitch)
        status = (
            f"V1 Candle Detector | {len(self.candles)} candles | "
            f"pitch {pitch_text}px | {self.processing_ms:.1f} ms | "
            f"capture-safe {'yes' if self.capture_excluded else 'no'}"
        )
        # Keep status inside CHART_TOP_CROP so it cannot hide candle pixels
        # that the next MSS frame needs to analyze.
        painter.drawText(REGION["left"] + 10, REGION["top"] + 25, status)

        if self.error_message:
            painter.setPen(QColor(255, 90, 90))
            painter.drawText(
                REGION["left"] + 10,
                REGION["top"] + 48,
                self.error_message,
            )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.timer.stop()
        self.sct.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    overlay = CandleOverlay()
    overlay.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
