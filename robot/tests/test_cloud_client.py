import json

import pytest

from cloud_client import HttpTransport, RoomCache
from outbox import TransportResult


class Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if self.exc:
            raise self.exc
        return self.resp

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if self.exc:
            raise self.exc
        return self.resp


ITEM = {"uuid": "a" * 32, "room": "102", "meter_type": "elec", "value": "3398",
        "rollover": False, "captured_at": "2026-09-30T07:30:00+00:00"}


@pytest.mark.parametrize("status, body, expected", [
    (201, {}, TransportResult.OK),
    (200, {"duplicate": True}, TransportResult.DUPLICATE),
    (422, {"detail": "unknown room"}, TransportResult.rejected("unknown room")),
])
def test_transport_maps_status(status, body, expected):
    s = FakeSession(Resp(status, body))
    t = HttpTransport("https://dorm.example", "KEY", session=s)
    assert t.send(ITEM, b"img") == expected
    method, url, kw = s.calls[0]
    assert url == "https://dorm.example/api/device/readings"
    assert kw["headers"]["X-Device-Key"] == "KEY"
    assert kw["data"]["uuid"] == ITEM["uuid"] and kw["data"]["rollover"] == "false"
    assert kw["files"]["image"][1] == b"img"


@pytest.mark.parametrize("status", [500, 502, 401])
def test_server_or_auth_errors_are_retried(status):
    t = HttpTransport("https://dorm.example", "KEY", session=FakeSession(Resp(status)))
    with pytest.raises(ConnectionError):
        t.send(ITEM, b"img")


CLOUD_ROOMS = [
    {"number": "101", "prev": {"water": {"value": "0834", "captured_at": "2026-09-01T03:00:00+00:00"}, "elec": None}},
    {"number": "102", "prev": {"water": None, "elec": {"value": "3312", "captured_at": "2026-09-01T03:00:00+00:00"}}},
]


def test_cache_refresh_saves_and_survives_offline(tmp_path):
    ok = RoomCache(tmp_path / "rooms.json", fetch=lambda: CLOUD_ROOMS, fallback_rooms=["X"])
    assert ok.refresh() is True
    offline = RoomCache(tmp_path / "rooms.json", fetch=lambda: (_ for _ in ()).throw(ConnectionError()),
                        fallback_rooms=["X"])
    assert offline.refresh() is False
    assert offline.room_numbers() == ["101", "102"]


def test_cache_uses_fallback_when_never_synced(tmp_path):
    c = RoomCache(tmp_path / "rooms.json", fetch=lambda: None, fallback_rooms=["101", "102", "103"])
    assert c.room_numbers() == ["101", "102", "103"]
    assert c.previous("101", "water", {}) is None


def test_previous_prefers_newer_local_reading(tmp_path):
    c = RoomCache(tmp_path / "rooms.json", fetch=lambda: CLOUD_ROOMS, fallback_rooms=[])
    c.refresh()
    local = {("102", "elec"): {"value": "3398", "captured_at": "2026-09-30T07:30:00+00:00"}}
    assert c.previous("102", "elec", local)["value"] == "3398"
    older_local = {("102", "elec"): {"value": "3000", "captured_at": "2026-08-01T00:00:00+00:00"}}
    assert c.previous("102", "elec", older_local)["value"] == "3312"
    assert c.previous("101", "water", {})["value"] == "0834"


def test_fetch_rooms_calls_device_endpoint():
    s = FakeSession(Resp(200, {"rooms": CLOUD_ROOMS}))
    t = HttpTransport("https://dorm.example/", "KEY", session=s)
    assert t.fetch_rooms() == CLOUD_ROOMS
    assert s.calls[0][1] == "https://dorm.example/api/device/rooms"
