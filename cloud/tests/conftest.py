import pytest
from fastapi.testclient import TestClient

from app.main import Settings, create_app

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200 + b"\xff\xd9"
DEVICE = {"X-Device-Key": "device-secret"}


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'dorm.db'}",
        upload_dir=str(tmp_path / "uploads"),
        admin_password="correct horse",
        secret_key="test-secret",
        device_key="device-secret",
        dorm_name="หอทดสอบ",
        secure_cookies=False,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def admin(settings):
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/admin/login", json={"password": "correct horse"}).status_code == 200
        yield c


def upload(client, uuid, room="101", meter_type="elec", value="3398", captured_at="2026-09-30T07:30:00+00:00",
           rollover="false", image=JPEG, headers=DEVICE):
    return client.post("/api/device/readings", headers=headers, data={
        "uuid": uuid, "room": room, "meter_type": meter_type, "value": value,
        "captured_at": captured_at, "rollover": rollover,
    }, files={"image": ("x.jpg", image, "image/jpeg")})


def uid(n):
    return f"{n:032x}"
