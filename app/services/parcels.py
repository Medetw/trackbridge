from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import ConflictError, NotFoundError
from app.models import Parcel, ParcelStatus, StatusHistory, Warehouse
from app.schemas import ParcelCreate, ParcelReceive, WarehouseCreate


@dataclass(frozen=True)
class StatusChangeEvent:
    """Snapshot handed to the notification dispatcher after the transaction commits."""

    tracking_code: str
    client_phone: str
    client_name: str
    old_status: ParcelStatus | None
    new_status: ParcelStatus


@dataclass(frozen=True)
class ReceiveOutcome:
    parcel: Parcel
    event: StatusChangeEvent | None


# --- Warehouses ---


async def list_warehouses(session: AsyncSession) -> list[Warehouse]:
    return list(await session.scalars(select(Warehouse).order_by(Warehouse.name)))


async def create_warehouse(session: AsyncSession, data: WarehouseCreate) -> Warehouse:
    warehouse = Warehouse(name=data.name, location=data.location)
    session.add(warehouse)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(f"Warehouse '{data.name}' already exists") from None
    return warehouse


async def _get_warehouse(session: AsyncSession, warehouse_id: int) -> Warehouse:
    warehouse = await session.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    return warehouse


# --- Parcels ---


async def get_parcel(session: AsyncSession, tracking_code: str, *, for_update: bool = False) -> Parcel:
    stmt = (
        select(Parcel)
        .where(Parcel.tracking_code == tracking_code.strip().upper())
        # Reload server-generated columns (updated_at, history timestamps) instead of lazy-loading them later.
        .execution_options(populate_existing=True)
    )
    if for_update:
        # Row lock so concurrent scans of the same box serialize instead of double-notifying.
        stmt = stmt.with_for_update(of=Parcel)
    else:
        stmt = stmt.options(selectinload(Parcel.history))
    parcel = await session.scalar(stmt)
    if parcel is None:
        raise NotFoundError(f"Parcel with tracking code '{tracking_code}' not found")
    return parcel


async def register_parcel(session: AsyncSession, data: ParcelCreate, changed_by: str) -> Parcel:
    if data.warehouse_id is not None:
        await _get_warehouse(session, data.warehouse_id)
    parcel = Parcel(
        tracking_code=data.tracking_code,
        client_phone=data.client_phone,
        client_name=data.client_name,
        warehouse_id=data.warehouse_id,
        status=ParcelStatus.registered,
    )
    parcel.history.append(StatusHistory(old_status=None, new_status=ParcelStatus.registered.value, changed_by=changed_by))
    session.add(parcel)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(f"Parcel with tracking code '{data.tracking_code}' already exists") from None
    return await get_parcel(session, parcel.tracking_code)


def _apply_status(parcel: Parcel, new_status: ParcelStatus, changed_by: str) -> StatusChangeEvent:
    old_status = parcel.status
    if new_status.rank <= old_status.rank:
        raise ConflictError(
            f"Cannot change status of '{parcel.tracking_code}' from '{old_status.value}' to '{new_status.value}': "
            "statuses can only move forward"
        )
    parcel.status = new_status
    parcel.history.append(StatusHistory(old_status=old_status.value, new_status=new_status.value, changed_by=changed_by))
    return StatusChangeEvent(
        tracking_code=parcel.tracking_code,
        client_phone=parcel.client_phone,
        client_name=parcel.client_name,
        old_status=old_status,
        new_status=new_status,
    )


async def receive_parcel(session: AsyncSession, data: ParcelReceive, changed_by: str) -> ReceiveOutcome:
    """Mark a scanned parcel as received in China. Re-scanning a received parcel only updates measurements."""
    parcel = await get_parcel(session, data.tracking_code, for_update=True)
    if data.warehouse_id is not None:
        await _get_warehouse(session, data.warehouse_id)
        parcel.warehouse_id = data.warehouse_id
    if data.weight_kg is not None:
        parcel.weight_kg = data.weight_kg
    if data.volume_cbm is not None:
        parcel.volume_cbm = data.volume_cbm

    event: StatusChangeEvent | None = None
    if parcel.status is ParcelStatus.registered:
        await session.refresh(parcel, ["history"])
        event = _apply_status(parcel, ParcelStatus.received_at_china_wh, changed_by)
    elif parcel.status is not ParcelStatus.received_at_china_wh:
        raise ConflictError(
            f"Parcel '{parcel.tracking_code}' is already '{parcel.status.value}' and cannot be received again"
        )

    await session.commit()
    return ReceiveOutcome(parcel=await get_parcel(session, parcel.tracking_code), event=event)


async def update_status(
    session: AsyncSession, tracking_code: str, new_status: ParcelStatus, changed_by: str
) -> tuple[Parcel, StatusChangeEvent]:
    parcel = await get_parcel(session, tracking_code, for_update=True)
    await session.refresh(parcel, ["history"])
    event = _apply_status(parcel, new_status, changed_by)
    await session.commit()
    return await get_parcel(session, parcel.tracking_code), event


async def list_parcels_by_phone(session: AsyncSession, phone: str, *, active_only: bool = True) -> list[Parcel]:
    stmt = select(Parcel).where(Parcel.client_phone == phone).order_by(Parcel.created_at.desc())
    if active_only:
        stmt = stmt.where(Parcel.status != ParcelStatus.delivered)
    return list(await session.scalars(stmt))


async def list_recent_parcels(session: AsyncSession, *, query: str | None = None, limit: int = 50) -> list[Parcel]:
    stmt = select(Parcel).order_by(Parcel.created_at.desc(), Parcel.id.desc()).limit(limit)
    if query:
        stmt = stmt.where(
            or_(
                Parcel.tracking_code.icontains(query, autoescape=True),
                Parcel.client_name.icontains(query, autoescape=True),
                Parcel.client_phone.icontains(query, autoescape=True),
            )
        )
    return list(await session.scalars(stmt))
