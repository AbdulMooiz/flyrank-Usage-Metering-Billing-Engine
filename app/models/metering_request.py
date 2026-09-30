import uuid
from typing import Any

from sqlalchemy import CHAR, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class MeteringRequest(TimestampMixin, Base):
    __tablename__ = "metering_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_metering_requests_tenant_key"),
        UniqueConstraint("tenant_id", "id", name="uq_metering_requests_tenant_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
