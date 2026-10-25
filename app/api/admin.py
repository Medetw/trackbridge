from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Security
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import SessionDep, WorkerDep
from app.errors import DomainError
from app.schemas import ParcelCreate
from app.security import api_key_header, is_valid_api_key
from app.services import parcels as service
from app.templating import blank_to_none, templates

router = APIRouter(prefix="/admin", tags=["admin-ui"], include_in_schema=False)

BAD_KEY = "Неверный API-ключ. Откройте настройки ⚙️ и введите ключ."


@router.get("", response_class=HTMLResponse)
async def admin_page(request: Request, session: SessionDep) -> HTMLResponse:
    warehouses = await service.list_warehouses(session)
    return templates.TemplateResponse(request, "admin.html", {"warehouses": warehouses})


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
    parcels = await service.list_recent_parcels(session, query=q.strip() or None)
    return templates.TemplateResponse(request, "partials/admin_rows.html", {"parcels": parcels, "q": q.strip()})


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
