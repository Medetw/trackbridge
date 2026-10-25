import httpx

from tests.conftest import RecordingNotifier


async def test_admin_page_renders(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert 'hx-post="/admin/parcels"' in resp.text
    assert "义乌 1号仓" in resp.text


async def test_admin_registers_parcel(client: httpx.AsyncClient, notifier: RecordingNotifier) -> None:
    resp = await client.post(
        "/admin/parcels",
        data={"tracking_code": " gz-77 ", "client_phone": "8 701 555 00 11", "client_name": "Ерлан", "warehouse_id": ""},
        headers={"X-Worker-Id": "manager1"},
    )
    assert resp.status_code == 200, resp.text
    assert "GZ-77" in resp.text and "+77015550011" in resp.text
    assert resp.headers["HX-Trigger"] == "parcels-changed"

    detail = (await client.get("/api/v1/parcels/GZ-77")).json()
    assert detail["status"] == "registered"
    assert detail["history"][0]["changed_by"] == "manager1"
    assert notifier.events == []  # registering doesn't notify


async def test_admin_register_errors(client: httpx.AsyncClient, parcel: dict) -> None:
    bad_key = await client.post(
        "/admin/parcels", data={"tracking_code": "A1B", "client_phone": "+77011112233", "client_name": "X"},
        headers={"X-API-Key": "nope"},
    )
    assert bad_key.status_code == 401 and "API-ключ" in bad_key.text

    dup = await client.post(
        "/admin/parcels", data={"tracking_code": "yw-0001", "client_phone": "+77011112233", "client_name": "X"}
    )
    assert dup.status_code == 409 and "already exists" in dup.text

    invalid = await client.post(
        "/admin/parcels", data={"tracking_code": "A1B", "client_phone": "123", "client_name": "X"}
    )
    assert invalid.status_code == 422 and "телефон" in invalid.text and "трек-код" not in invalid.text


async def test_admin_list_and_search(client: httpx.AsyncClient, parcel: dict) -> None:
    await client.post(
        "/admin/parcels", data={"tracking_code": "GZ-9", "client_phone": "+77015550011", "client_name": "Ерлан"}
    )
    everything = await client.get("/admin/parcels")
    assert everything.status_code == 200
    assert "YW-0001" in everything.text and "GZ-9" in everything.text

    # Exact case: SQLite's lower() is ASCII-only, so case-insensitive Cyrillic is only exercised on PostgreSQL.
    by_name = await client.get("/admin/parcels", params={"q": "Ерл"})
    assert "GZ-9" in by_name.text and "YW-0001" not in by_name.text

    by_phone = await client.get("/admin/parcels", params={"q": "7011234567"})
    assert "YW-0001" in by_phone.text and "GZ-9" not in by_phone.text

    wildcard = await client.get("/admin/parcels", params={"q": "%"})
    assert "Ничего не найдено" in wildcard.text


async def test_admin_list_requires_key(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.get("/admin/parcels", headers={"X-API-Key": ""})
    assert resp.status_code == 401
    assert "YW-0001" not in resp.text
