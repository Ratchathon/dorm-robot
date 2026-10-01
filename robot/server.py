"""
Cleaning/meter robot - runs on the Raspberry Pi (or a laptop with ROBOT_FAKE_HARDWARE=1)
======================================================================================
One command starts everything:
    python3 server.py

  http://<pi-ip>:5000/   cockpit page (open this from a laptop on the same hotspot)
  ws://<pi-ip>:8765      drive commands -> ESP32 over USB serial

Settings come from environment variables (or a .env file next to this script):
  SERIAL_PORT          /dev/ttyACM0
  CLOUD_URL            https://your-dorm-app.example   (empty = keep everything on the Pi for now)
  DEVICE_KEY           secret that matches DEVICE_KEY on the cloud
  ROOMS                101,102,103   used only until the first successful sync with the cloud
  TILT_FLOOR / TILT_WALL   servo angles for keys 1 / 2 (calibrate on the real robot)
  ROBOT_FAKE_HARDWARE  1 = no serial, synthetic camera (for testing on a laptop)
"""

import asyncio
import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import websockets

from app import create_app
from bridge import RobotBridge
from captures import CaptureStore
from cloud_client import HttpTransport, RoomCache
from frames import FrameGrabber
from outbox import Outbox

HERE = Path(__file__).parent


def load_env_file():
    env = HERE / ".env"
    if env.exists():
        for line in env.read_text("utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


load_env_file()
FAKE = os.environ.get("ROBOT_FAKE_HARDWARE") == "1"
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUDRATE = 115200
HTTP_PORT = int(os.environ.get("HTTP_PORT", "5000"))
WS_PORT = int(os.environ.get("WS_PORT", "8765"))
CLOUD_URL = os.environ.get("CLOUD_URL", "").rstrip("/")
DEVICE_KEY = os.environ.get("DEVICE_KEY", "")
ROOMS = [r.strip() for r in os.environ.get("ROOMS", "101,102,103").split(",") if r.strip()]
TILT_FLOOR = int(os.environ.get("TILT_FLOOR", "35"))
TILT_WALL = int(os.environ.get("TILT_WALL", "110"))
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE / "data"))
FRAME_SIZE = (640, 480)


# ---------------- serial (ESP32) ----------------
class SerialBridge:
    """pyserial wrapper that survives unplugged cables without crashing the server."""

    def __init__(self, port, baudrate):
        import serial
        self._serial_mod = serial
        self._port, self._baud = port, baudrate
        self._ser = None
        self._lock = threading.Lock()
        self._connect()
        threading.Thread(target=self._read_forever, daemon=True).start()

    def _connect(self):
        try:
            self._ser = self._serial_mod.Serial(self._port, self._baud, timeout=0.1)
            print(f"[Serial] connected {self._port} @ {self._baud}")
        except self._serial_mod.SerialException as exc:
            self._ser = None
            print(f"[Serial] not connected ({exc}) - will retry on next command")

    def send_json(self, payload):
        with self._lock:
            if self._ser is None or not self._ser.is_open:
                self._connect()
                if self._ser is None:
                    return
            try:
                self._ser.write((json.dumps(payload) + "\n").encode("utf-8"))
            except self._serial_mod.SerialException as exc:
                print(f"[Serial] write failed: {exc}")
                self._ser = None

    def _read_forever(self):
        last = None
        while True:
            ser = self._ser
            if ser is None or not ser.is_open:
                time.sleep(0.5)
                continue
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                time.sleep(0.5)
                continue
            if line and line != last:  # identical acks are not reprinted
                print(f"[ESP32] {line}")
                last = line


class PrintSerial:
    def __init__(self):
        self._last = None

    def send_json(self, payload):
        if payload != self._last:
            print(f"[FakeSerial] {payload}")
            self._last = payload


# ---------------- camera ----------------
def open_camera():
    if FAKE:
        return fake_camera()
    from libcamera import Transform
    from picamera2 import Picamera2
    cam = Picamera2()
    cam.configure(cam.create_video_configuration(
        main={"size": FRAME_SIZE, "format": "RGB888"},  # RGB888 in picamera2 = BGR order for OpenCV
        transform=Transform(hflip=True, vflip=True),     # camera is mounted upside down
    ))
    cam.start()
    try:
        from libcamera import controls
        cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
    except Exception as exc:
        print(f"[Camera] autofocus not enabled ({exc})")
    return cam.capture_array


def fake_camera():
    """Synthetic wall meter so the whole flow can be tried on a laptop."""
    start = time.time()

    def read():
        time.sleep(1 / 20)
        img = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), (22, 24, 26), np.uint8)
        x = int(20 * np.sin(time.time() - start))
        cv2.rectangle(img, (225 + x, 145), (415 + x, 335), (172, 183, 189), -1)
        cv2.rectangle(img, (250 + x, 215), (390 + x, 265), (204, 230, 239), -1)
        cv2.putText(img, "3398", (258 + x, 255), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (24, 27, 31), 3)
        cv2.putText(img, "kWh", (298 + x, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (61, 66, 74), 1)
        return img

    return read


def encode_jpeg(frame, quality):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


# ---------------- cloud ----------------
class OfflineTransport:
    """Used when CLOUD_URL is not configured: readings stay queued on the Pi."""

    def send(self, item, image_bytes):
        raise ConnectionError("CLOUD_URL not configured")

    def fetch_rooms(self):
        raise ConnectionError("CLOUD_URL not configured")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    transport = HttpTransport(CLOUD_URL, DEVICE_KEY) if CLOUD_URL and DEVICE_KEY else OfflineTransport()
    outbox = Outbox(DATA_DIR / "outbox", transport)
    rooms = RoomCache(DATA_DIR / "rooms.json", fetch=transport.fetch_rooms, fallback_rooms=ROOMS)

    def sync_loop():
        while True:
            rooms.refresh()
            outbox.process_once()
            time.sleep(5)

    threading.Thread(target=sync_loop, name="cloud-sync", daemon=True).start()

    grabber = FrameGrabber(open_camera())
    grabber.start()
    app = create_app(grabber=grabber, captures=CaptureStore(), outbox=outbox, rooms=rooms,
                     encode_jpeg=encode_jpeg, ws_port=WS_PORT, tilt_floor=TILT_FLOOR,
                     tilt_wall=TILT_WALL, cloud_url=CLOUD_URL)
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, use_reloader=False),
                     daemon=True).start()

    serial = PrintSerial() if FAKE else SerialBridge(SERIAL_PORT, SERIAL_BAUDRATE)
    bridge = RobotBridge(serial)

    async def ws_main():
        # ping every 2 s: a vanished laptop frees the controller lock within ~4 s
        async with websockets.serve(bridge.handle, "0.0.0.0", WS_PORT, ping_interval=2, ping_timeout=2):
            print(f"[Robot] cockpit: http://<this-ip>:{HTTP_PORT}/   (fake hardware: {FAKE})")
            await asyncio.Future()

    asyncio.run(ws_main())


if __name__ == "__main__":
    main()
