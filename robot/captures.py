"""Frames frozen by the capture button, waiting for the operator to pick type/room/value.

Replaces the single `_last_read` slot, which a second quick capture overwrote.
"""

import threading
import time
import uuid
from collections import OrderedDict


class CaptureStore:
    def __init__(self, ttl: float = 600, max_items: int = 20, clock=time.monotonic):
        self._ttl = ttl
        self._max = max_items
        self._clock = clock
        self._items = OrderedDict()  # id -> (created, bytes)
        self._lock = threading.Lock()

    def _purge(self):
        now = self._clock()
        for key in [k for k, (t, _) in self._items.items() if now - t > self._ttl]:
            del self._items[key]
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def put(self, jpeg: bytes) -> str:
        cid = uuid.uuid4().hex
        with self._lock:
            self._items[cid] = (self._clock(), jpeg)
            self._purge()
        return cid

    def get(self, cid):
        if not isinstance(cid, str):
            return None
        with self._lock:
            self._purge()
            entry = self._items.get(cid)
            return entry[1] if entry else None

    def pop(self, cid):
        if not isinstance(cid, str):
            return None
        with self._lock:
            self._purge()
            entry = self._items.pop(cid, None)
            return entry[1] if entry else None
