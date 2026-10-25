from fastapi import APIRouter, BackgroundTasks, Depends, status

from app.deps import DispatcherDep, SessionDep, WorkerDep
from app.schemas import (
    ErrorOut,
    ParcelCreate,
    ParcelDetailOut,
    ParcelReceive,
    ReceiveResult,
    StatusUpdate,
    TrackingEvent,
    TrackingOut,
    WarehouseCreate,
    WarehouseOut,
)
from app.security import require_api_key
from app.services import parcels as service

ERRORS = {401: {"model": ErrorOut}, 404: {"model": ErrorOut}, 409: {"model": ErrorOut}}

public = APIRouter(prefix="/api/v1", tags=["public"])
protected = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)], responses=ERRORS)


@public.get("/parcels/track/{tracking_code}", response_model=TrackingOut, responses={404: {"model": ErrorOut}})
async def track_parcel(tracking_code: str, session: SessionDep) -> TrackingOut:
    parcel = await service.get_parcel(session, tracking_code)
    return TrackingOut(
        tracking_code=parcel.tracking_code,
        status=parcel.status,
        weight_kg=parcel.weight_kg,
        volume_cbm=parcel.volume_cbm,
        warehouse=parcel.warehouse.name if parcel.warehouse else None,
        updated_at=parcel.updated_at,
        history=[TrackingEvent(status=h.new_status, timestamp=h.timestamp) for h in parcel.history],
    )


@protected.post("/parcels/receive", response_model=ReceiveResult, tags=["warehouse"])
async def receive_parcel(
    data: ParcelReceive, session: SessionDep, worker: WorkerDep, dispatcher: DispatcherDep, background: BackgroundTasks
) -> ReceiveResult:
    outcome = await service.receive_parcel(session, data, worker)
    if outcome.event:
        background.add_task(dispatcher.dispatch, outcome.event)
    return ReceiveResult(parcel=outcome.parcel, status_changed=outcome.event is not None)  # type: ignore[arg-type]


@protected.post("/parcels", response_model=ParcelDetailOut, status_code=status.HTTP_201_CREATED, tags=["admin"])
async def register_parcel(data: ParcelCreate, session: SessionDep, worker: WorkerDep) -> object:
    return await service.register_parcel(session, data, worker)


@protected.get("/parcels/{tracking_code}", response_model=ParcelDetailOut, tags=["admin"])
async def get_parcel(tracking_code: str, session: SessionDep) -> object:
    return await service.get_parcel(session, tracking_code)


@protected.post("/parcels/{tracking_code}/status", response_model=ParcelDetailOut, tags=["admin"])
async def update_status(
    tracking_code: str,
    data: StatusUpdate,
    session: SessionDep,
    worker: WorkerDep,
    dispatcher: DispatcherDep,
    background: BackgroundTasks,
) -> object:
    parcel, event = await service.update_status(session, tracking_code, data.status, worker)
    background.add_task(dispatcher.dispatch, event)
    return parcel


@protected.get("/warehouses", response_model=list[WarehouseOut], tags=["admin"])
async def list_warehouses(session: SessionDep) -> object:
    return await service.list_warehouses(session)


@protected.post("/warehouses", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED, tags=["admin"])
async def create_warehouse(data: WarehouseCreate, session: SessionDep) -> object:
    return await service.create_warehouse(session, data)
