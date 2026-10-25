import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ParcelStatus(str, enum.Enum):
    """Lifecycle order matters: parcels may only move forward through this list."""

    registered = "registered"
    received_at_china_wh = "received_at_china_wh"
    in_transit = "in_transit"
    customs = "customs"
    ready_in_kz = "ready_in_kz"
    delivered = "delivered"

    @property
    def rank(self) -> int:
        return list(ParcelStatus).index(self)

    @property
    def next(self) -> "ParcelStatus | None":
        statuses = list(ParcelStatus)
        return statuses[self.rank + 1] if self.rank + 1 < len(statuses) else None


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    location: Mapped[str] = mapped_column(String(300), default="")


class Parcel(Base):
    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_code: Mapped[str] = mapped_column(String(64), unique=True)
    client_phone: Mapped[str] = mapped_column(String(20), index=True)
    client_name: Mapped[str] = mapped_column(String(200))
    weight_kg: Mapped[float | None] = mapped_column(Float)
    volume_cbm: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ParcelStatus] = mapped_column(
        Enum(ParcelStatus, name="parcel_status"),
        default=ParcelStatus.registered,
        index=True,
    )
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    warehouse: Mapped[Warehouse | None] = relationship(lazy="joined")
    history: Mapped[list["StatusHistory"]] = relationship(
        back_populates="parcel",
        order_by="StatusHistory.timestamp, StatusHistory.id",
        cascade="all, delete-orphan",
    )


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id", ondelete="CASCADE"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    changed_by: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parcel: Mapped[Parcel] = relationship(back_populates="history")


class TelegramContact(Base):
    """Links a client phone number to a Telegram chat (filled when the client shares their contact with the bot)."""

    __tablename__ = "telegram_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
