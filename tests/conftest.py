import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

# Tests run on SQLite for speed and zero setup; production uses PostgreSQL (see docker-compose.yml).
_db_file = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_file}"
os.environ["API_KEYS"] = "test-key,second-key"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["WHATSAPP_ACCESS_TOKEN"] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.notifications.dispatcher import NotificationDispatcher  # noqa: E402
from app.services.parcels import StatusChangeEvent  # noqa: E402


class RecordingNotifier:
    name = "recording"

    def __init__(self) -> None:
        self.events: list[StatusChangeEvent] = []

    async def notify(self, event: StatusChangeEvent) -> None:
        self.events.append(event)


@pytest.fixture
async def notifier() -> AsyncIterator[RecordingNotifier]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    recorder = RecordingNotifier()
    app.state.dispatcher = NotificationDispatcher([recorder])
    yield recorder


@pytest.fixture
async def client(notifier: RecordingNotifier) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": "test-key"}) as c:
        yield c


@pytest.fixture
async def parcel(client: httpx.AsyncClient) -> dict:
    wh = await client.post("/api/v1/warehouses", json={"name": "义乌 1号仓", "location": "Yiwu"})
    assert wh.status_code == 201, wh.text
    resp = await client.post(
        "/api/v1/parcels",
        json={"tracking_code": "yw-0001", "client_phone": "8 (701) 123-45-67", "client_name": "Айгерим"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json() | {"warehouse_id": wh.json()["id"]}
