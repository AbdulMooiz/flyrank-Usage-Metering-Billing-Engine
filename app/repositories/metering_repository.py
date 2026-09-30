import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MeteringRequest, UsageEvent, UsageType


class MeteringRepository:
    @staticmethod
    def get_request(
        session: Session, tenant_id: uuid.UUID, idempotency_key: str
    ) -> MeteringRequest | None:
        return session.scalar(
            select(MeteringRequest).where(
                MeteringRequest.tenant_id == tenant_id,
                MeteringRequest.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def monthly_totals(
        session: Session, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> dict[UsageType, int]:
        rows = session.execute(
            select(UsageEvent.usage_type, func.sum(UsageEvent.quantity))
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.timestamp >= start,
                UsageEvent.timestamp < end,
            )
            .group_by(UsageEvent.usage_type)
        )
        return {usage_type: int(total) for usage_type, total in rows}

    @staticmethod
    def monthly_cost_microcents(
        session: Session, tenant_id: uuid.UUID, start: datetime, end: datetime
    ) -> int:
        total = session.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_microcents), 0)).where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.timestamp >= start,
                UsageEvent.timestamp < end,
            )
        )
        return int(total)

    @staticmethod
    def add_event(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        request_id: uuid.UUID,
        usage_type: UsageType,
        quantity: int,
        idempotency_key: str,
        cost_microcents: int,
        details: dict[str, Any],
    ) -> UsageEvent:
        event = UsageEvent(
            tenant_id=tenant_id,
            request_id=request_id,
            usage_type=usage_type,
            quantity=quantity,
            idempotency_key=idempotency_key,
            cost_microcents=cost_microcents,
            details=details,
        )
        session.add(event)
        return event
