"""Things needed to run on a free host (Render) with a managed Postgres (Neon)."""

import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app, normalize_database_url
from tests.conftest import JPEG, uid, upload


@pytest.mark.parametrize("given, expected", [
    ("postgres://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///./data/dorm.db", "sqlite:///./data/dorm.db"),
])
def test_normalize_database_url(given, expected):
    assert normalize_database_url(given) == expected


def test_photos_live_in_the_database_not_on_disk(settings, tmp_path):
    with TestClient(create_app(settings)) as c:
        c.post("/api/admin/login", json={"password": "correct horse"})
        c.post("/api/admin/rooms", json={"number": "101"})
        assert upload(c, uid(1)).status_code == 201
        files = [p for p in (tmp_path / "uploads").rglob("*") if p.is_file()]
        assert files == []  # host disks are wiped on every restart
        rid = c.get("/api/admin/summary?period=2026-09").json()["rooms"][0]["elec"]["id"]
        img = c.get(f"/api/admin/readings/{rid}/image")
        assert img.status_code == 200 and img.content == JPEG and img.headers["content-type"] == "image/jpeg"


def test_photos_survive_an_app_restart(settings):
    with TestClient(create_app(settings)) as c:
        c.post("/api/admin/login", json={"password": "correct horse"})
        c.post("/api/admin/rooms", json={"number": "101"})
        upload(c, uid(1))
    with TestClient(create_app(settings)) as c:  # same database, fresh process
        c.post("/api/admin/login", json={"password": "correct horse"})
        rid = c.get("/api/admin/summary?period=2026-09").json()["rooms"][0]["elec"]["id"]
        assert c.get(f"/api/admin/readings/{rid}/image").content == JPEG


def test_healthz_is_cheap_and_public(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_room_links_use_public_url_when_set(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path / 'd.db'}", upload_dir=str(tmp_path / "u"),
                 admin_password="pw", secret_key="k", device_key="d", secure_cookies=False,
                 public_url="https://mydorm.onrender.com/")
    with TestClient(create_app(s)) as c:
        c.post("/api/admin/login", json={"password": "pw"})
        room = c.post("/api/admin/rooms", json={"number": "101"}).json()
        assert room["link"] == f"https://mydorm.onrender.com/r/{room['token']}"


def test_room_link_falls_back_to_request_host(admin):
    room = admin.post("/api/admin/rooms", json={"number": "101"}).json()
    assert room["link"] == f"http://testserver/r/{room['token']}"
