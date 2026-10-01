"""HTTP side of the robot: cockpit page, MJPEG stream, capture -> reading flow."""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, request, send_from_directory

from outbox import METER_TYPES, validate_reading

STATIC = Path(__file__).parent / "static"
LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def _this_month(iso_ts: str) -> bool:
    ts = datetime.fromisoformat(iso_ts).astimezone(LOCAL_TZ)
    now = datetime.now(LOCAL_TZ)
    return (ts.year, ts.month) == (now.year, now.month)


MAX_CLOCK_SKEW_S = 600


def trusted_capture_time(client_time):
    """Pi clock unless it disagrees with the browser by >10 min (no RTC battery / no NTP offline)."""
    now = datetime.now(timezone.utc)
    if not isinstance(client_time, str):
        return None
    try:
        browser = datetime.fromisoformat(client_time)
    except ValueError:
        return None
    if browser.tzinfo is None:
        return None
    browser = browser.astimezone(timezone.utc)
    return browser.isoformat() if abs((browser - now).total_seconds()) > MAX_CLOCK_SKEW_S else None


def create_app(*, grabber, captures, outbox, rooms, encode_jpeg, stream_quality=80, capture_quality=92,
               ws_port=8765, tilt_floor=35, tilt_wall=110, cloud_url=""):
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "cockpit.html")

    @app.get("/api/config")
    def config():
        return jsonify(ws_port=ws_port, tilt_floor=tilt_floor, tilt_wall=tilt_wall, cloud_url=cloud_url)

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name)

    @app.get("/video_feed")
    def video_feed():
        def frames():
            seq = 0
            while True:
                frame, seq = grabber.wait_for_new(seq, timeout=2)
                if frame is None:
                    continue
                jpg = encode_jpeg(frame, stream_quality)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.post("/api/capture")
    def capture():
        frame, _ = grabber.latest()
        if frame is None:
            return jsonify(error="กล้องยังไม่พร้อม"), 503
        return jsonify(capture_id=captures.put(encode_jpeg(frame, capture_quality))), 201

    @app.get("/api/capture/<cid>.jpg")
    def capture_image(cid):
        jpg = captures.get(cid)
        if jpg is None:
            return jsonify(error="ไม่พบภาพ"), 404
        return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/api/readings")
    def save_reading():
        body = request.get_json(silent=True)
        clean, err = validate_reading(body, set(rooms.room_numbers()))
        if err:
            return jsonify(error=err), 422
        jpg = captures.pop(body.get("capture_id"))
        if jpg is None:
            return jsonify(error="ภาพหมดอายุหรือบันทึกไปแล้ว กรุณาถ่ายใหม่"), 410
        captured_at = trusted_capture_time(body.get("client_time"))
        if captured_at:
            print(f"[Clock] Pi clock differs from browser by >10 min, using browser time {captured_at}")
        item = outbox.enqueue(jpg, {**clean, "captured_at": captured_at})
        return jsonify(uuid=item["uuid"], captured_at=item["captured_at"]), 201

    @app.get("/api/rooms")
    def list_rooms():
        local = outbox.latest_values()
        out = []
        for number in rooms.room_numbers():
            prev = {t: rooms.previous(number, t, local) for t in METER_TYPES}
            done = {t: bool(prev[t]) and _this_month(prev[t]["captured_at"]) for t in METER_TYPES}
            out.append({"number": number, "prev": prev, "done": done})
        return jsonify(rooms=out)

    @app.get("/api/status")
    def status():
        return jsonify(pending=outbox.pending_count(), recent=outbox.recent(8))

    return app
