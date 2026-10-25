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


async def test_list_shows_next_status_button(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.get("/admin/parcels")
    assert 'hx-post="/admin/parcels/YW-0001/status"' in resp.text
    assert "&#34;status&#34;: &#34;received_at_china_wh&#34;" in resp.text or '"status": "received_at_china_wh"' in resp.text

    await client.post("/api/v1/parcels/YW-0001/status", json={"status": "delivered"})
    done = await client.get("/admin/parcels")
    assert "YW-0001" in done.text and "hx-post" not in done.text


async def test_admin_advances_status_and_notifies(
    client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier
) -> None:
    resp = await client.post(
        "/admin/parcels/yw-0001/status",
        data={"status": "received_at_china_wh", "q": ""},
        headers={"X-Worker-Id": "manager1"},
    )
    assert resp.status_code == 200, resp.text
    assert "Принята на складе в Китае" in resp.text
    assert 'hx-vals' in resp.text and "in_transit" in resp.text  # next button now targets in_transit

    assert [e.new_status.value for e in notifier.events] == ["received_at_china_wh"]
    detail = (await client.get("/api/v1/parcels/YW-0001")).json()
    assert detail["history"][-1]["changed_by"] == "manager1"


async def test_admin_status_keeps_search_filter(client: httpx.AsyncClient, parcel: dict) -> None:
    await client.post(
        "/admin/parcels", data={"tracking_code": "GZ-9", "client_phone": "+77015550011", "client_name": "Ерлан"}
    )
    resp = await client.post("/admin/parcels/GZ-9/status", data={"status": "received_at_china_wh", "q": "GZ-"})
    assert "GZ-9" in resp.text and "YW-0001" not in resp.text


async def test_admin_status_errors(client: httpx.AsyncClient, parcel: dict, notifier: RecordingNotifier) -> None:
    url = "/admin/parcels/YW-0001/status"

    bad_key = await client.post(url, data={"status": "customs"}, headers={"X-API-Key": "nope"})
    assert bad_key.status_code == 401 and "API-ключ" in bad_key.text

    bogus = await client.post(url, data={"status": "teleported"})
    assert bogus.status_code == 422 and "Неизвестный статус" in bogus.text and "YW-0001" in bogus.text

    missing = await client.post("/admin/parcels/NOPE-1/status", data={"status": "customs"})
    assert missing.status_code == 404 and "NOPE-1" in missing.text

    assert (await client.post(url, data={"status": "customs"})).status_code == 200
    stale = await client.post(url, data={"status": "in_transit"})  # e.g. a second tab with an outdated list
    assert stale.status_code == 409 and "only move forward" in stale.text
    assert "На таможне" in stale.text  # list is refreshed to the real state

    assert [e.new_status.value for e in notifier.events] == ["customs"]


async def test_admin_page_has_warehouse_section(client: httpx.AsyncClient, parcel: dict) -> None:
    resp = await client.get("/admin")
    assert 'hx-post="/admin/warehouses"' in resp.text
    assert "(Yiwu)</option>" in resp.text  # parcel form's select
    assert '<span class="text-slate-500">· Yiwu</span>' in resp.text  # warehouse list


async def test_admin_creates_warehouse(client: httpx.AsyncClient, notifier: RecordingNotifier) -> None:
    resp = await client.post("/admin/warehouses", data={"name": "  Guangzhou  ", "location": "Baiyun"})
    assert resp.status_code == 200, resp.text
    assert "Guangzhou" in resp.text and "Baiyun" in resp.text
    assert resp.headers["HX-Trigger"] == "warehouses-changed"

    api = (await client.get("/api/v1/warehouses")).json()
    assert [w["name"] for w in api] == ["Guangzhou"]  # trimmed


async def test_admin_warehouse_errors(client: httpx.AsyncClient, parcel: dict) -> None:
    bad_key = await client.post("/admin/warehouses", data={"name": "X"}, headers={"X-API-Key": "nope"})
    assert bad_key.status_code == 401 and "API-ключ" in bad_key.text
    assert "HX-Trigger" not in bad_key.headers

    dup = await client.post("/admin/warehouses", data={"name": "义乌 1号仓"})
    assert dup.status_code == 409 and "already exists" in dup.text
    assert "HX-Trigger" not in dup.headers
    assert "Warehouse &#39;义乌 1号仓&#39; already exists" in dup.text  # error banner
    assert '<span class="font-medium">义乌 1号仓</span>' in dup.text  # the existing list is still shown

    blank = await client.post("/admin/warehouses", data={"name": "   "})
    assert blank.status_code == 422 and "название" in blank.text


async def test_warehouse_options_keep_selection(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    resp = await client.get("/admin/warehouses/options", params={"warehouse_id": str(wid)}, headers={"X-API-Key": ""})
    assert resp.status_code == 200
    assert f'<option value="{wid}" selected>' in resp.text

    none_selected = await client.get("/admin/warehouses/options")
    assert "selected" not in none_selected.text


async def _warehouse_id(client: httpx.AsyncClient, name: str) -> int:
    return next(w["id"] for w in (await client.get("/api/v1/warehouses")).json() if w["name"] == name)


async def test_warehouse_list_has_edit_and_delete_controls(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    resp = await client.get("/admin")
    assert f'hx-post="/admin/warehouses/{wid}"' in resp.text
    assert f'hx-post="/admin/warehouses/{wid}/delete"' in resp.text


async def test_admin_renames_warehouse(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    resp = await client.post(f"/admin/warehouses/{wid}", data={"name": " Yiwu Hub ", "location": "Zhejiang"})
    assert resp.status_code == 200, resp.text
    assert "Yiwu Hub" in resp.text and "Zhejiang" in resp.text and "义乌 1号仓" not in resp.text
    assert resp.headers["HX-Trigger"] == "warehouses-changed"
    assert [w["name"] for w in (await client.get("/api/v1/warehouses")).json()] == ["Yiwu Hub"]


async def test_admin_rename_errors(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    await client.post("/admin/warehouses", data={"name": "Guangzhou"})
    url = f"/admin/warehouses/{wid}"

    bad_key = await client.post(url, data={"name": "X"}, headers={"X-API-Key": "nope"})
    assert bad_key.status_code == 401 and "API-ключ" in bad_key.text

    dup = await client.post(url, data={"name": "Guangzhou"})
    assert dup.status_code == 409 and "already exists" in dup.text and "HX-Trigger" not in dup.headers
    assert "义乌 1号仓" in dup.text  # unchanged

    blank = await client.post(url, data={"name": "  "})
    assert blank.status_code == 422 and "название" in blank.text

    missing = await client.post("/admin/warehouses/9999", data={"name": "Y"})
    assert missing.status_code == 404 and "9999" in missing.text


async def test_admin_deletes_unused_warehouse(client: httpx.AsyncClient, parcel: dict) -> None:
    await client.post("/admin/warehouses", data={"name": "Guangzhou"})
    gid = await _warehouse_id(client, "Guangzhou")
    resp = await client.post(f"/admin/warehouses/{gid}/delete")
    assert resp.status_code == 200 and "Guangzhou" not in resp.text and "义乌 1号仓" in resp.text
    assert resp.headers["HX-Trigger"] == "warehouses-changed"


async def test_admin_refuses_to_delete_warehouse_with_parcels(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    await client.post(
        "/api/v1/parcels",
        json={"tracking_code": "WH-1", "client_phone": "+77011112233", "client_name": "X", "warehouse_id": wid},
    )
    resp = await client.post(f"/admin/warehouses/{wid}/delete")
    assert resp.status_code == 409 and "1 parcel(s)" in resp.text and "HX-Trigger" not in resp.headers
    assert "义乌 1号仓" in resp.text  # still listed
    assert len((await client.get("/api/v1/warehouses")).json()) == 1


async def test_admin_delete_requires_key(client: httpx.AsyncClient, parcel: dict) -> None:
    wid = parcel["warehouse_id"]
    resp = await client.post(f"/admin/warehouses/{wid}/delete", headers={"X-API-Key": ""})
    assert resp.status_code == 401
    assert len((await client.get("/api/v1/warehouses")).json()) == 1
