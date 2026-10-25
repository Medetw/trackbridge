import httpx

from tests.conftest import RecordingNotifier


async def test_scan_page_renders(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.get("/warehouse/scan")
    assert resp.status_code == 200
    assert 'hx-post="/warehouse/scan"' in resp.text
    assert "义乌 1号仓" in resp.text


async def test_scan_form_receives_parcel(client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier) -> None:
    resp = await client.post(
        "/warehouse/scan",
        data={"tracking_code": "yw-0001", "weight_kg": "4.2", "volume_cbm": "", "warehouse_id": ""},
    )
    assert resp.status_code == 200, resp.text
    assert "YW-0001" in resp.text and "Принято" in resp.text and "4.2 кг" in resp.text
    assert len(notifier.events) == 1


async def test_scan_form_errors_render_partials(client: httpx.AsyncClient, parcel: dict) -> None:
    bad_key = await client.post("/warehouse/scan", data={"tracking_code": "YW-0001"}, headers={"X-API-Key": "x"})
    assert bad_key.status_code == 401 and "API-ключ" in bad_key.text

    missing = await client.post("/warehouse/scan", data={"tracking_code": "MISSING-9"})
    assert missing.status_code == 404 and "MISSING-9" in missing.text

    invalid = await client.post("/warehouse/scan", data={"tracking_code": "YW-0001", "weight_kg": "abc"})
    assert invalid.status_code == 422 and "weight_kg" in invalid.text
