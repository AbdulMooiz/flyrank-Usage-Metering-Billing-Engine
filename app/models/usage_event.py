import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import UsageType


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["metering_requests.tenant_id", "metering_requests.id"],
            name="fk_usage_events_request_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_usage_events_quantity_positive"),
        CheckConstraint("cost_microcents >= 0", name="ck_usage_events_cost_nonnegative"),
        Index("ix_usage_events_tenant_timestamp_type", "tenant_id", "timestamp", "usage_type"),
        Index("uq_usage_events_tenant_idempotency_key", "tenant_id", "idempotency_key", unique=True),
        Index("uq_usage_events_request_type", "request_id", "usage_type", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    usage_type: Mapped[UsageType] = mapped_column(
        Enum(UsageType, name="usage_type", values_callable=lambda values: [item.value for item in values]),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    cost_microcents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
