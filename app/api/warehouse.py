from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Security
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import DispatcherDep, SessionDep, WorkerDep
from app.errors import DomainError
from app.notifications.messages import STATUS_LABELS_RU
from app.schemas import ParcelReceive
from app.security import api_key_header, is_valid_api_key
from app.services import parcels as service

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
templates.env.globals["status_labels"] = STATUS_LABELS_RU

router = APIRouter(prefix="/warehouse", tags=["warehouse-ui"], include_in_schema=False)


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


@router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request, session: SessionDep) -> HTMLResponse:
    warehouses = await service.list_warehouses(session)
    return templates.TemplateResponse(request, "scan.html", {"warehouses": warehouses})


@router.post("/scan", response_class=HTMLResponse)
async def scan_submit(
    request: Request,
    session: SessionDep,
    worker: WorkerDep,
    dispatcher: DispatcherDep,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[str | None, Security(api_key_header)],
    tracking_code: Annotated[str, Form()] = "",
    weight_kg: Annotated[str | None, Form()] = None,
    volume_cbm: Annotated[str | None, Form()] = None,
    warehouse_id: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    """HTMX twin of POST /api/v1/parcels/receive: same service call, renders a result card instead of JSON."""

    def error(message: str, status_code: int) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "partials/scan_result.html", {"error": message, "code": tracking_code}, status_code=status_code
        )

    if not is_valid_api_key(api_key, settings):
        return error("Неверный API-ключ. Откройте настройки ⚙️ и введите ключ.", 401)
    try:
        data = ParcelReceive(
            tracking_code=tracking_code,
            weight_kg=_blank_to_none(weight_kg),  # type: ignore[arg-type]
            volume_cbm=_blank_to_none(volume_cbm),  # type: ignore[arg-type]
            warehouse_id=_blank_to_none(warehouse_id),  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        fields = ", ".join(str(e["loc"][0]) for e in exc.errors())
        return error(f"Проверьте поля: {fields}", 422)
    try:
        outcome = await service.receive_parcel(session, data, worker)
    except DomainError as exc:
        return error(exc.message, exc.status_code)
    if outcome.event:
        background.add_task(dispatcher.dispatch, outcome.event)
    return templates.TemplateResponse(
        request,
        "partials/scan_result.html",
        {"parcel": outcome.parcel, "status_changed": outcome.event is not None},
    )
