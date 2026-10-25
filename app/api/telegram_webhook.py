import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import get_settings

router = APIRouter(tags=["telegram"], include_in_schema=False)


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    bot = getattr(request.app.state, "telegram_bot", None)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Telegram bot is not configured")
    expected = get_settings().telegram_webhook_secret
    if not expected or not secrets.compare_digest(x_telegram_bot_api_secret_token or "", expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid Telegram webhook secret")
    await request.app.state.telegram_dispatcher.feed_webhook_update(bot, update)
    return {"ok": True}
