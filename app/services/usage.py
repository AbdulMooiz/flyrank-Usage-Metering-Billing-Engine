import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import PaymentRequired, TenantNotFound
from app.models import Tenant, UsageType
from app.repositories.metering_repository import MeteringRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.schemas.usage import UsageResponse
from app.services.metering import month_bounds
from app.services.pricing import PricingService


class UsageService:
    @staticmethod
    def get_monthly_usage(
        session: Session, tenant_id: uuid.UUID, now: datetime | None = None
    ) -> UsageResponse:
        now = now or datetime.now(UTC)
        period_start, period_end = month_bounds(now)
        with session.begin():
            if session.get(Tenant, tenant_id) is None:
                raise TenantNotFound("The requested tenant does not exist")
            subscription_and_plan = SubscriptionRepository.get_with_plan(session, tenant_id)
            if subscription_and_plan is None:
                raise PaymentRequired("The tenant has no subscription plan")
            subscription, plan = subscription_and_plan
            totals = MeteringRepository.monthly_totals(
                session, tenant_id, period_start, period_end
            )
            cost_microcents = MeteringRepository.monthly_cost_microcents(
                session, tenant_id, period_start, period_end
            )
            return UsageResponse(
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
                current_plan=plan.name,
                subscription_status=subscription.status,
                api_calls_used=totals.get(UsageType.API_CALLS, 0),
                api_call_limit=plan.api_call_limit,
                ai_tokens_used=totals.get(UsageType.AI_TOKENS, 0),
                ai_token_limit=plan.ai_token_limit,
                monthly_cost_cents=PricingService.to_cents(cost_microcents),
            )
