from captures import CaptureStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_two_quick_captures_do_not_overwrite_each_other():
    store = CaptureStore(ttl=60)
    a = store.put(b"first")
    b = store.put(b"second")
    assert a != b
    assert store.get(a) == b"first"
    assert store.get(b) == b"second"


def test_expired_capture_is_gone():
    clock = Clock()
    store = CaptureStore(ttl=60, clock=clock)
    cid = store.put(b"img")
    clock.t += 61
    assert store.get(cid) is None


def test_store_keeps_only_newest_items():
    store = CaptureStore(ttl=60, max_items=3)
    ids = [store.put(bytes([i])) for i in range(5)]
    assert store.get(ids[0]) is None
    assert store.get(ids[1]) is None
    assert store.get(ids[4]) == bytes([4])


def test_pop_removes_capture():
    store = CaptureStore(ttl=60)
    cid = store.put(b"x")
    assert store.pop(cid) == b"x"
    assert store.get(cid) is None


def test_unknown_or_weird_ids_return_none():
    store = CaptureStore(ttl=60)
    for bad in ["", "../../etc/passwd", None, "nope"]:
        assert store.get(bad) is None
