import pytest

from tests.conftest import DEVICE, JPEG, uid, upload


def add_rooms(admin, *numbers):
    ids = {}
    for n in numbers:
        r = admin.post("/api/admin/rooms", json={"number": n})
        assert r.status_code == 201, r.text
        ids[n] = r.json()
    return ids


def set_rates(admin, water="18", elec="7"):
    assert admin.put("/api/admin/rates", json={"water": water, "elec": elec}).status_code == 200


# ---------------- admin auth ----------------

def test_admin_apis_need_login(client):
    for method, path in [("get", "/api/admin/rooms"), ("get", "/api/admin/summary?period=2026-09"),
                         ("put", "/api/admin/rates"), ("get", "/api/admin/disputes")]:
        assert getattr(client, method)(path).status_code == 401


def test_wrong_password(client):
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401


def test_login_is_rate_limited(client):
    codes = [client.post("/api/admin/login", json={"password": "nope"}).status_code for _ in range(7)]
    assert codes[-1] == 429
    assert client.post("/api/admin/login", json={"password": "correct horse"}).status_code == 429


def test_logout(admin):
    admin.post("/api/admin/logout")
    assert admin.get("/api/admin/rooms").status_code == 401


def test_session_cookie_is_httponly(settings):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/admin/login", json={"password": "correct horse"})
        assert "httponly" in r.headers["set-cookie"].lower()


# ---------------- rooms ----------------

def test_room_numbers_are_unique_and_validated(admin):
    add_rooms(admin, "101")
    assert admin.post("/api/admin/rooms", json={"number": "101"}).status_code == 409
    for bad in ["", "   ", "1" * 20, "<b>"]:
        assert admin.post("/api/admin/rooms", json={"number": bad}).status_code == 422


def test_room_qr_is_svg(admin):
    rid = add_rooms(admin, "101")["101"]["id"]
    r = admin.get(f"/api/admin/rooms/{rid}/qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")


# ---------------- device ----------------

def test_device_needs_key(admin, client):
    add_rooms(admin, "101")
    assert upload(client, uid(1), headers={}).status_code == 401
    assert upload(client, uid(1), headers={"X-Device-Key": "wrong"}).status_code == 401
    assert client.get("/api/device/rooms", headers={"X-Device-Key": "wrong"}).status_code == 401


def test_device_upload_is_idempotent(admin, client):
    add_rooms(admin, "101")
    assert upload(client, uid(1)).status_code == 201
    again = upload(client, uid(1))
    assert again.status_code == 200 and again.json()["duplicate"] is True
    summary = admin.get("/api/admin/summary?period=2026-09").json()
    assert summary["rooms"][0]["elec"]["value"] == "3398"


@pytest.mark.parametrize("kw, field", [
    ({"room": "999"}, "room"),
    ({"meter_type": "gas"}, "meter_type"),
    ({"value": "12a4"}, "value"),
    ({"value": "1" * 9}, "value"),
    ({"captured_at": "yesterday"}, "captured_at"),
    ({"image": b"not a jpeg"}, "image"),
    ({"image": b"\xff\xd8\xff" + b"0" * (6 * 1024 * 1024)}, "image"),
])
def test_device_upload_validation(admin, client, kw, field):
    add_rooms(admin, "101")
    r = upload(client, uid(2), **kw)
    assert r.status_code in (413, 422)
    assert field in r.json()["detail"]


def test_device_upload_bad_uuid(admin, client):
    add_rooms(admin, "101")
    assert upload(client, "../../evil").status_code == 422


def test_device_rooms_include_latest_previous(admin, client):
    add_rooms(admin, "101", "102")
    upload(client, uid(1), value="3312", captured_at="2026-09-01T03:00:00+00:00")
    upload(client, uid(2), value="3398", captured_at="2026-09-30T03:00:00+00:00")
    rooms = client.get("/api/device/rooms", headers=DEVICE).json()["rooms"]
    assert [r["number"] for r in rooms] == ["101", "102"]
    assert rooms[0]["prev"]["elec"]["value"] == "3398"
    assert rooms[0]["prev"]["water"] is None


def test_inactive_room_not_offered_to_robot(admin, client):
    ids = add_rooms(admin, "101", "102")
    admin.patch(f"/api/admin/rooms/{ids['102']['id']}", json={"active": False})
    rooms = client.get("/api/device/rooms", headers=DEVICE).json()["rooms"]
    assert [r["number"] for r in rooms] == ["101"]


# ---------------- summary / billing ----------------

