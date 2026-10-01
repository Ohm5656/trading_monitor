# TradingView Market Structure Monitor

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-Array%20Engine-013243?style=for-the-badge&logo=numpy&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-Overlay%20UI-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-Local%20Desktop-0078D4?style=for-the-badge&logo=windows&logoColor=white)

A local Windows desktop monitor that reads TradingView candles directly from the screen, detects market structure, and draws BOS / CHoCH markers through a transparent always-on-top overlay.

No TradingView API. No cloud service. No broker integration. No automated order execution.

## Highlights

- Detects candles from pixel color and geometry: `x`, `high`, `low`, `body_top`, `body_bottom`, `direction`
- Finds strict pivot-based Swing High / Swing Low points
- Classifies structure as `HH`, `HL`, `LH`, and `LL`
- Detects close-confirmed `BOS` and `CHoCH` events
- Resets the BOS counter after every CHoCH
- Draws live marker lines and labels on a transparent overlay
- Supports manual marker deletion in edit mode
- Plays local sound alerts and writes new events to JSONL
- Avoids saving screenshots during normal operation

## Tech Stack

| Layer | Technology | Purpose |
| --- | --- | --- |
| Runtime | Python | Main application and structure engine |
| Capture | MSS | Fast local screen capture |
| Vision | OpenCV + NumPy | Candle color masks, morphology, and component extraction |
| UI | PyQt6 | Transparent always-on-top overlay |
| OS Integration | Win32 APIs via `ctypes` | Click-through windows, capture exclusion, hotkeys |
| Tests | `unittest` | Detector and market-structure verification |

## Quick Start

Open TradingView in fullscreen with the expected dark theme and candle colors, then run:

```powershell
.\.venv\Scripts\Activate.ps1
python .\trading_monitor.py
```

Run the core tests:

```powershell
python -m unittest -v test_v1_candle_detector test_market_structure
```

## Controls

- `F8`: Toggle between Normal mode and Edit mode
- Normal mode: the overlay is click-through, so TradingView remains interactive
- Edit mode: click near a BOS / CHoCH marker line to delete it, then press `F8` again to return to Normal mode

## Calibration

The detector is tuned for a fixed fullscreen TradingView layout. Screen position, candle colors, and filter thresholds live near the top of `v1_candle_detector.py`.

Important detector settings:

- `REGION`: screen capture rectangle
- Bull / bear BGR color targets
- Color tolerance
- Candle body and wick size filters
- UI exclusion zones

Market-structure settings live near the top of `trading_monitor.py`:

- `SWING_LEFT` / `SWING_RIGHT`: pivot window size
- `SWING_EQUALITY_TOLERANCE`: equal high / low tolerance in pixels
- `BREAK_BUFFER_PIXELS`: close-confirmation buffer
- `SHOW_CANDLE_DEBUG`, `SHOW_SWINGS`, `SHOW_STRUCTURE_MARKERS`
- `ENABLE_EVENT_LOG`, `ENABLE_SOUND_NOTIFICATION`

If TradingView is resized, moved, themed differently, or split with another window, update `REGION` and the candle colors before relying on detections.

## Structure Rules

- Lower pixel `y` means a higher price
- Swing pivots use strict comparison to avoid duplicate plateau pivots
- Bullish close uses `body_top`
- Bearish close uses `body_bottom`
- BOS means a break in the current trend direction
- CHoCH means a break of the protected swing against the current trend
- Wick-only breaks are ignored; the candle body close must confirm the break

## Event Log

New live events are appended to:

```text
logs/structure_events.jsonl
```

The event log stores structured event data only. It does not store screenshots. Startup historical events are ignored so the app does not alert on old structure when it first opens.

## Project Layout

```text
trading_monitor.py           # Real-time app and overlay
v1_candle_detector.py        # Screen capture and candle extraction
market_structure.py          # Swing, BOS, and CHoCH engine
marker_manager.py            # Marker lifecycle and manual deletion
structure_notifications.py   # Event dedupe, sound, and JSONL logging
test_v1_candle_detector.py   # Candle detector tests
test_market_structure.py     # Market-structure tests
test_capture.py              # Manual capture helper
test_overlay.py              # Manual overlay helper
```

## Safety Boundary

This project is a local visual monitor only. It does not place trades, manage broker accounts, or provide financial advice. Treat all signals as visual aids that still require human review.
