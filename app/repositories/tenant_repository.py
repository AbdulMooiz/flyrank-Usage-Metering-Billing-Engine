import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant


class TenantRepository:
    @staticmethod
    def get_for_update(session: Session, tenant_id: uuid.UUID) -> Tenant | None:
        return session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
