from typing import Any

import httpx
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.methods.base import TelegramMethod
from aiogram.types import Chat, Message
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ParcelStatus, TelegramContact
from app.notifications.telegram import TelegramNotifier, build_dispatcher
from app.services.parcels import StatusChangeEvent

USER = {"id": 555, "is_bot": False, "first_name": "Айгерим"}
CHAT = {"id": 555, "type": "private"}


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[TelegramMethod[Any]] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.sent.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=1, date=0, chat=Chat(id=method.chat_id, type="private"), text=method.text)
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass


def make_bot() -> tuple[Bot, RecordingSession]:
    session = RecordingSession()
    return Bot("42:TEST", session=session), session


def update(message: dict) -> dict:
    return {"update_id": 1, "message": {"message_id": 10, "date": 0, "chat": CHAT, "from": USER, **message}}


async def test_contact_links_chat_and_lists_parcels(parcel: dict) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SessionLocal)
    contact = {"phone_number": "77011234567", "first_name": "A", "user_id": 555}
    await dp.feed_webhook_update(bot, update({"contact": contact}))

    async with SessionLocal() as db:
        link = await db.scalar(select(TelegramContact).where(TelegramContact.chat_id == 555))
    assert link is not None and link.phone == "+77011234567"
    reply = session.sent[-1]
    assert isinstance(reply, SendMessage) and "YW-0001" in reply.text


async def test_foreign_contact_rejected(notifier: Any) -> None:
    bot, session = make_bot()
    contact = {"phone_number": "77011234567", "first_name": "A", "user_id": 999}
    await build_dispatcher(SessionLocal).feed_webhook_update(bot, update({"contact": contact}))
    async with SessionLocal() as db:
        assert await db.scalar(select(TelegramContact)) is None
    assert "собственный" in session.sent[-1].text  # type: ignore[attr-defined]


async def test_bare_code_lookup(parcel: dict) -> None:
    bot, session = make_bot()
    await build_dispatcher(SessionLocal).feed_webhook_update(bot, update({"text": "yw-0001"}))
    assert "Зарегистрирована" in session.sent[-1].text  # type: ignore[attr-defined]


async def test_notifier_sends_to_client_and_managers(parcel: dict) -> None:
    async with SessionLocal() as db:
        db.add(TelegramContact(phone="+77011234567", chat_id=555))
        await db.commit()
    bot, session = make_bot()
    event = StatusChangeEvent("YW-0001", "+77011234567", "Айгерим", ParcelStatus.in_transit, ParcelStatus.customs)
    await TelegramNotifier(bot, SessionLocal, manager_chat_ids=[-100]).notify(event)
    assert sorted(m.chat_id for m in session.sent) == [-100, 555]  # type: ignore[attr-defined]


async def test_webhook_rejects_without_bot(client: httpx.AsyncClient) -> None:
    resp = await client.post("/telegram/webhook", json={"update_id": 1})
    assert resp.status_code == 404
