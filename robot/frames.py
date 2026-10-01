"""One background thread owns the camera; every stream/capture reads its latest frame.

Before: each /video_feed viewer and /read_meter called camera.capture_array() itself,
so FPS dropped with every extra viewer.
"""

import threading
import time


class FrameGrabber:
    def __init__(self, read_frame, error_backoff: float = 0.2):
        self._read = read_frame
        self._error_backoff = error_backoff
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="frame-grabber", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def _loop(self):
        while self._running:
            try:
                frame = self._read()
            except Exception as exc:  # a flaky frame must not kill the stream
                print(f"[Camera] read failed: {exc}")
                time.sleep(self._error_backoff)
                continue
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()

    def latest(self):
        with self._cond:
            return self._frame, self._seq

    def wait_for_new(self, after_seq: int, timeout: float = 1.0):
        """Block until a frame newer than after_seq exists (or timeout); return (frame, seq)."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after_seq, timeout=timeout)
            return self._frame, self._seq
