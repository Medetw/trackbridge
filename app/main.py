import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import admin, parcels, telegram_webhook, warehouse
from app.config import get_settings
from app.db import SessionLocal, engine
from app.errors import register_error_handlers
from app.notifications.base import Notifier
from app.notifications.dispatcher import NotificationDispatcher
from app.notifications.telegram import TelegramNotifier, build_dispatcher, create_bot
from app.notifications.whatsapp import WhatsAppNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("trackbridge")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.api_key_list:
        logger.warning("API_KEYS is empty: every protected endpoint will reject requests")

    http_client = httpx.AsyncClient()
    notifiers: list[Notifier] = []
    bot = None

    if settings.telegram_enabled:
        assert settings.telegram_bot_token is not None
        bot = create_bot(settings.telegram_bot_token.get_secret_value())
        app.state.telegram_bot = bot
        app.state.telegram_dispatcher = build_dispatcher(SessionLocal)
        notifiers.append(TelegramNotifier(bot, SessionLocal, settings.manager_chat_ids))
        if settings.public_base_url and settings.telegram_webhook_secret:
            await bot.set_webhook(
                f"{settings.public_base_url.rstrip('/')}/telegram/webhook",
                secret_token=settings.telegram_webhook_secret,
                allowed_updates=app.state.telegram_dispatcher.resolve_used_update_types(),
            )
            logger.info("Telegram webhook registered")
        else:
            logger.warning("PUBLIC_BASE_URL or TELEGRAM_WEBHOOK_SECRET missing: bot can send but won't receive updates")
    if settings.whatsapp_enabled:
        notifiers.append(WhatsAppNotifier(settings, http_client))

    app.state.dispatcher = NotificationDispatcher(notifiers)
    logger.info("Notification channels: %s", [n.name for n in notifiers] or "none")
    try:
        yield
    finally:
        await http_client.aclose()
        if bot is not None:
            await bot.session.close()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="TrackBridge",
        description="China → Kazakhstan cargo tracking: warehouse scanning, parcel tracking, messenger notifications.",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(parcels.public)
    app.include_router(parcels.protected)
    app.include_router(warehouse.router)
    app.include_router(admin.router)
    app.include_router(telegram_webhook.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/warehouse/scan")

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
