"""Complete local TradingView market-structure monitor (V1-V6)."""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from mss import MSS
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

import v1_candle_detector as candle_detector
from marker_manager import Marker, MarkerManager
from market_structure import StructureEvent, SwingPoint, analyze_market_structure
from structure_notifications import (
    JsonlEventLogger,
    StructureEventMonitor,
    publish_new_events,
    windows_sound_notification,
)


# =====================================================
# Market-structure calibration
# =====================================================

CAPTURE_INTERVAL_MS = 250
SWING_LEFT = 2
SWING_RIGHT = 2
SWING_EQUALITY_TOLERANCE = 1
BREAK_BUFFER_PIXELS = 1

SHOW_CANDLE_DEBUG = False
SHOW_SWINGS = True
SHOW_STRUCTURE_MARKERS = True
MAX_STRUCTURE_MARKERS = 100

ENABLE_EVENT_LOG = True
EVENT_LOG_PATH = Path(__file__).with_name("logs") / "structure_events.jsonl"
ENABLE_SOUND_NOTIFICATION = True
NOTIFICATION_SECONDS = 3.0

EDIT_MODE_HOTKEY = 0x77  # F8
MARKER_DELETE_TOLERANCE = 8


def _f8_is_down() -> bool:
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(EDIT_MODE_HOTKEY) & 0x8000)
    except (AttributeError, OSError):
        return False


class MarketStructureOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.sct = MSS()
        self.candles: list[dict[str, int | str]] = []
        self.swings: list[SwingPoint] = []
        self.events: list[StructureEvent] = []
        self.marker_manager = MarkerManager(MAX_STRUCTURE_MARKERS)
        self.event_monitor = StructureEventMonitor()
        self.event_logger = JsonlEventLogger(EVENT_LOG_PATH) if ENABLE_EVENT_LOG else None

        self.processing_ms = 0.0
        self.error_message = ""
        self.notification_text = ""
        self.notification_until = 0.0
        self.edit_mode = False
        self._f8_was_down = False
        self.capture_excluded = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.capture_excluded = candle_detector.exclude_window_from_capture(self)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_monitor)
        self.timer.start(CAPTURE_INTERVAL_MS)

    def _poll_edit_hotkey(self) -> None:
        is_down = _f8_is_down()
        if is_down and not self._f8_was_down:
            self.set_edit_mode(not self.edit_mode)
        self._f8_was_down = is_down

    def set_edit_mode(self, enabled: bool) -> None:
        if enabled == self.edit_mode:
            return

        self.edit_mode = enabled
        flags = self.windowFlags()
        if enabled:
            flags &= ~Qt.WindowType.WindowTransparentForInput
        else:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.show()
        # setWindowFlags recreates the native window, so apply affinity again.
        self.capture_excluded = candle_detector.exclude_window_from_capture(self)
        self.update()

    def _grab_frame(self) -> np.ndarray:
        if self.capture_excluded:
            screenshot = self.sct.grab(candle_detector.REGION)
        else:
            # Safe fallback for older Windows builds. It may briefly flicker,
            # but prevents structure lines feeding back into candle detection.
            self.hide()
            QApplication.processEvents()
            screenshot = self.sct.grab(candle_detector.REGION)
            self.show()
            QApplication.processEvents()

        frame = np.asarray(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def update_monitor(self) -> None:
        self._poll_edit_hotkey()
        started = time.perf_counter()

        try:
            frame = self._grab_frame()
            self.candles = candle_detector.detect_candles(frame)
            self.swings, self.events = analyze_market_structure(
                self.candles,
                swing_left=SWING_LEFT,
                swing_right=SWING_RIGHT,
                equality_tolerance=SWING_EQUALITY_TOLERANCE,
                break_buffer=BREAK_BUFFER_PIXELS,
            )
            self.marker_manager.sync(self.events)

            new_events = self.event_monitor.update(self.events)
            publish_new_events(
                new_events,
                self.event_logger,
                windows_sound_notification if ENABLE_SOUND_NOTIFICATION else None,
            )
            if new_events:
                newest = new_events[-1]
                self.notification_text = (
                    f"{newest.display_label} | {newest.direction.title()}"
                )
                self.notification_until = time.monotonic() + NOTIFICATION_SECONDS

            self.error_message = ""
        except KeyboardInterrupt:
            QApplication.quit()
            return
        except Exception as error:  # Keep calibration information visible.
            self.candles = []
            self.swings = []
            self.events = []
            self.marker_manager.sync(())
            self.error_message = f"{type(error).__name__}: {error}"

        self.processing_ms = (time.perf_counter() - started) * 1000.0
        print(
            f"\rCandles {len(self.candles):3d} | Swings {len(self.swings):3d} | "
            f"Events {len(self.events):3d} | {self.processing_ms:6.1f} ms",
            end="",
            flush=True,
        )
        self.update()

    def _screen_x(self, x: int) -> int:
        return candle_detector.REGION["left"] + x

    def _screen_y(self, y: int) -> int:
        return candle_detector.REGION["top"] + y

    def _draw_candle_debug(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(255, 220, 0, 180), 1))
        for candle in self.candles:
            x1 = self._screen_x(int(candle["x1"])) - 1
            x2 = self._screen_x(int(candle["x2"])) + 1
            high = self._screen_y(int(candle["high"])) - 1
            low = self._screen_y(int(candle["low"])) + 1
            painter.drawRect(x1, high, max(1, x2 - x1), max(1, low - high))

    def _draw_swings(self, painter: QPainter) -> None:
        painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        for swing in self.swings:
            x = self._screen_x(swing.x)
            y = self._screen_y(swing.y)

            if swing.kind == "high":
                color = QColor(255, 190, 60, 210)
                painter.setPen(QPen(color, 1))
                painter.drawLine(x - 3, y - 4, x, y - 1)
                painter.drawLine(x, y - 1, x + 3, y - 4)
                painter.drawText(x - 9, y - 7, swing.display_label)
            else:
                color = QColor(90, 190, 255, 210)
                painter.setPen(QPen(color, 1))
                painter.drawLine(x - 3, y + 4, x, y + 1)
                painter.drawLine(x, y + 1, x + 3, y + 4)
                painter.drawText(x - 9, y + 14, swing.display_label)

    def _draw_marker(self, painter: QPainter, marker: Marker) -> None:
        if marker.direction == "bullish":
            color = QColor(65, 230, 130, marker.alpha)
        else:
            color = QColor(255, 90, 105, marker.alpha)

        width = 3 if marker.marker_type == "CHoCH" else 2
        painter.setPen(QPen(color, width))
        x1 = self._screen_x(marker.x1)
        x2 = self._screen_x(marker.x2)
        y = self._screen_y(marker.y)
        painter.drawLine(x1, y, x2, y)

        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        label_width = painter.fontMetrics().horizontalAdvance(marker.label)
        painter.drawText(max(x1, (x1 + x2 - label_width) // 2), y - 5, marker.label)

    def _draw_status(self, painter: QPainter) -> None:
        x = candle_detector.REGION["left"] + 10
        y = candle_detector.REGION["top"] + 25
        pitch = candle_detector.LAST_DEBUG.pitch
        mode = "EDIT (click marker to delete)" if self.edit_mode else "NORMAL (F8: edit)"
        capture_state = "safe" if self.capture_excluded else "hide/grab fallback"

        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            x,
            y,
            f"Market Structure Monitor | C {len(self.candles)} | "
            f"S {len(self.swings)} | E {len(self.events)} | "
            f"pitch {pitch or '?'}px | {self.processing_ms:.1f} ms | {capture_state}",
        )

        painter.setPen(QColor(255, 210, 70) if self.edit_mode else QColor(180, 180, 180))
        painter.drawText(x, y + 20, mode)

        if self.error_message:
            painter.setPen(QColor(255, 80, 80))
            painter.drawText(x, y + 40, self.error_message)

    def _draw_notification(self, painter: QPainter) -> None:
        if not self.notification_text or time.monotonic() >= self.notification_until:
            return

        right = candle_detector.REGION["left"] + candle_detector.REGION["width"] - 20
        top = candle_detector.REGION["top"] + 20
        painter.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        text_width = painter.fontMetrics().horizontalAdvance(self.notification_text)
        painter.fillRect(right - text_width - 28, top, text_width + 28, 36, QColor(10, 10, 10, 210))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(right - text_width - 14, top + 25, self.notification_text)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if SHOW_CANDLE_DEBUG:
            self._draw_candle_debug(painter)
        if SHOW_SWINGS:
            self._draw_swings(painter)
        if SHOW_STRUCTURE_MARKERS:
            for marker in self.marker_manager.markers:
                self._draw_marker(painter, marker)

        self._draw_status(painter)
        self._draw_notification(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if self.edit_mode and event.button() == Qt.MouseButton.LeftButton:
            local_x = int(event.position().x()) - candle_detector.REGION["left"]
            local_y = int(event.position().y()) - candle_detector.REGION["top"]
            deleted = self.marker_manager.delete_at(
                local_x,
                local_y,
                tolerance=MARKER_DELETE_TOLERANCE,
            )
            if deleted is not None:
                self.notification_text = f"Deleted {deleted.label}"
                self.notification_until = time.monotonic() + 1.5
                self.update()
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.timer.stop()
        self.sct.close()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    overlay = MarketStructureOverlay()
    overlay.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
