"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

parcel_status = sa.Enum(
    "registered", "received_at_china_wh", "in_transit", "customs", "ready_in_kz", "delivered",
    name="parcel_status",
)


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("location", sa.String(300), nullable=False),
    )
    op.create_table(
        "parcels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tracking_code", sa.String(64), nullable=False, unique=True),
        sa.Column("client_phone", sa.String(20), nullable=False),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("volume_cbm", sa.Float(), nullable=True),
        sa.Column("status", parcel_status, nullable=False),
        sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_parcels_client_phone", "parcels", ["client_phone"])
    op.create_index("ix_parcels_status", "parcels", ["status"])
    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parcel_id", sa.Integer(), sa.ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("changed_by", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_status_history_parcel_id", "status_history", ["parcel_id"])
    op.create_table(
        "telegram_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_telegram_contacts_phone", "telegram_contacts", ["phone"])


def downgrade() -> None:
    op.drop_table("telegram_contacts")
    op.drop_table("status_history")
    op.drop_table("parcels")
    op.drop_table("warehouses")
    parcel_status.drop(op.get_bind(), checkfirst=True)
