import httpx

from tests.conftest import RecordingNotifier
from app.models import ParcelStatus


async def test_register_normalizes_code_and_phone(parcel: dict) -> None:
    assert parcel["tracking_code"] == "YW-0001"
    assert parcel["client_phone"] == "+77011234567"
    assert parcel["status"] == "registered"
    assert [h["new_status"] for h in parcel["history"]] == ["registered"]


async def test_duplicate_tracking_code_conflicts(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.post(
        "/api/v1/parcels", json={"tracking_code": "YW-0001", "client_phone": "+77011234567", "client_name": "X"}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"


async def test_receive_updates_status_and_notifies(
    client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier
) -> None:
    resp = await client.post(
        "/api/v1/parcels/receive",
        json={"tracking_code": "yw-0001", "weight_kg": 12.5, "volume_cbm": 0.08, "warehouse_id": parcel["warehouse_id"]},
        headers={"X-Worker-Id": "li.wei"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status_changed"] is True
    assert body["parcel"]["status"] == "received_at_china_wh"
    assert body["parcel"]["weight_kg"] == 12.5
    assert body["parcel"]["warehouse"]["name"] == "义乌 1号仓"

    assert len(notifier.events) == 1
    event = notifier.events[0]
    assert (event.old_status, event.new_status) == (ParcelStatus.registered, ParcelStatus.received_at_china_wh)
    assert event.client_phone == "+77011234567"

    detail = (await client.get("/api/v1/parcels/YW-0001")).json()
    assert detail["history"][-1]["changed_by"] == "li.wei"


async def test_rescan_updates_measurements_without_notifying(
    client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier
) -> None:
    await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "weight_kg": 10})
    resp = await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "weight_kg": 11})
    assert resp.status_code == 200
    assert resp.json()["status_changed"] is False
    assert resp.json()["parcel"]["weight_kg"] == 11
    assert len(notifier.events) == 1


async def test_receive_unknown_parcel_404(client: httpx.AsyncClient, notifier: RecordingNotifier) -> None:
    resp = await client.post("/api/v1/parcels/receive", json={"tracking_code": "NOPE-1"})
    assert resp.status_code == 404
    assert "NOPE-1" in resp.json()["detail"]
    assert notifier.events == []


async def test_receive_validates_weight(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "weight_kg": -1})
    assert resp.status_code == 422


async def test_receive_after_shipping_conflicts(client: httpx.AsyncClient, parcel: dict) -> None:
    await client.post("/api/v1/parcels/YW-0001/status", json={"status": "in_transit"})
    resp = await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001"})
    assert resp.status_code == 409


async def test_status_cannot_move_backwards(client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier) -> None:
    ok = await client.post("/api/v1/parcels/YW-0001/status", json={"status": "customs"})
    assert ok.status_code == 200
    back = await client.post("/api/v1/parcels/YW-0001/status", json={"status": "in_transit"})
    assert back.status_code == 409
    assert "only move forward" in back.json()["detail"]
    assert [e.new_status for e in notifier.events] == [ParcelStatus.customs]


async def test_api_key_required(client: httpx.AsyncClient, parcel: dict) -> None:
    for headers in ({"X-API-Key": ""}, {"X-API-Key": "wrong"}):
        resp = await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001"}, headers=headers)
        assert resp.status_code == 401
        assert "X-API-Key" in resp.json()["detail"]
    second = await client.get("/api/v1/parcels/YW-0001", headers={"X-API-Key": "second-key"})
    assert second.status_code == 200


async def test_public_tracking_hides_pii(client: httpx.AsyncClient, parcel: dict) -> None:
    await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "weight_kg": 3})
    resp = await client.get("/api/v1/parcels/track/yw-0001", headers={"X-API-Key": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "received_at_china_wh"
    assert [h["status"] for h in body["history"]] == ["registered", "received_at_china_wh"]
    text = resp.text
    assert "Айгерим" not in text and "7011234567" not in text and "changed_by" not in text


async def test_public_tracking_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/parcels/track/UNKNOWN")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
