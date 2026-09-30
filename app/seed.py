import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Plan, Subscription, Tenant

FREE_TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PRO_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
PLAN_LIMITS = {
    "Free": (1_000, 100_000),
    "Pro": (100_000, 10_000_000),
}


def seed() -> None:
    with SessionLocal.begin() as session:
        plans: dict[str, Plan] = {}
        for name, (api_limit, token_limit) in PLAN_LIMITS.items():
            plan = session.scalar(select(Plan).where(Plan.name == name))
            if plan is None:
                plan = Plan(name=name, api_call_limit=api_limit, ai_token_limit=token_limit)
                session.add(plan)
                session.flush()
            plans[name] = plan

        tenants = (
            (FREE_TENANT_ID, "Demo Free Tenant", "Free"),
            (PRO_TENANT_ID, "Demo Pro Tenant", "Pro"),
        )
        for tenant_id, tenant_name, plan_name in tenants:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                tenant = Tenant(id=tenant_id, name=tenant_name)
                session.add(tenant)
                session.flush()

            subscription = session.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant_id)
            )
            if subscription is None:
                session.add(
                    Subscription(tenant_id=tenant_id, plan_id=plans[plan_name].id, status="active")
                )


if __name__ == "__main__":
    seed()