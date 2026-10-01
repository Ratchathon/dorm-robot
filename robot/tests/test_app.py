import pytest

from app import create_app
from captures import CaptureStore
from cloud_client import RoomCache
from outbox import Outbox, TransportResult


class Grabber:
    def __init__(self, frame="F"):
        self.frame = frame

    def latest(self):
        return self.frame, (1 if self.frame else 0)

    def wait_for_new(self, seq, timeout=1):
        return self.latest()


class OkTransport:
    def send(self, item, img):
        return TransportResult.OK


@pytest.fixture
def ctx(tmp_path):
    grabber = Grabber()
    captures = CaptureStore()
    outbox = Outbox(tmp_path / "ob", OkTransport())
    rooms = RoomCache(tmp_path / "rooms.json", fetch=lambda: None, fallback_rooms=["101", "102"])
    app = create_app(grabber=grabber, captures=captures, outbox=outbox, rooms=rooms,
                     encode_jpeg=lambda frame, quality: b"JPEG:" + frame.encode())
    app.testing = True
    return app.test_client(), grabber, outbox


def test_index_serves_cockpit(ctx):
    client, _, _ = ctx
    r = client.get("/")
    assert r.status_code == 200 and "Teleoperated Cleaning Robot" in r.get_data(as_text=True)


def test_config_endpoint(ctx):
    client, _, _ = ctx
    cfg = client.get("/api/config").get_json()
    assert cfg == {"ws_port": 8765, "tilt_floor": 35, "tilt_wall": 110, "cloud_url": ""}


def test_no_wildcard_cors(ctx):
    client, _, _ = ctx
    assert "Access-Control-Allow-Origin" not in client.get("/api/status").headers


def test_capture_then_save_reading(ctx):
    client, _, outbox = ctx
    cap = client.post("/api/capture").get_json()
    img = client.get(f"/api/capture/{cap['capture_id']}.jpg")
    assert img.data == b"JPEG:F" and img.mimetype == "image/jpeg"
    r = client.post("/api/readings", json={"capture_id": cap["capture_id"], "room": "102",
                                           "meter_type": "elec", "value": "3398"})
    assert r.status_code == 201
    assert outbox.pending_count() == 1
    assert outbox.image(r.get_json()["uuid"]) == b"JPEG:F"
    # the same capture cannot be saved twice
    again = client.post("/api/readings", json={"capture_id": cap["capture_id"], "room": "102",
                                               "meter_type": "elec", "value": "3398"})
    assert again.status_code == 410


def save(client, **extra):
    cid = client.post("/api/capture").get_json()["capture_id"]
    return client.post("/api/readings", json={"capture_id": cid, "room": "101", "meter_type": "water",
                                              "value": "0851", **extra}).get_json()


def test_pi_clock_used_when_close_to_browser_clock(ctx):
    from datetime import datetime, timezone, timedelta
    client, _, _ = ctx
    near = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    r = save(client, client_time=near)
    assert abs(datetime.fromisoformat(r["captured_at"]) - datetime.now(timezone.utc)) < timedelta(seconds=5)


def test_browser_clock_wins_when_pi_clock_is_wrong(ctx):
    # Pi without internet/RTC battery can boot with a stale clock -> wrong billing month
    client, _, _ = ctx
    r = save(client, client_time="2030-01-15T10:00:00+07:00")
    assert r["captured_at"].startswith("2030-01-15T03:00:00")


@pytest.mark.parametrize("bad", ["yesterday", "2030-01-15T10:00:00", 12345])
def test_bad_client_time_is_ignored(ctx, bad):
    client, _, _ = ctx
    assert save(client, client_time=bad)["captured_at"].startswith(str(__import__("datetime").date.today().year))


def test_capture_without_camera_frame_is_503(ctx):
    client, grabber, _ = ctx
    grabber.frame = None
    assert client.post("/api/capture").status_code == 503


@pytest.mark.parametrize("body", [
    {"room": "999", "meter_type": "elec", "value": "1"},
    {"room": "101", "meter_type": "gas", "value": "1"},
    {"room": "101", "meter_type": "elec", "value": "12a"},
])
def test_invalid_reading_rejected_and_capture_kept(ctx, body):
    client, _, outbox = ctx
    cid = client.post("/api/capture").get_json()["capture_id"]
    r = client.post("/api/readings", json={**body, "capture_id": cid})
    assert r.status_code == 422
    assert outbox.pending_count() == 0
    assert client.get(f"/api/capture/{cid}.jpg").status_code == 200  # can fix and retry


def test_non_json_body_is_422(ctx):
    client, _, _ = ctx
    assert client.post("/api/readings", data="x", content_type="text/plain").status_code == 422


def test_rooms_include_previous_from_local_outbox(ctx):
    client, _, _ = ctx
    cid = client.post("/api/capture").get_json()["capture_id"]
    client.post("/api/readings", json={"capture_id": cid, "room": "101", "meter_type": "water", "value": "0851"})
    rooms = client.get("/api/rooms").get_json()["rooms"]
    r101 = next(r for r in rooms if r["number"] == "101")
    assert r101["prev"]["water"]["value"] == "0851"
    assert r101["prev"]["elec"] is None
    assert r101["done"]["water"] is True


def test_status_reports_pending(ctx):
    client, _, _ = ctx
    cid = client.post("/api/capture").get_json()["capture_id"]
    client.post("/api/readings", json={"capture_id": cid, "room": "101", "meter_type": "water", "value": "0851"})
    s = client.get("/api/status").get_json()
    assert s["pending"] == 1 and s["recent"][0]["room"] == "101"
