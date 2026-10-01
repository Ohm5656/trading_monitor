# TradingView Market Structure Monitor

โปรแกรม Windows แบบ local สำหรับอ่านกราฟ TradingView จากหน้าจอและวาด Market Structure ผ่าน transparent overlay โดยไม่ใช้ TradingView API, cloud API หรือระบบส่งคำสั่งซื้อขาย

## ความสามารถ

- ตรวจ candle จากสีและรูปทรง: `x`, `high`, `low`, `body_top`, `body_bottom`, `direction`
- ตรวจ Swing High / Swing Low ด้วย pivot window
- จัดประเภท HH / HL / LH / LL
- ตรวจ BOS และ CHoCH จากการปิดของ body เหนือ/ใต้ swing level
- นับ BOS ใหม่จาก `#1` หลัง CHoCH ทุกครั้ง
- วาด marker และ label บน transparent always-on-top overlay
- F8 สลับ Normal/Edit mode; ใน Edit mode คลิกเส้น marker เพื่อลบ
- แจ้งเตือนด้วยเสียงและเขียน event ใหม่เป็น JSONL
- ไม่บันทึก screenshot ระหว่างทำงาน

## เริ่มใช้งาน

ให้เปิด TradingView เต็มหน้าจอด้วย Dark theme และสี candle ตามค่าที่กำหนด จากนั้นรัน:

```powershell
.\.venv\Scripts\Activate.ps1
python .\trading_monitor.py
```

ทดสอบทั้งหมด:

```powershell
python -m unittest -v test_v1_candle_detector.py test_market_structure.py
```

## การควบคุม

- `F8`: สลับ Normal/Edit mode
- Normal mode: overlay เป็น click-through ใช้งาน TradingView ได้ตามปกติ
- Edit mode: คลิกใกล้เส้น BOS/CHoCH เพื่อลบ marker นั้น แล้วกด F8 เพื่อกลับ Normal mode

## Calibration

ค่าหน้าจอ สี และ candle filters อยู่ตอนต้นของ `v1_candle_detector.py` ได้แก่ `REGION`, สี bull/bear, color distance และขนาด candle

ค่า market structure อยู่ตอนต้นของ `trading_monitor.py` ได้แก่:

- `SWING_LEFT` / `SWING_RIGHT`: ค่าเริ่มต้น 2/2
- `SWING_EQUALITY_TOLERANCE`: tolerance ของ equal high/low
- `BREAK_BUFFER_PIXELS`: ระยะปิดทะลุ swing เพื่อยืนยัน break
- `SHOW_CANDLE_DEBUG`, `SHOW_SWINGS`, `SHOW_STRUCTURE_MARKERS`
- `ENABLE_EVENT_LOG`, `ENABLE_SOUND_NOTIFICATION`

ROI ปัจจุบันออกแบบสำหรับ TradingView เต็มหน้าจอ หากย่อหรือแบ่งหน้าจอ ต้องปรับ `REGION` ไม่เช่นนั้น detector อาจอ่าน UI ของโปรแกรมอื่น

## นิยาม Structure

- Pixel Y น้อยกว่า = ราคาสูงกว่า
- Swing ต้องต่ำ/สูงกว่าเพื่อนบ้านแบบ strict เพื่อไม่สร้าง pivot ซ้ำบน plateau
- Bullish close = `body_top`; bearish close = `body_bottom`
- BOS คือ break ตาม trend ปัจจุบัน
- CHoCH คือ break protected swing ฝั่งตรงข้าม และ reset BOS counter
- ใช้ close-confirmation ไม่ใช้ wick-only break

## Event log

Event ใหม่หลังเปิดโปรแกรมจะถูกเพิ่มใน `logs/structure_events.jsonl` ไม่มีข้อมูลภาพอยู่ใน log โปรแกรมไม่แจ้งเตือนย้อนหลังตอนเริ่มต้น

## ไฟล์หลัก

- `v1_candle_detector.py`: screen capture และ candle extraction
- `market_structure.py`: V2-V5 pure calculation engine
- `marker_manager.py`: marker lifecycle และ manual deletion
- `structure_notifications.py`: event deduplication, JSONL log และเสียงแจ้งเตือน
- `trading_monitor.py`: V1-V6 real-time application

