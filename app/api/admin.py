from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Security
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import DispatcherDep, SessionDep, WorkerDep
from app.errors import DomainError
from app.models import ParcelStatus
from app.schemas import ParcelCreate, WarehouseCreate, WarehouseUpdate
from app.security import api_key_header, is_valid_api_key
from app.services import parcels as service
from app.templating import blank_to_none, templates

router = APIRouter(prefix="/admin", tags=["admin-ui"], include_in_schema=False)

BAD_KEY = "Неверный API-ключ. Откройте настройки ⚙️ и введите ключ."


@router.get("", response_class=HTMLResponse)
async def admin_page(request: Request, session: SessionDep) -> HTMLResponse:
    warehouses = await service.list_warehouses(session)
    return templates.TemplateResponse(request, "admin.html", {"warehouses": warehouses})


async def _rows_response(
    request: Request, session: SessionDep, q: str, *, error: str | None = None, status_code: int = 200
) -> HTMLResponse:
    q = q.strip()
    parcels = await service.list_recent_parcels(session, query=q or None)
    return templates.TemplateResponse(
        request, "partials/admin_rows.html", {"parcels": parcels, "q": q, "error": error}, status_code=status_code
    )


@router.get("/parcels", response_class=HTMLResponse)
async def parcel_rows(
    request: Request,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    q: str = "",
) -> HTMLResponse:
    if not is_valid_api_key(api_key, settings):
        return templates.TemplateResponse(request, "partials/admin_rows.html", {"error": BAD_KEY}, status_code=401)
    return await _rows_response(request, session, q)


@router.post("/parcels/{tracking_code}/status", response_class=HTMLResponse)
async def change_status(
    tracking_code: str,
    request: Request,
    session: SessionDep,
    worker: WorkerDep,
    dispatcher: DispatcherDep,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    status: Annotated[str, Form()] = "",
    q: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """HTMX twin of POST /api/v1/parcels/{code}/status: re-renders the (filtered) list instead of returning JSON."""
    if not is_valid_api_key(api_key, settings):
        return templates.TemplateResponse(request, "partials/admin_rows.html", {"error": BAD_KEY}, status_code=401)
    try:
        new_status = ParcelStatus(status)
        _, event = await service.update_status(session, tracking_code, new_status, worker)
    except ValueError:
        return await _rows_response(request, session, q, error=f"Неизвестный статус: {status}", status_code=422)
    except DomainError as exc:
        return await _rows_response(request, session, q, error=exc.message, status_code=exc.status_code)
    background.add_task(dispatcher.dispatch, event)
    return await _rows_response(request, session, q)


@router.post("/parcels", response_class=HTMLResponse)
async def register_parcel(
    request: Request,
    session: SessionDep,
    worker: WorkerDep,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    tracking_code: Annotated[str, Form()] = "",
    client_phone: Annotated[str, Form()] = "",
    client_name: Annotated[str, Form()] = "",
    warehouse_id: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """HTMX twin of POST /api/v1/parcels: same service call, renders a result card instead of JSON."""

    def error(message: str, status_code: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/admin_result.html", {"error": message}, status_code=status_code
        )

    if not is_valid_api_key(api_key, settings):
        return error(BAD_KEY, 401)
    try:
        data = ParcelCreate(
            tracking_code=tracking_code,
            client_phone=client_phone,
            client_name=client_name,
            warehouse_id=blank_to_none(warehouse_id),  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        labels = {"tracking_code": "трек-код", "client_phone": "телефон", "client_name": "имя", "warehouse_id": "склад"}
        fields = ", ".join(labels.get(str(e["loc"][0]), str(e["loc"][0])) for e in exc.errors())
        return error(f"Проверьте поля: {fields}", 422)
    try:
        parcel = await service.register_parcel(session, data, worker)
    except DomainError as exc:
        return error(exc.message, exc.status_code)
    return templates.TemplateResponse(
        request, "partials/admin_result.html", {"parcel": parcel}, headers={"HX-Trigger": "parcels-changed"}
    )


async def _warehouses_response(
    request: Request, session: SessionDep, *, error: str | None = None, status_code: int = 200, trigger: bool = False
) -> HTMLResponse:
    warehouses = await service.list_warehouses(session)
    return templates.TemplateResponse(
        request,
        "partials/admin_warehouses.html",
        {"warehouses": warehouses, "error": error},
        status_code=status_code,
        headers={"HX-Trigger": "warehouses-changed"} if trigger else None,
    )


@router.get("/warehouses/options", response_class=HTMLResponse)
async def warehouse_options(request: Request, session: SessionDep, warehouse_id: str = "") -> HTMLResponse:
    """<option> list for the parcel form's select (same data the page already renders without a key)."""
    warehouses = await service.list_warehouses(session)
    return templates.TemplateResponse(
        request,
        "partials/admin_warehouse_options.html",
        {"warehouses": warehouses, "selected_id": warehouse_id},
    )


WAREHOUSE_FIELD_LABELS = {"name": "название", "location": "расположение"}


def _parse_warehouse(name: str, location: str) -> WarehouseCreate | str:
    """Returns the validated payload, or a user-facing error message."""
    try:
        return WarehouseUpdate(name=name, location=location)
    except ValidationError as exc:
        fields = ", ".join(WAREHOUSE_FIELD_LABELS.get(str(e["loc"][0]), str(e["loc"][0])) for e in exc.errors())
        return f"Проверьте поля: {fields}"


@router.post("/warehouses", response_class=HTMLResponse)
async def create_warehouse(
    request: Request,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    name: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """HTMX twin of POST /api/v1/warehouses: re-renders the warehouse list instead of returning JSON."""
    if not is_valid_api_key(api_key, settings):
        return await _warehouses_response(request, session, error=BAD_KEY, status_code=401)
    data = _parse_warehouse(name, location)
    if isinstance(data, str):
        return await _warehouses_response(request, session, error=data, status_code=422)
    try:
        await service.create_warehouse(session, data)
    except DomainError as exc:
        return await _warehouses_response(request, session, error=exc.message, status_code=exc.status_code)
    return await _warehouses_response(request, session, trigger=True)


@router.post("/warehouses/{warehouse_id}", response_class=HTMLResponse)
async def update_warehouse(
    warehouse_id: int,
    request: Request,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    name: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """HTMX twin of PUT /api/v1/warehouses/{id}."""
    if not is_valid_api_key(api_key, settings):
        return await _warehouses_response(request, session, error=BAD_KEY, status_code=401)
    data = _parse_warehouse(name, location)
    if isinstance(data, str):
        return await _warehouses_response(request, session, error=data, status_code=422)
    try:
        await service.update_warehouse(session, warehouse_id, data)
    except DomainError as exc:
        return await _warehouses_response(request, session, error=exc.message, status_code=exc.status_code)
    return await _warehouses_response(request, session, trigger=True)


@router.post("/warehouses/{warehouse_id}/delete", response_class=HTMLResponse)
async def delete_warehouse(
    warehouse_id: int,
    request: Request,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
) -> HTMLResponse:
    """HTMX twin of DELETE /api/v1/warehouses/{id}."""
    if not is_valid_api_key(api_key, settings):
        return await _warehouses_response(request, session, error=BAD_KEY, status_code=401)
    try:
        await service.delete_warehouse(session, warehouse_id)
    except DomainError as exc:
        return await _warehouses_response(request, session, error=exc.message, status_code=exc.status_code)
    return await _warehouses_response(request, session, trigger=True)