def seed_month(admin, client):
    add_rooms(admin, "101", "102", "103")
    set_rates(admin)
    n = iter(range(1, 100))
    aug, sep = "2026-08-31T03:00:00+00:00", "2026-09-30T03:00:00+00:00"
    for room, t, before, after in [("101", "water", "0834", "0851"), ("101", "elec", "4480", "4521"),
                                   ("102", "water", "1207", "1229"), ("102", "elec", "5120", "5098")]:
        upload(client, uid(next(n)), room=room, meter_type=t, value=before, captured_at=aug)
        upload(client, uid(next(n)), room=room, meter_type=t, value=after, captured_at=sep)


def test_summary_numbers(admin, client):
    seed_month(admin, client)
    s = admin.get("/api/admin/summary?period=2026-09").json()
    rooms = {r["number"]: r for r in s["rooms"]}
    r101 = rooms["101"]
    assert r101["water"]["units"] == 17 and r101["water"]["amount"] == "306.00"
    assert r101["elec"]["units"] == 41 and r101["elec"]["amount"] == "287.00"
    assert r101["total"] == "593.00"
    assert rooms["102"]["elec"]["status"] == "review" and rooms["102"]["total"] is None
    assert rooms["103"]["water"]["status"] == "missing"
    assert s["counts"] == {"water": 2, "elec": 2, "review": 1, "rooms": 3}
    assert s["grand_total"] == "593.00"
    assert s["rates"] == {"water": "18", "elec": "7"}


def test_bad_period_is_422(admin):
    assert admin.get("/api/admin/summary?period=2026-13").status_code == 422


def test_edit_reading_fixes_review_and_keeps_history(admin, client):
    seed_month(admin, client)
    s = admin.get("/api/admin/summary?period=2026-09").json()
    rid = next(r for r in s["rooms"] if r["number"] == "102")["elec"]["id"]
    assert admin.patch(f"/api/admin/readings/{rid}", json={"value": "5198", "note": "พิมพ์ผิด"}).status_code == 200
    s = admin.get("/api/admin/summary?period=2026-09").json()
    r102 = next(r for r in s["rooms"] if r["number"] == "102")
    assert r102["elec"]["units"] == 78 and r102["elec"]["edited"] is True
    hist = admin.get(f"/api/admin/readings/{rid}/history").json()["history"]
    assert hist[0]["old_value"] == "5098" and hist[0]["new_value"] == "5198"


def test_confirm_rollover(admin, client):
    seed_month(admin, client)
    s = admin.get("/api/admin/summary?period=2026-09").json()
    rid = next(r for r in s["rooms"] if r["number"] == "102")["elec"]["id"]
    admin.patch(f"/api/admin/readings/{rid}", json={"rollover": True})
    s = admin.get("/api/admin/summary?period=2026-09").json()
    assert next(r for r in s["rooms"] if r["number"] == "102")["elec"]["units"] == 5098 + 10000 - 5120


def test_move_reading_to_other_room(admin, client):
    seed_month(admin, client)
    s = admin.get("/api/admin/summary?period=2026-09").json()
    rid = next(r for r in s["rooms"] if r["number"] == "101")["water"]["id"]
    assert admin.patch(f"/api/admin/readings/{rid}", json={"room": "103"}).status_code == 200
    s = admin.get("/api/admin/summary?period=2026-09").json()
    rooms = {r["number"]: r for r in s["rooms"]}
    assert rooms["103"]["water"]["value"] == "0851"
    assert rooms["101"]["water"]["status"] == "missing"


def test_edit_validation(admin, client):
    seed_month(admin, client)
    rid = admin.get("/api/admin/summary?period=2026-09").json()["rooms"][0]["water"]["id"]
    assert admin.patch(f"/api/admin/readings/{rid}", json={"value": "abc"}).status_code == 422
    assert admin.patch(f"/api/admin/readings/{rid}", json={"room": "999"}).status_code == 422
    assert admin.patch("/api/admin/readings/99999", json={"value": "1"}).status_code == 404


def test_delete_hides_reading_and_falls_back_to_older(admin, client):
    seed_month(admin, client)
    add_extra = upload(client, uid(90), room="101", meter_type="water", value="0860",
                       captured_at="2026-09-30T05:00:00+00:00")
    assert add_extra.status_code == 201
    s = admin.get("/api/admin/summary?period=2026-09").json()
    latest = s["rooms"][0]["water"]
    assert latest["value"] == "0860"
    assert admin.delete(f"/api/admin/readings/{latest['id']}").status_code == 200
    s = admin.get("/api/admin/summary?period=2026-09").json()
    assert s["rooms"][0]["water"]["value"] == "0851"
    assert admin.get(f"/api/admin/readings/{latest['id']}/image").status_code == 404


def test_admin_manual_reading(admin):
    add_rooms(admin, "101")
    r = admin.post("/api/admin/readings", json={"room": "101", "meter_type": "water", "value": "0100",
                                                "captured_at": "2026-09-15T03:00:00+00:00"})
    assert r.status_code == 201
    s = admin.get("/api/admin/summary?period=2026-09").json()
    assert s["rooms"][0]["water"]["source"] == "admin" and s["rooms"][0]["water"]["has_image"] is False


