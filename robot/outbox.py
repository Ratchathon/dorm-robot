"""Store-and-forward queue: readings are saved on the Pi first, then uploaded to the cloud.

The competition hall has no internet (phone hotspot only), so nothing may be lost
while offline. Each reading carries a UUID; the cloud treats a repeated UUID as
"already have it", so retries can never create duplicates.
"""

import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

METER_TYPES = ("water", "elec")
VALUE_RE = re.compile(r"^[0-9]{1,8}$")
MAX_BACKOFF = 60


class TransportResult:
    OK = ("ok", None)
    DUPLICATE = ("duplicate", None)

    @staticmethod
    def rejected(reason: str):
        return ("rejected", reason)


def validate_reading(payload, known_rooms):
    """Return (clean_dict, None) or (None, error message naming the bad field)."""
    if not isinstance(payload, dict):
        return None, "body must be an object"
    room = payload.get("room")
    if not isinstance(room, str) or room not in known_rooms:
        return None, "room: unknown room"
    meter_type = payload.get("meter_type")
    if meter_type not in METER_TYPES:
        return None, "meter_type: must be water or elec"
    value = payload.get("value")
    if not isinstance(value, str) or not VALUE_RE.match(value):
        return None, "value: digits only (1-8)"
    return {"room": room, "meter_type": meter_type, "value": value,
            "rollover": payload.get("rollover") is True}, None


class Outbox:
    def __init__(self, directory, transport, clock=time.time):
        self.dir = Path(directory)
        self.images = self.dir / "images"
        self.images.mkdir(parents=True, exist_ok=True)
        self.transport = transport
        self.clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.dir / "outbox.sqlite3", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                uuid TEXT PRIMARY KEY,
                room TEXT NOT NULL,
                meter_type TEXT NOT NULL,
                value TEXT NOT NULL,
                rollover INTEGER NOT NULL DEFAULT 0,
                captured_at TEXT NOT NULL,
                created REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_try REAL NOT NULL DEFAULT 0,
                error TEXT
            )""")
        self._db.commit()

    def _image_path(self, item_uuid: str) -> Path:
        return self.images / f"{item_uuid}.jpg"

    def enqueue(self, jpeg: bytes, meta: dict) -> dict:
        item = {
            "uuid": uuid.uuid4().hex,
            "room": meta["room"],
            "meter_type": meta["meter_type"],
            "value": meta["value"],
            "rollover": bool(meta.get("rollover")),
            "captured_at": meta.get("captured_at") or datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
        }
        self._image_path(item["uuid"]).write_bytes(jpeg)
        with self._lock:
            self._db.execute(
                "INSERT INTO items (uuid, room, meter_type, value, rollover, captured_at, created) "
                "VALUES (?,?,?,?,?,?,?)",
                (item["uuid"], item["room"], item["meter_type"], item["value"],
                 int(item["rollover"]), item["captured_at"], self.clock()))
            self._db.commit()
        return item

    def pending_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM items WHERE status='pending'").fetchone()[0]

    def recent(self, limit: int = 10):
        with self._lock:
            rows = self._db.execute(
                "SELECT uuid, room, meter_type, value, captured_at, status, error FROM items "
                "ORDER BY created DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def latest_values(self):
        """Newest locally recorded value per (room, meter_type), rejected items excluded."""
        with self._lock:
            rows = self._db.execute(
                "SELECT room, meter_type, value, captured_at FROM items WHERE status != 'rejected' "
                "ORDER BY created ASC, rowid ASC").fetchall()
        return {(r["room"], r["meter_type"]): {"value": r["value"], "captured_at": r["captured_at"]} for r in rows}

    def image(self, item_uuid: str):
        path = self._image_path(item_uuid)
        return path.read_bytes() if re.fullmatch(r"[0-9a-f]{32}", item_uuid or "") and path.exists() else None

    def process_once(self) -> int:
        """Try every due pending item once. Returns how many were delivered."""
        now = self.clock()
        with self._lock:
            due = [dict(r) for r in self._db.execute(
                "SELECT * FROM items WHERE status='pending' AND next_try <= ? ORDER BY created", (now,))]
        delivered = 0
        for item in due:
            item["rollover"] = bool(item["rollover"])
            try:
                status, reason = self.transport.send(item, self._image_path(item["uuid"]).read_bytes())
            except Exception as exc:  # offline, timeout, DNS... -> retry later
                attempts = item["attempts"] + 1
                self._update(item["uuid"], attempts=attempts, error=str(exc)[:200],
                             next_try=self.clock() + min(MAX_BACKOFF, 2 ** attempts))
                continue
            if status in ("ok", "duplicate"):
                self._update(item["uuid"], status="sent", error=None)
                delivered += 1
            else:
                self._update(item["uuid"], status="rejected", error=(reason or "rejected")[:200])
        return delivered

    def _update(self, item_uuid, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE items SET {cols} WHERE uuid=?", (*fields.values(), item_uuid))
            self._db.commit()

    def run_forever(self, period: float = 3.0, stop_event=None):
        stop_event = stop_event or threading.Event()
        while not stop_event.is_set():
            try:
                self.process_once()
            except Exception as exc:
                print(f"[Outbox] unexpected error: {exc}")
            stop_event.wait(period)
