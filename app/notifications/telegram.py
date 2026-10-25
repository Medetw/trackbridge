import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import NotFoundError
from app.models import TelegramContact
from app.notifications.messages import status_change_text, status_label
from app.phone import normalize_phone
from app.services import parcels as parcel_service
from app.services.parcels import StatusChangeEvent

logger = logging.getLogger(__name__)


def create_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


class TelegramNotifier:
    """Sends status changes to every chat linked to the client's phone, plus manager chats."""

    name = "telegram"

    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession], manager_chat_ids: list[int]) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._manager_chat_ids = manager_chat_ids

    async def notify(self, event: StatusChangeEvent) -> None:
        async with self._session_factory() as session:
            client_chats = list(
                await session.scalars(select(TelegramContact.chat_id).where(TelegramContact.phone == event.client_phone))
            )
        text = html.escape(status_change_text(event.tracking_code, event.client_name, event.new_status))
        manager_text = (
            f"📦 <b>{html.escape(event.tracking_code)}</b> → {status_label(event.new_status)}\n"
            f"{html.escape(event.client_name)}, {html.escape(event.client_phone)}"
        )
        sends = [self._bot.send_message(chat_id, text) for chat_id in client_chats]
        sends += [self._bot.send_message(chat_id, manager_text) for chat_id in self._manager_chat_ids]
        results = await asyncio.gather(*sends, return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise RuntimeError(f"{len(errors)}/{len(sends)} Telegram sends failed: {errors[0]!r}")


def _share_contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_dispatcher(session_factory: async_sessionmaker[AsyncSession]) -> Dispatcher:
    """Client-facing bot: link phone via shared contact, then `/track CODE` or just send a code."""
    router = Router()

    async def reply_with_parcel(message: Message, code: str) -> None:
        async with session_factory() as session:
            try:
                parcel = await parcel_service.get_parcel(session, code)
            except NotFoundError:
                await message.answer(f"Посылка <b>{html.escape(code)}</b> не найдена.")
                return
        lines = [f"📦 <b>{html.escape(parcel.tracking_code)}</b>: {status_label(parcel.status)}"]
        if parcel.weight_kg:
            lines.append(f"Вес: {parcel.weight_kg:g} кг")
        await message.answer("\n".join(lines))

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Здравствуйте! Поделитесь номером телефона, указанным при оформлении груза, "
            "чтобы получать уведомления о статусе посылок.\n\n"
            "Проверить посылку: отправьте трек-код или /track КОД",
            reply_markup=_share_contact_keyboard(),
        )

    @router.message(F.contact)
    async def contact_shared(message: Message) -> None:
        contact = message.contact
        assert contact is not None and message.from_user is not None
        if contact.user_id != message.from_user.id:
            await message.answer("Пожалуйста, отправьте свой собственный номер кнопкой ниже.", reply_markup=_share_contact_keyboard())
            return
        try:
            phone = normalize_phone(contact.phone_number)
        except ValueError:
            await message.answer("Не удалось распознать номер телефона.")
            return
        async with session_factory() as session:
            link = await session.scalar(select(TelegramContact).where(TelegramContact.chat_id == message.chat.id))
            if link is None:
                session.add(TelegramContact(phone=phone, chat_id=message.chat.id))
            else:
                link.phone = phone
            await session.commit()
            active = await parcel_service.list_parcels_by_phone(session, phone)
        lines = [f"✅ Номер {html.escape(phone)} подключен. Мы сообщим об изменении статуса."]
        if active:
            lines.append("\nВаши посылки:")
            lines += [f"• <b>{html.escape(p.tracking_code)}</b>: {status_label(p.status)}" for p in active]
        await message.answer("\n".join(lines), reply_markup=ReplyKeyboardRemove())

    @router.message(Command("track"))
    async def track(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Использование: /track КОД")
            return
        await reply_with_parcel(message, command.args.split()[0])

    @router.message(F.text.regexp(r"^[A-Za-z0-9\-_]{3,64}$"))
    async def bare_code(message: Message) -> None:
        assert message.text is not None
        await reply_with_parcel(message, message.text)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