def test_rates_history(admin):
    set_rates(admin, "18", "7")
    set_rates(admin, "20", "7.5")
    assert admin.get("/api/admin/rates").json()["current"] == {"water": "20", "elec": "7.5"}
    for bad in [{"water": "-1", "elec": "7"}, {"water": "abc", "elec": "7"}, {"water": "18"}]:
        assert admin.put("/api/admin/rates", json=bad).status_code == 422


def test_periods_list(admin, client):
    seed_month(admin, client)
    assert admin.get("/api/admin/periods").json()["periods"] == ["2026-09", "2026-08"]


# ---------------- tenant link ----------------

def tenant_token(admin, number):
    rooms = admin.get("/api/admin/rooms").json()["rooms"]
    return next(r for r in rooms if r["number"] == number)["token"]


def test_tenant_sees_only_own_room(admin, client):
    seed_month(admin, client)
    t101 = tenant_token(admin, "101")
    data = client.get(f"/api/tenant/{t101}").json()
    assert data["room"] == "101" and data["dorm_name"] == "หอทดสอบ"
    sep = next(p for p in data["periods"] if p["period"] == "2026-09")
    assert sep["total"] == "593.00"
    img_id = sep["water"]["id"]
    assert client.get(f"/api/tenant/{t101}/readings/{img_id}/image").content == JPEG
    # someone else's reading via my token
    s = admin.get("/api/admin/summary?period=2026-09").json()
    other = next(r for r in s["rooms"] if r["number"] == "102")["water"]["id"]
    assert client.get(f"/api/tenant/{t101}/readings/{other}/image").status_code == 404


def test_unknown_token_is_404(client):
    assert client.get("/api/tenant/not-a-real-token").status_code == 404


def test_tenant_response_has_no_admin_fields(admin, client):
    seed_month(admin, client)
    data = client.get(f"/api/tenant/{tenant_token(admin, '101')}").json()
    text = str(data)
    assert "token" not in text and "note" not in text


def test_new_link_invalidates_old_but_keeps_history(admin, client):
    ids = add_rooms(admin, "101")
    old = ids["101"]["token"]
    upload(client, uid(1), captured_at="2026-09-01T03:00:00+00:00")
    new = admin.post(f"/api/admin/rooms/{ids['101']['id']}/new-link", json={"new_tenant": False}).json()["token"]
    assert client.get(f"/api/tenant/{old}").status_code == 404
    assert len(client.get(f"/api/tenant/{new}").json()["periods"]) == 1


def test_new_tenant_does_not_see_previous_tenants_photos(admin, client):
    ids = add_rooms(admin, "101")
    upload(client, uid(1), value="3312", captured_at="2020-09-01T03:00:00+00:00")
    new = admin.post(f"/api/admin/rooms/{ids['101']['id']}/new-link", json={"new_tenant": True}).json()["token"]
    data = client.get(f"/api/tenant/{new}").json()
    assert data["periods"] == []
    s = admin.get("/api/admin/summary?period=2020-09").json()
    assert client.get(f"/api/tenant/{new}/readings/{s['rooms'][0]['elec']['id']}/image").status_code == 404


def test_dispute_flow(admin, client):
    seed_month(admin, client)
    tok = tenant_token(admin, "101")
    r = client.post(f"/api/tenant/{tok}/disputes", json={"period": "2026-09", "message": "เลขไฟไม่ตรงกับรูป"})
    assert r.status_code == 201
    assert client.post(f"/api/tenant/{tok}/disputes", json={"period": "2026-09", "message": ""}).status_code == 422
    assert client.post(f"/api/tenant/{tok}/disputes", json={"period": "2026-09", "message": "x" * 1001}).status_code == 422
    items = admin.get("/api/admin/disputes").json()["disputes"]
    assert items[0]["room"] == "101" and items[0]["status"] == "open"
    admin.patch(f"/api/admin/disputes/{items[0]['id']}", json={"status": "resolved", "reply": "แก้ให้แล้ว"})
    mine = client.get(f"/api/tenant/{tok}").json()["disputes"]
    assert mine[0]["reply"] == "แก้ให้แล้ว" and mine[0]["status"] == "resolved"


# ---------------- pages + headers ----------------

@pytest.mark.parametrize("path", ["/calculator", "/admin", "/admin/login", "/"])
def test_pages_render(client, path):
    r = client.get(path, follow_redirects=True)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_tenant_page_not_indexed_and_no_referrer(admin, client):
    add_rooms(admin, "101")
    r = client.get(f"/r/{tenant_token(admin, '101')}")
    assert r.status_code == 200
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in r.headers["x-robots-tag"]


def test_security_headers(client):
    r = client.get("/calculator")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
