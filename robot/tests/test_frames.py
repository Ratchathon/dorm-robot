import threading
import time

from frames import FrameGrabber


class FakeCamera:
    def __init__(self, fail_first=0):
        self.calls = 0
        self.threads = set()
        self.fail_first = fail_first

    def read(self):
        self.calls += 1
        self.threads.add(threading.get_ident())
        time.sleep(0.005)
        if self.calls <= self.fail_first:
            raise RuntimeError("camera hiccup")
        return f"frame-{self.calls}"


def test_all_readers_share_one_capture_thread():
    cam = FakeCamera()
    grabber = FrameGrabber(cam.read)
    grabber.start()
    try:
        results = []

        def reader():
            seq = 0
            for _ in range(5):
                frame, seq = grabber.wait_for_new(seq, timeout=1)
                results.append(frame)

        readers = [threading.Thread(target=reader) for _ in range(4)]
        for t in readers:
            t.start()
        for t in readers:
            t.join()
        assert len(results) == 20
        assert len(cam.threads) == 1  # only the grabber thread touched the camera
    finally:
        grabber.stop()


def test_latest_returns_none_before_first_frame():
    grabber = FrameGrabber(lambda: None)
    assert grabber.latest() == (None, 0)


def test_camera_errors_do_not_kill_the_grabber():
    cam = FakeCamera(fail_first=3)
    grabber = FrameGrabber(cam.read, error_backoff=0.001)
    grabber.start()
    try:
        frame, seq = grabber.wait_for_new(0, timeout=1)
        assert frame is not None and seq >= 1
    finally:
        grabber.stop()


def test_wait_times_out_with_current_frame_when_nothing_new():
    grabber = FrameGrabber(lambda: "x")
    frame, seq = grabber.wait_for_new(0, timeout=0.01)  # never started
    assert (frame, seq) == (None, 0)
