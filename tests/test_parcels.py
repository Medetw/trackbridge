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


async def test_api_renames_warehouse(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    resp = await client.put(f"/api/v1/warehouses/{wid}", json={"name": " Yiwu Hub ", "location": "Zhejiang"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": wid, "name": "Yiwu Hub", "location": "Zhejiang"}

    await client.post("/api/v1/warehouses", json={"name": "Guangzhou"})
    dup = await client.put(f"/api/v1/warehouses/{wid}", json={"name": "Guangzhou"})
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"

    assert (await client.put("/api/v1/warehouses/9999", json={"name": "Z"})).status_code == 404
    assert (await client.put(f"/api/v1/warehouses/{wid}", json={"name": ""})).status_code == 422


async def test_rename_shows_in_public_tracking(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "warehouse_id": wid})
    await client.put(f"/api/v1/warehouses/{wid}", json={"name": "Yiwu Hub"})
    body = (await client.get("/api/v1/parcels/track/YW-0001")).json()
    assert body["warehouse"] == "Yiwu Hub"


async def test_api_deletes_warehouse(client: httpx.AsyncClient, parcel: dict) -> None:
    created = await client.post("/api/v1/warehouses", json={"name": "Guangzhou"})
    gid = created.json()["id"]
    resp = await client.delete(f"/api/v1/warehouses/{gid}")
    assert resp.status_code == 204 and resp.content == b""
    assert [w["name"] for w in (await client.get("/api/v1/warehouses")).json()] == ["义乌 1号仓"]
    assert (await client.delete(f"/api/v1/warehouses/{gid}")).status_code == 404


async def test_api_refuses_to_delete_warehouse_with_parcels(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    await client.post("/api/v1/parcels/receive", json={"tracking_code": "YW-0001", "warehouse_id": wid})
    resp = await client.delete(f"/api/v1/warehouses/{wid}")
    assert resp.status_code == 409
    assert "1 parcel(s)" in resp.json()["detail"]
    assert len((await client.get("/api/v1/warehouses")).json()) == 1


async def test_warehouse_write_endpoints_require_key(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    no_key = {"X-API-Key": ""}
    assert (await client.put(f"/api/v1/warehouses/{wid}", json={"name": "X"}, headers=no_key)).status_code == 401
    assert (await client.delete(f"/api/v1/warehouses/{wid}", headers=no_key)).status_code == 401
