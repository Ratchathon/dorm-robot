"""Fill an EMPTY database with demo rooms, rates and meter photos so the pages have something to show.

    python seed_demo.py

Uses the same DATABASE_URL as the server (default: ./data/dorm.db). Photos are stored in the database.
Never run this against the real dorm database.
"""

import io
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db import Rate, Reading, ReadingImage, Room, make_session_factory, to_db
from app.main import normalize_database_url

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/dorm.db")

ROOMS = ["101", "102", "103", "201", "202", "203"]
# room: (water Aug, water Sep, elec Aug, elec Sep)   None = not read yet
READINGS = {
    "101": ("0834", "0851", "4480", "4521"),
    "102": ("1207", "1229", "3312", None),
    "103": ("0561", "0570", "5120", "5098"),   # lower than last month -> "needs review" demo
    "201": ("0978", "0990", "2764", "2830"),
    "202": ("1455", None, "4091", None),
    "203": ("0302", None, "1876", None),
}
AUG = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
SEP = datetime(2026, 9, 30, 7, 30, tzinfo=timezone.utc)


def meter_jpeg(value: str, kind: str) -> bytes:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        sys.exit("ต้องติดตั้ง Pillow ก่อน:  pip install pillow")
    img = Image.new("RGB", (640, 480), (26, 24, 22))
    d = ImageDraw.Draw(img)
    if kind == "water":
        d.ellipse((220, 140, 420, 340), fill=(189, 183, 172), outline=(150, 144, 133), width=8)
    else:
        d.rounded_rectangle((225, 145, 415, 335), radius=14, fill=(189, 183, 172))
    d.rectangle((250, 215, 390, 265), fill=(239, 230, 204))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
    except OSError:
        font = ImageFont.load_default()
    d.text((320, 240), value, fill=(31, 27, 24), font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def main():
    if DATABASE_URL.startswith("sqlite:///"):
        Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    Session = make_session_factory(normalize_database_url(DATABASE_URL))
    with Session() as s:
        if s.scalar(select(Room.id).limit(1)):
            sys.exit("ฐานข้อมูลมีข้อมูลอยู่แล้ว ไม่ใส่ข้อมูลตัวอย่างซ้ำ (ลบโฟลเดอร์ data แล้วรันใหม่ถ้าต้องการเริ่มใหม่)")
        rooms = {n: Room(number=n, token=secrets.token_urlsafe(18)) for n in ROOMS}
        s.add_all(rooms.values())
        s.add_all([Rate(meter_type="water", price="18"), Rate(meter_type="elec", price="7")])
        s.flush()
        for number, (w_aug, w_sep, e_aug, e_sep) in READINGS.items():
            for kind, value, ts in (("water", w_aug, AUG), ("water", w_sep, SEP), ("elec", e_aug, AUG), ("elec", e_sep, SEP)):
                if value is None:
                    continue
                reading = Reading(uuid=secrets.token_hex(16), room_id=rooms[number].id, meter_type=kind, value=value,
                                  captured_at=to_db(ts), image_file="db", source="robot")
                s.add(reading)
                s.flush()
                s.add(ReadingImage(reading_id=reading.id, data=meter_jpeg(value, kind)))
        s.commit()
        print("ใส่ข้อมูลตัวอย่างแล้ว · ลิงก์หน้าลูกบ้าน:")
        for n, r in rooms.items():
            print(f"  ห้อง {n}: {os.environ.get('PUBLIC_URL', 'http://localhost:8000').rstrip('/')}/r/{r.token}")


if __name__ == "__main__":
    main()
