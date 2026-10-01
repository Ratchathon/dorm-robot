"""Talks to the dorm cloud with the robot's device key (can only add readings / list rooms)."""

import json
from pathlib import Path

from outbox import TransportResult

TIMEOUT = (5, 20)  # connect, read seconds


class HttpTransport:
    def __init__(self, base_url: str, device_key: str, session=None):
        if session is None:
            import requests
            session = requests.Session()
        self.base = base_url.rstrip("/")
        self.key = device_key
        self.session = session

    def _headers(self):
        return {"X-Device-Key": self.key}

    def send(self, item, image_bytes):
        data = {k: item[k] for k in ("uuid", "room", "meter_type", "value", "captured_at")}
        data["rollover"] = "true" if item.get("rollover") else "false"
        resp = self.session.post(
            f"{self.base}/api/device/readings", headers=self._headers(), data=data,
            files={"image": (f"{item['uuid']}.jpg", image_bytes, "image/jpeg")}, timeout=TIMEOUT)
        if resp.status_code == 201:
            return TransportResult.OK
        if resp.status_code == 200 and _json(resp).get("duplicate"):
            return TransportResult.DUPLICATE
        if resp.status_code in (400, 404, 409, 413, 422):
            detail = _json(resp).get("detail", f"HTTP {resp.status_code}")
            return TransportResult.rejected(detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False))
        # 401/403 = wrong key, 5xx = server trouble: keep the item and retry
        raise ConnectionError(f"cloud answered HTTP {resp.status_code}")

    def fetch_rooms(self):
        resp = self.session.get(f"{self.base}/api/device/rooms", headers=self._headers(), timeout=TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"cloud answered HTTP {resp.status_code}")
        return resp.json()["rooms"]


def _json(resp):
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


class RoomCache:
    """Room list + last cloud reading per meter, kept on disk for offline use."""

    def __init__(self, path, fetch, fallback_rooms):
        self.path = Path(path)
        self.fetch = fetch
        self.fallback = list(fallback_rooms)
        self._rooms = None
        if self.path.exists():
            try:
                self._rooms = json.loads(self.path.read_text("utf-8"))
            except (ValueError, OSError):
                self._rooms = None

    def refresh(self) -> bool:
        try:
            rooms = self.fetch()
        except Exception:
            return False
        if not isinstance(rooms, list):
            return False
        self._rooms = rooms
        self.path.write_text(json.dumps(rooms, ensure_ascii=False), "utf-8")
        return True

    def room_numbers(self):
        if self._rooms:
            return [r["number"] for r in self._rooms]
        return list(self.fallback)

    def previous(self, room, meter_type, local_latest):
        cloud = None
        for r in self._rooms or []:
            if r["number"] == room:
                cloud = (r.get("prev") or {}).get(meter_type)
        local = local_latest.get((room, meter_type))
        candidates = [c for c in (cloud, local) if c]
        return max(candidates, key=lambda c: c["captured_at"]) if candidates else None
