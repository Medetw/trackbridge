from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.models import ParcelStatus
from app.phone import normalize_phone

TrackingCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9\-_]+$"),
]
Phone = Annotated[str, AfterValidator(normalize_phone)]
WeightKg = Annotated[float, Field(gt=0, le=10_000, description="Weight in kilograms")]
VolumeCbm = Annotated[float, Field(gt=0, le=1_000, description="Volume in cubic meters")]


# --- Warehouses ---


class WarehouseCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str


# --- Parcels ---


class ParcelCreate(BaseModel):
    tracking_code: TrackingCode
    client_phone: Phone
    client_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    warehouse_id: int | None = None


class ParcelReceive(BaseModel):
    tracking_code: TrackingCode
    weight_kg: WeightKg | None = None
    volume_cbm: VolumeCbm | None = None
    warehouse_id: int | None = None


class StatusUpdate(BaseModel):
    status: ParcelStatus


class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    old_status: str | None
    new_status: str
    changed_by: str
    timestamp: datetime


class ParcelOut(BaseModel):
    """Internal view (API-key protected): includes client PII and audit details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    client_phone: str
    client_name: str
    weight_kg: float | None
    volume_cbm: float | None
    status: ParcelStatus
    warehouse: WarehouseOut | None
    created_at: datetime
    updated_at: datetime


class ParcelDetailOut(ParcelOut):
    history: list[StatusHistoryOut]


class ReceiveResult(BaseModel):
    parcel: ParcelOut
    status_changed: bool = Field(description="False when the parcel was already received (re-scan only updated measurements)")


class TrackingEvent(BaseModel):
    status: str
    timestamp: datetime


class TrackingOut(BaseModel):
    """Public view: no phone, name or worker IDs."""

    tracking_code: str
    status: ParcelStatus
    weight_kg: float | None
    volume_cbm: float | None
    warehouse: str | None
    updated_at: datetime
    history: list[TrackingEvent]


class ErrorOut(BaseModel):
    detail: str
    code: str
