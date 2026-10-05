"""Dorm meter cloud app: admin console, tenant room links, public calculator, robot upload API.

Access model (kept simple on purpose, per the brief: no user accounts):
  * admin   - one password (ADMIN_PASSWORD) -> signed, HttpOnly session cookie
  * tenant  - a secret link per room (/r/<token>), shown as a QR code; regenerate to revoke
  * robot   - X-Device-Key header; may only list rooms and add readings
"""

import hmac
import io
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from app import billing
from app.db import (Dispute, Rate, Reading, ReadingEdit, ReadingImage, Room, from_db, make_session_factory,
                    to_db, utcnow)

STATIC = Path(__file__).parent / "static"
METER_TYPES = ("water", "elec")
UUID_RE = re.compile(r"^[0-9a-f]{32}$")
VALUE_RE = re.compile(r"^[0-9]{1,8}$")
ROOM_RE = re.compile(r"^[0-9A-Za-z฀-๿/-]{1,10}$")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
LOGIN_MAX_FAILS, LOGIN_WINDOW = 5, 600


def normalize_database_url(url: str) -> str:
    """Neon/Render give postgres:// URLs; SQLAlchemy needs the psycopg (v3) driver named explicitly."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass
class Settings:
    database_url: str
    upload_dir: str
    admin_password: str
    secret_key: str
    device_key: str
    dorm_name: str = "หอพัก"
    secure_cookies: bool = True
    public_url: str = ""  # e.g. https://mydorm.onrender.com - used for tenant links and QR codes

    @classmethod
    def from_env(cls):
        missing = [k for k in ("ADMIN_PASSWORD", "SECRET_KEY", "DEVICE_KEY") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"missing environment variables: {', '.join(missing)}")
        return cls(
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/dorm.db"),
            upload_dir=os.environ.get("UPLOAD_DIR", "./data/uploads"),
            admin_password=os.environ["ADMIN_PASSWORD"],
            secret_key=os.environ["SECRET_KEY"],
            device_key=os.environ["DEVICE_KEY"],
            dorm_name=os.environ.get("DORM_NAME", "หอพัก"),
            secure_cookies=os.environ.get("SECURE_COOKIES", "1") != "0",
            public_url=os.environ.get("PUBLIC_URL", ""),
        )


def create_app(settings: Settings) -> FastAPI:
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    SessionLocal = make_session_factory(normalize_database_url(settings.database_url))
    uploads = Path(settings.upload_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    login_fails: dict[str, list[float]] = defaultdict(list)

    app = FastAPI(title="Dorm meters", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="dorm_admin",
                       max_age=7 * 24 * 3600, same_site="lax", https_only=settings.secure_cookies)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; script-src 'self'; "
                                "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                                "frame-ancestors 'none'")
        return resp

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    # ---------------- helpers ----------------
    def fail(status, detail):
        raise HTTPException(status, detail)

    def require_admin(request: Request):
        if request.session.get("admin") is not True:
            fail(401, "login required")

    def require_device(request: Request):
        key = request.headers.get("X-Device-Key", "")
        if not hmac.compare_digest(key.encode(), settings.device_key.encode()):
            fail(401, "bad device key")

    def parse_ts(text, field="captured_at"):
        try:
            ts = datetime.fromisoformat(str(text))
        except ValueError:
            fail(422, f"{field}: must be ISO 8601 time")
        if ts.tzinfo is None:
            fail(422, f"{field}: time zone required")
        return ts

    def check_value(value):
        if not isinstance(value, str) or not VALUE_RE.match(value):
            fail(422, "value: digits only (1-8)")
        return value

    def check_type(meter_type):
        if meter_type not in METER_TYPES:
            fail(422, "meter_type: must be water or elec")
        return meter_type

    def room_by_number(s, number, active_only=True):
        q = select(Room).where(Room.number == str(number))
        if active_only:
            q = q.where(Room.active.is_(True))
        room = s.scalar(q)
        if room is None:
            fail(422, "room: unknown room")
        return room

    def public_base(request: Request) -> str:
        return (settings.public_url or str(request.base_url)).rstrip("/")

    def room_dict(room: Room, request: Request):
        return {"id": room.id, "number": room.number, "token": room.token, "active": room.active,
                "visible_from": iso(room.visible_from), "link": f"{public_base(request)}/r/{room.token}"}

    def iso(dt):
        return from_db(dt).isoformat() if dt else None

    IMAGE_IN_DB = "db"

    def alive(q):
        return q.where(Reading.deleted_at.is_(None))

    def latest(s, room_id, meter_type, before=None, since=None):
        q = alive(select(Reading)).where(Reading.room_id == room_id, Reading.meter_type == meter_type)
        if before is not None:
            q = q.where(Reading.captured_at < before)
        if since is not None:
            q = q.where(Reading.captured_at >= since)
        return s.scalar(q.order_by(Reading.captured_at.desc(), Reading.id.desc()).limit(1))

    def rate_for(s, meter_type, period_end):
        base = select(Rate).where(Rate.meter_type == meter_type)
        rate = s.scalar(base.where(Rate.effective_from < period_end).order_by(Rate.effective_from.desc(), Rate.id.desc()))
        # rates entered after the month ended still apply to it when nothing older exists (first setup)
        rate = rate or s.scalar(base.order_by(Rate.effective_from.asc(), Rate.id.asc()))
        return Decimal(rate.price) if rate else None

    def edited_ids(s, ids):
        if not ids:
            return set()
        return set(s.scalars(select(ReadingEdit.reading_id).where(ReadingEdit.reading_id.in_(ids))))

    def meter_line(s, room, meter_type, start, end, price, hide_prev_before=None):
        curr = latest(s, room.id, meter_type, before=end, since=start)
        prev = latest(s, room.id, meter_type, before=start)
        line = billing.bill_line(
            billing.Reading(prev.value, prev.rollover) if prev else None,
            billing.Reading(curr.value, curr.rollover) if curr else None,
            price)
        out = {"status": line["status"], "units": line["units"],
               "amount": str(line["amount"]) if line["amount"] is not None else None,
               "price": format_decimal(price) if price is not None else None,
               "prev_value": prev.value if prev else None,
               "prev_captured_at": iso(prev.captured_at) if prev else None}
        if curr:
            out.update(id=curr.id, value=curr.value, captured_at=iso(curr.captured_at), rollover=curr.rollover,
                       has_image=bool(curr.image_file), source=curr.source)
        return out, line

    def room_period(s, room, period, for_admin=True):
        start, end = billing.period_bounds(period)
        start, end = to_db(start), to_db(end)
        result = {"number": room.number, "room_id": room.id, "active": room.active}
        amounts = []
        for t in METER_TYPES:
            out, line = meter_line(s, room, t, start, end, rate_for(s, t, end))
            result[t] = out
            amounts.append(line["amount"])
        result["total"] = str(billing.money(sum(amounts))) if all(a is not None for a in amounts) else None
        if for_admin:
            ids = [result[t].get("id") for t in METER_TYPES if result[t].get("id")]
            ed = edited_ids(s, ids)
            for t in METER_TYPES:
                result[t]["edited"] = result[t].get("id") in ed
        return result

    def format_decimal(d: Decimal) -> str:
        return format(d.normalize(), "f")

    def reading_periods(s, room_id=None, since=None):
        q = alive(select(Reading.captured_at))
        if room_id is not None:
            q = q.where(Reading.room_id == room_id)
        if since is not None:
            q = q.where(Reading.captured_at >= since)
        return sorted({billing.period_of(from_db(ts)) for ts in s.scalars(q)}, reverse=True)

    # ---------------- pages ----------------
    def page(name, **headers):
        return FileResponse(STATIC / name, media_type="text/html", headers=headers or None)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """For an uptime pinger: keeps the free web service awake without waking the database."""
        return {"ok": True}

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/admin")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return page("admin.html")

    @app.get("/admin/login", include_in_schema=False)
    def login_page():
        return page("login.html")

    @app.get("/calculator", include_in_schema=False)
    def calculator_page():
        return page("calculator.html")

    @app.get("/r/{token}", include_in_schema=False)
    def tenant_page(token: str):
        return page("tenant.html", **{"Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow",
                                      "Cache-Control": "no-store"})

    # ---------------- admin auth ----------------
    @app.post("/api/admin/login")
    async def login(request: Request):
        ip = request.client.host if request.client else "?"
        now = time.monotonic()
        login_fails[ip] = [t for t in login_fails[ip] if now - t < LOGIN_WINDOW]
        if len(login_fails[ip]) >= LOGIN_MAX_FAILS:
            fail(429, "พยายามหลายครั้งเกินไป ลองใหม่ใน 10 นาที")
        body = await json_body(request)
        password = body.get("password")
        if not isinstance(password, str) or not hmac.compare_digest(password.encode(), settings.admin_password.encode()):
            login_fails[ip].append(now)
            fail(401, "รหัสผ่านไม่ถูกต้อง")
        login_fails.pop(ip, None)
        request.session.clear()
        request.session["admin"] = True
        return {"ok": True}

    @app.post("/api/admin/logout")
    def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/admin/me", dependencies=[Depends(require_admin)])
    def me():
        return {"admin": True, "dorm_name": settings.dorm_name}

    async def json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            fail(422, "body must be JSON")
        if not isinstance(body, dict):
            fail(422, "body must be a JSON object")
        return body

    # ---------------- admin: rooms ----------------
    @app.get("/api/admin/rooms", dependencies=[Depends(require_admin)])
    def list_rooms(request: Request, s=Depends(db)):
        return {"rooms": [room_dict(r, request) for r in s.scalars(select(Room).order_by(Room.number))]}

    @app.post("/api/admin/rooms", status_code=201, dependencies=[Depends(require_admin)])
    async def create_room(request: Request, s=Depends(db)):
        body = await json_body(request)
        number = check_room_number(body.get("number", ""))
        room = Room(number=number, token=secrets.token_urlsafe(18))
        s.add(room)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            fail(409, "มีห้องนี้อยู่แล้ว")
        return room_dict(room, request)

    def check_room_number(value):
        number = value.strip() if isinstance(value, str) else ""
        if not ROOM_RE.match(number):
            fail(422, "number: 1-10 ตัว ใช้ตัวเลข ตัวอักษร - หรือ / เท่านั้น")
        return number

    def get_room(s, room_id):
        room = s.get(Room, room_id)
        if room is None:
            fail(404, "room not found")
        return room

    @app.patch("/api/admin/rooms/{room_id}", dependencies=[Depends(require_admin)])
    async def update_room(room_id: int, request: Request, s=Depends(db)):
        body = await json_body(request)
        room = get_room(s, room_id)
        if "number" in body:
            room.number = check_room_number(body["number"])
        if "active" in body:
            if not isinstance(body["active"], bool):
                fail(422, "active: true/false")
            room.active = body["active"]
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            fail(409, "มีห้องนี้อยู่แล้ว")
        return room_dict(room, request)

    @app.delete("/api/admin/rooms/{room_id}", dependencies=[Depends(require_admin)])
    async def delete_room(room_id: int, request: Request, s=Depends(db)):
        """Permanently removes the room with all its readings, photos, edit history and disputes."""
        body = await json_body(request)
        room = get_room(s, room_id)
        if str(body.get("confirm", "")).strip() != room.number:
            fail(422, "confirm: พิมพ์เลขห้องให้ตรงเพื่อยืนยันการลบ")
        readings = list(s.scalars(select(Reading).where(Reading.room_id == room.id)))
        ids = [r.id for r in readings]
        if ids:
            s.execute(delete(ReadingImage).where(ReadingImage.reading_id.in_(ids)))
            s.execute(delete(ReadingEdit).where(ReadingEdit.reading_id.in_(ids)))
            s.execute(delete(Reading).where(Reading.id.in_(ids)))
        s.execute(delete(Dispute).where(Dispute.room_id == room.id))
        number = room.number
        s.delete(room)
        s.commit()
        for r in readings:  # photos saved on disk by older versions
            if r.image_file and r.image_file != IMAGE_IN_DB:
                (uploads / r.image_file).unlink(missing_ok=True)
        return {"deleted": number}

    @app.post("/api/admin/rooms/{room_id}/new-link", dependencies=[Depends(require_admin)])
    async def new_link(room_id: int, request: Request, s=Depends(db)):
        body = await json_body(request)
        room = get_room(s, room_id)
        room.token = secrets.token_urlsafe(18)
        if body.get("new_tenant") is True:
            room.visible_from = utcnow()
        s.commit()
        return room_dict(room, request)

    @app.get("/api/admin/rooms/{room_id}/qr.svg", dependencies=[Depends(require_admin)])
    def room_qr(room_id: int, request: Request, s=Depends(db)):
        import qrcode
        import qrcode.image.svg
        room = get_room(s, room_id)
        url = f"{public_base(request)}/r/{room.token}"
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    # ---------------- admin: rates ----------------
    def current_rates(s, at=None):
        end = at or utcnow()
        return {t: (format_decimal(p) if (p := rate_for(s, t, end)) is not None else None) for t in METER_TYPES}

    @app.get("/api/admin/rates", dependencies=[Depends(require_admin)])
    def get_rates(s=Depends(db)):
        history = [{"meter_type": r.meter_type, "price": r.price, "effective_from": iso(r.effective_from)}
                   for r in s.scalars(select(Rate).order_by(Rate.effective_from.desc(), Rate.id.desc()))]
        latest_rates = {}
        for h in history:
            latest_rates.setdefault(h["meter_type"], h["price"])
        return {"current": latest_rates or None, "history": history}

    @app.put("/api/admin/rates", dependencies=[Depends(require_admin)])
    async def put_rates(request: Request, s=Depends(db)):
        body = await json_body(request)
        prices = {}
        for t in METER_TYPES:
            try:
                d = Decimal(str(body[t]))
            except (KeyError, InvalidOperation):
                fail(422, f"{t}: ราคาต่อหน่วยต้องเป็นตัวเลข")
            if not d.is_finite() or d < 0 or d > 1000 or d.as_tuple().exponent < -4:
                fail(422, f"{t}: ราคาต้องอยู่ระหว่าง 0-1000 บาท")
            prices[t] = format_decimal(d)
        now = utcnow()
        for t, p in prices.items():
            s.add(Rate(meter_type=t, price=p, effective_from=now))
        s.commit()
        return {"current": prices}

    # ---------------- admin: readings ----------------
    @app.get("/api/admin/periods", dependencies=[Depends(require_admin)])
    def periods(s=Depends(db)):
        return {"periods": reading_periods(s)}

    @app.get("/api/admin/summary", dependencies=[Depends(require_admin)])
    def summary(period: str, s=Depends(db)):
        try:
            _, end = billing.period_bounds(period)
        except ValueError as exc:
            fail(422, str(exc))
        rows = [room_period(s, room, period) for room in s.scalars(select(Room).order_by(Room.number))]
        rows = [r for r in rows if r["active"] or r["water"].get("id") or r["elec"].get("id")]
        counts = {t: sum(1 for r in rows if r[t].get("id")) for t in METER_TYPES}
        counts["review"] = sum(1 for r in rows for t in METER_TYPES if r[t]["status"] == "review")
        counts["rooms"] = len(rows)
        totals = [Decimal(r["total"]) for r in rows if r["total"] is not None]
        return {"period": period, "rooms": rows, "counts": counts,
                "grand_total": str(billing.money(sum(totals))) if totals else "0.00",
                "rates": current_rates(s, to_db(end))}

    def get_reading(s, reading_id):
        reading = s.get(Reading, reading_id)
        if reading is None or reading.deleted_at is not None:
            fail(404, "reading not found")
        return reading

    @app.patch("/api/admin/readings/{reading_id}", dependencies=[Depends(require_admin)])
    async def edit_reading(reading_id: int, request: Request, s=Depends(db)):
        body = await json_body(request)
        reading = get_reading(s, reading_id)
        edit = ReadingEdit(reading_id=reading.id, action="edit", note=str(body.get("note", ""))[:300] or None)
        if "value" in body:
            edit.old_value, edit.new_value = reading.value, check_value(body["value"])
            reading.value = body["value"]
        if "room" in body:
            new_room = room_by_number(s, body["room"], active_only=False)
            edit.old_room, edit.new_room = reading.room.number, new_room.number
            reading.room_id = new_room.id
        if "rollover" in body:
            if not isinstance(body["rollover"], bool):
                fail(422, "rollover: true/false")
            edit.old_rollover, edit.new_rollover = reading.rollover, body["rollover"]
            reading.rollover = body["rollover"]
        s.add(edit)
        s.commit()
        return {"ok": True}

    @app.delete("/api/admin/readings/{reading_id}", dependencies=[Depends(require_admin)])
    def delete_reading(reading_id: int, s=Depends(db)):
        reading = get_reading(s, reading_id)
        reading.deleted_at = utcnow()  # soft delete: file kept for the audit trail
        s.add(ReadingEdit(reading_id=reading.id, action="delete", old_value=reading.value))
        s.commit()
        return {"ok": True}

    @app.get("/api/admin/readings/{reading_id}/image", dependencies=[Depends(require_admin)])
    def admin_image(reading_id: int, s=Depends(db)):
        return image_response(get_reading(s, reading_id), s)

    @app.get("/api/admin/readings/{reading_id}/history", dependencies=[Depends(require_admin)])
    def history(reading_id: int, s=Depends(db)):
        rows = s.scalars(select(ReadingEdit).where(ReadingEdit.reading_id == reading_id)
                         .order_by(ReadingEdit.at.desc(), ReadingEdit.id.desc()))
        return {"history": [{"action": e.action, "old_value": e.old_value, "new_value": e.new_value,
                             "old_room": e.old_room, "new_room": e.new_room, "old_rollover": e.old_rollover,
                             "new_rollover": e.new_rollover, "note": e.note, "at": iso(e.at)} for e in rows]}

    @app.post("/api/admin/readings", status_code=201, dependencies=[Depends(require_admin)])
    async def manual_reading(request: Request, s=Depends(db)):
        body = await json_body(request)
        room = room_by_number(s, body.get("room"))
        ts = parse_ts(body["captured_at"]) if body.get("captured_at") else datetime.now(timezone.utc)
        reading = Reading(uuid=secrets.token_hex(16), room_id=room.id, meter_type=check_type(body.get("meter_type")),
                          value=check_value(body.get("value")), rollover=body.get("rollover") is True,
                          captured_at=to_db(ts), source="admin")
        s.add(reading)
        s.commit()
        return {"id": reading.id}

    def image_response(reading, s):
        headers = {"Cache-Control": "private, max-age=3600"}
        if reading.image_file == IMAGE_IN_DB:
            row = s.get(ReadingImage, reading.id)
            if row is None:
                fail(404, "no image")
            return Response(row.data, media_type="image/jpeg", headers=headers)
        path = uploads / reading.image_file if reading.image_file else None  # photos saved by older versions
        if path is None or not path.exists():
            fail(404, "no image")
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    # ---------------- admin: disputes ----------------
    @app.get("/api/admin/disputes", dependencies=[Depends(require_admin)])
    def list_disputes(s=Depends(db)):
        rows = s.scalars(select(Dispute).order_by(Dispute.created_at.desc(), Dispute.id.desc()))
        return {"disputes": [{"id": d.id, "room": d.room.number, "period": d.period, "message": d.message,
                              "status": d.status, "reply": d.reply, "created_at": iso(d.created_at)} for d in rows]}

    @app.patch("/api/admin/disputes/{dispute_id}", dependencies=[Depends(require_admin)])
    async def update_dispute(dispute_id: int, request: Request, s=Depends(db)):
        body = await json_body(request)
        d = s.get(Dispute, dispute_id)
        if d is None:
            fail(404, "not found")
        if "status" in body:
            if body["status"] not in ("open", "resolved"):
                fail(422, "status: open or resolved")
            d.status = body["status"]
        if "reply" in body:
            reply = str(body["reply"]).strip()
            if len(reply) > 1000:
                fail(422, "reply: ไม่เกิน 1000 ตัวอักษร")
            d.reply = reply or None
        s.commit()
        return {"ok": True}

    # ---------------- device (robot) ----------------
    @app.get("/api/device/rooms", dependencies=[Depends(require_device)])
    def device_rooms(s=Depends(db)):
        out = []
        for room in s.scalars(select(Room).where(Room.active.is_(True)).order_by(Room.number)):
            prev = {}
            for t in METER_TYPES:
                r = latest(s, room.id, t)
                prev[t] = {"value": r.value, "captured_at": iso(r.captured_at)} if r else None
            out.append({"number": room.number, "prev": prev})
        return {"rooms": out}

    @app.post("/api/device/readings", dependencies=[Depends(require_device)])
    async def device_upload(uuid: str = Form(...), room: str = Form(...), meter_type: str = Form(...),
                            value: str = Form(...), captured_at: str = Form(...), rollover: str = Form("false"),
                            image: UploadFile = File(...), s=Depends(db)):
        if not UUID_RE.match(uuid):
            fail(422, "uuid: 32 hex characters")
        if s.scalar(select(Reading.id).where(Reading.uuid == uuid)):
            return JSONResponse({"duplicate": True}, status_code=200)
        room_obj = room_by_number(s, room)
        check_type(meter_type)
        check_value(value)
        ts = parse_ts(captured_at)
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            fail(413, "image: larger than 5 MB")
        if not data.startswith(b"\xff\xd8\xff"):
            fail(422, "image: must be a JPEG")
        reading = Reading(uuid=uuid, room_id=room_obj.id, meter_type=meter_type, value=value,
                          rollover=rollover == "true", captured_at=to_db(ts), image_file=IMAGE_IN_DB, source="robot")
        s.add(reading)
        try:
            s.flush()
            s.add(ReadingImage(reading_id=reading.id, data=data))
            s.commit()
        except IntegrityError:  # same uuid arrived twice at the same moment
            s.rollback()
            return JSONResponse({"duplicate": True}, status_code=200)
        return JSONResponse({"ok": True}, status_code=201)

    # ---------------- tenant (secret link) ----------------
    def tenant_room(s, token) -> Room:
        room = s.scalar(select(Room).where(Room.token == token)) if len(token) <= 64 else None
        if room is None:
            fail(404, "ลิงก์ไม่ถูกต้องหรือถูกยกเลิกแล้ว")
        return room

    def public_line(line):
        keep = ("id", "value", "prev_value", "units", "amount", "price", "status", "captured_at", "has_image")
        return {k: line.get(k) for k in keep}

    @app.get("/api/tenant/{token}")
    def tenant_data(token: str, s=Depends(db)):
        room = tenant_room(s, token)
        periods = []
        for p in reading_periods(s, room.id, since=room.visible_from)[:12]:
            row = room_period(s, room, p, for_admin=False)
            periods.append({"period": p, "total": row["total"],
                            **{t: public_line(row[t]) for t in METER_TYPES}})
        disputes = s.scalars(select(Dispute).where(Dispute.room_id == room.id)
                             .order_by(Dispute.created_at.desc(), Dispute.id.desc()).limit(20))
        return {"room": room.number, "dorm_name": settings.dorm_name, "periods": periods,
                "rates": current_rates(s),
                "disputes": [{"period": d.period, "message": d.message, "status": d.status, "reply": d.reply,
                              "created_at": iso(d.created_at)} for d in disputes]}

    @app.get("/api/tenant/{token}/readings/{reading_id}/image")
    def tenant_image(token: str, reading_id: int, s=Depends(db)):
        room = tenant_room(s, token)
        reading = s.get(Reading, reading_id)
        if (reading is None or reading.deleted_at is not None or reading.room_id != room.id
                or (room.visible_from and reading.captured_at < room.visible_from)):
            fail(404, "not found")
        return image_response(reading, s)

    @app.post("/api/tenant/{token}/disputes", status_code=201)
    async def tenant_dispute(token: str, request: Request, s=Depends(db)):
        room = tenant_room(s, token)
        body = await json_body(request)
        try:
            billing.period_bounds(body.get("period"))
        except ValueError:
            fail(422, "period: รูปแบบ 2026-09")
        message = str(body.get("message", "")).strip()
        if not message or len(message) > 1000:
            fail(422, "message: 1-1000 ตัวอักษร")
        open_count = len(list(s.scalars(select(Dispute.id).where(Dispute.room_id == room.id, Dispute.status == "open"))))
        if open_count >= 5:
            fail(429, "มีเรื่องที่ยังรอตอบอยู่หลายรายการแล้ว")
        s.add(Dispute(room_id=room.id, period=body["period"], message=message))
        s.commit()
        return {"ok": True}

    return app


def app_from_env():
    return create_app(Settings.from_env())
