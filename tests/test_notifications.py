import httpx
import pytest

from app.config import Settings
from app.models import ParcelStatus
from app.notifications.dispatcher import NotificationDispatcher
from app.notifications.whatsapp import WhatsAppError, WhatsAppNotifier
from app.phone import normalize_phone
from app.services.parcels import StatusChangeEvent

EVENT = StatusChangeEvent(
    tracking_code="YW-0001",
    client_phone="+77011234567",
    client_name="Айгерим",
    old_status=ParcelStatus.registered,
    new_status=ParcelStatus.received_at_china_wh,
)


def wa_settings(**overrides: str) -> Settings:
    return Settings(whatsapp_access_token="tok", whatsapp_phone_number_id="123", **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("87011234567", "+77011234567"), ("+7 701 123 45 67", "+77011234567"), ("7011234567", "+77011234567"),
     ("+86 138 0013 8000", "+8613800138000")],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


def test_normalize_phone_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        normalize_phone("12345")


async def test_whatsapp_template_payload_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={})

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.notifications.whatsapp.asyncio.sleep", no_sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notifier = WhatsAppNotifier(wa_settings(whatsapp_template_name="parcel_status"), client)
        await notifier.notify(EVENT)

    assert len(calls) == 2
    assert calls[0].url.path == "/v21.0/123/messages"
    assert calls[0].headers["Authorization"] == "Bearer tok"
    payload = notifier.build_payload(EVENT)
    assert payload["to"] == "77011234567"
    assert payload["template"]["name"] == "parcel_status"
    params = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
    assert params == ["YW-0001", "Принята на складе в Китае", "Айгерим"]


async def test_whatsapp_client_error_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "bad number"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WhatsAppError, match="400"):
            await WhatsAppNotifier(wa_settings(), client).notify(EVENT)
    assert calls == 1


async def test_dispatcher_isolates_failing_channel() -> None:
    delivered: list[str] = []

    class Broken:
        name = "broken"

        async def notify(self, event: StatusChangeEvent) -> None:
            raise RuntimeError("boom")

    class Working:
        name = "working"

        async def notify(self, event: StatusChangeEvent) -> None:
            delivered.append(event.tracking_code)

    await NotificationDispatcher([Broken(), Working()]).dispatch(EVENT)
    assert delivered == ["YW-0001"]
