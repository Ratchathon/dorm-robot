import pytest

from outbox import Outbox, TransportResult, validate_reading


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class FakeTransport:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def send(self, item, image_bytes):
        self.calls.append((item["uuid"], image_bytes))
        r = self.results.pop(0) if self.results else TransportResult.OK
        if isinstance(r, Exception):
            raise r
        return r


META = {"room": "102", "meter_type": "elec", "value": "3398", "rollover": False}


@pytest.fixture
def clock():
    return Clock()


def make(tmp_path, clock, results=()):
    t = FakeTransport(results)
    return Outbox(tmp_path, t, clock=clock), t


def test_enqueue_saves_image_and_is_pending(tmp_path, clock):
    box, _ = make(tmp_path, clock)
    item = box.enqueue(b"jpeg-bytes", META)
    assert box.pending_count() == 1
    assert (tmp_path / "images" / f"{item['uuid']}.jpg").read_bytes() == b"jpeg-bytes"
    assert item["captured_at"]


def test_successful_send_marks_sent(tmp_path, clock):
    box, t = make(tmp_path, clock, [TransportResult.OK])
    item = box.enqueue(b"img", META)
    box.process_once()
    assert box.pending_count() == 0
    assert t.calls == [(item["uuid"], b"img")]
    assert box.recent(1)[0]["status"] == "sent"


def test_duplicate_counts_as_sent(tmp_path, clock):
    box, _ = make(tmp_path, clock, [TransportResult.DUPLICATE])
    box.enqueue(b"img", META)
    box.process_once()
    assert box.pending_count() == 0


def test_network_error_retries_later_with_same_uuid(tmp_path, clock):
    box, t = make(tmp_path, clock, [ConnectionError("no internet"), ConnectionError("still"), TransportResult.OK])
    item = box.enqueue(b"img", META)
    box.process_once()
    assert box.pending_count() == 1
    box.process_once()  # not due yet -> no new call
    assert len(t.calls) == 1
    clock.t += 5
    box.process_once()
    clock.t += 10
    box.process_once()
    assert box.pending_count() == 0
    assert {uuid for uuid, _ in t.calls} == {item["uuid"]}


def test_backoff_is_capped(tmp_path, clock):
    box, t = make(tmp_path, clock, [ConnectionError()] * 20)
    box.enqueue(b"img", META)
    for _ in range(20):
        box.process_once()
        clock.t += 61
    assert len(t.calls) == 20  # never waits more than 60 s


def test_rejected_item_stops_retrying_and_shows_error(tmp_path, clock):
    box, t = make(tmp_path, clock, [TransportResult.rejected("unknown room")])
    box.enqueue(b"img", META)
    box.process_once()
    clock.t += 1000
    box.process_once()
    assert len(t.calls) == 1
    row = box.recent(1)[0]
    assert row["status"] == "rejected" and "unknown room" in row["error"]
    assert box.pending_count() == 0


def test_items_survive_restart(tmp_path, clock):
    box, _ = make(tmp_path, clock, [ConnectionError()])
    box.enqueue(b"img", META)
    box.process_once()
    box2, t2 = make(tmp_path, clock, [TransportResult.OK])
    clock.t += 100
    box2.process_once()
    assert box2.pending_count() == 0 and len(t2.calls) == 1


def test_latest_local_value_per_room_and_type(tmp_path, clock):
    box, _ = make(tmp_path, clock)
    box.enqueue(b"a", {**META, "value": "3390"})
    clock.t += 10
    box.enqueue(b"b", {**META, "value": "3398"})
    box.enqueue(b"c", {**META, "meter_type": "water", "value": "1229"})
    latest = box.latest_values()
    assert latest[("102", "elec")]["value"] == "3398"
    assert latest[("102", "water")]["value"] == "1229"


# ---------- validate_reading ----------

ROOMS = {"101", "102"}


@pytest.mark.parametrize("payload, error", [
    ({"room": "102", "meter_type": "elec", "value": "3398"}, None),
    ({"room": "102", "meter_type": "gas", "value": "3398"}, "meter_type"),
    ({"room": "999", "meter_type": "elec", "value": "3398"}, "room"),
    ({"room": "102", "meter_type": "elec", "value": ""}, "value"),
    ({"room": "102", "meter_type": "elec", "value": "12a4"}, "value"),
    ({"room": "102", "meter_type": "elec", "value": "-123"}, "value"),
    ({"room": "102", "meter_type": "elec", "value": "123456789"}, "value"),
    ({"room": "102", "meter_type": "elec", "value": 3398}, "value"),
    ({"room": ["102"], "meter_type": "elec", "value": "3398"}, "room"),
])
def test_validate_reading(payload, error):
    clean, err = validate_reading(payload, ROOMS)
    if error is None:
        assert err is None and clean["value"] == "3398" and clean["rollover"] is False
    else:
        assert clean is None and error in err


def test_validate_rollover_flag_must_be_true_bool():
    clean, _ = validate_reading({"room": "101", "meter_type": "water", "value": "0012", "rollover": "yes"}, ROOMS)
    assert clean["rollover"] is False
    clean, _ = validate_reading({"room": "101", "meter_type": "water", "value": "0012", "rollover": True}, ROOMS)
    assert clean["rollover"] is True
