import asyncio
import logging

import httpx

from app.config import Settings
from app.notifications.messages import status_change_text, status_label
from app.services.parcels import StatusChangeEvent

logger = logging.getLogger(__name__)

_RETRY_STATUSES = {429, 500, 502, 503, 504}


class WhatsAppError(RuntimeError):
    pass


class WhatsAppNotifier:
    """Meta WhatsApp Cloud API sender.

    Business-initiated messages outside the 24h customer service window must use an approved
    template, so configure WHATSAPP_TEMPLATE_NAME for production. Plain text is a dev fallback.
    """

    name = "whatsapp"

    def __init__(self, settings: Settings, client: httpx.AsyncClient, *, max_attempts: int = 3) -> None:
        assert settings.whatsapp_access_token is not None
        self._settings = settings
        self._client = client
        self._max_attempts = max_attempts
        self._url = (
            f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages"
        )
        self._headers = {"Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value()}"}

    def build_payload(self, event: StatusChangeEvent) -> dict:
        to = event.client_phone.lstrip("+")
        if self._settings.whatsapp_template_name:
            params = [event.tracking_code, status_label(event.new_status), event.client_name]
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": self._settings.whatsapp_template_name,
                    "language": {"code": self._settings.whatsapp_template_lang},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]},
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": status_change_text(event.tracking_code, event.client_name, event.new_status)},
        }

    async def notify(self, event: StatusChangeEvent) -> None:
        payload = self.build_payload(event)
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post(self._url, json=payload, headers=self._headers, timeout=10)
            except httpx.TransportError as exc:
                if attempt == self._max_attempts:
                    raise WhatsAppError(f"WhatsApp request failed: {exc}") from exc
            else:
                if response.is_success:
                    return
                if response.status_code not in _RETRY_STATUSES or attempt == self._max_attempts:
                    raise WhatsAppError(f"WhatsApp API {response.status_code}: {response.text[:500]}")
            await asyncio.sleep(2 ** (attempt - 1))
