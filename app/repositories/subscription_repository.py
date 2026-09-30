import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Plan, Subscription


class SubscriptionRepository:
    @staticmethod
    def get_with_plan(session: Session, tenant_id: uuid.UUID) -> tuple[Subscription, Plan] | None:
        row = session.execute(
            select(Subscription, Plan)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(Subscription.tenant_id == tenant_id)
        ).one_or_none()
        return row if row is not None else None
