import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import IdempotencyConflict, PaymentRequired, TenantNotFound
from app.core.pricing_config import API_CALL_MICROCENTS
from app.models import MeteringRequest, Tenant, UsageType
from app.repositories.metering_repository import MeteringRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.tenant_repository import TenantRepository
from app.schemas.usage import GenerateRequest, GenerateResponse
from app.services.pricing import PricingService
from app.services.quota import QuotaService


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = now.astimezone(UTC)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class MeteringService:
    @staticmethod
    def record_generate(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        idempotency_key: str,
        request: GenerateRequest,
        now: datetime | None = None,
    ) -> GenerateResponse:
        now = now or datetime.now(UTC)
        payload = request.model_dump(mode="json")
        request_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        with session.begin():
            tenant = TenantRepository.get_for_update(session, tenant_id)
            if tenant is None:
                raise TenantNotFound("The requested tenant does not exist")

            previous = MeteringRepository.get_request(session, tenant_id, idempotency_key)
            if previous is not None:
                if previous.request_hash != request_hash:
                    raise IdempotencyConflict(
                        "This Idempotency-Key was already used with a different request body"
                    )
                if previous.response_data is None:
                    raise IdempotencyConflict("The original idempotent result is unavailable")
                return GenerateResponse.model_validate(previous.response_data)

            subscription_and_plan = SubscriptionRepository.get_with_plan(session, tenant_id)
            if subscription_and_plan is None:
                raise PaymentRequired("The tenant has no active plan; subscribe to continue")
            subscription, plan = subscription_and_plan
            if subscription.status not in {"active", "trialing"} and not (
                plan.name == "Free" and subscription.status == "canceled"
            ):
                raise PaymentRequired(
                    "The subscription is not active; update payment or choose an available plan",
                    {"subscription_status": subscription.status},
                )

            period_start, period_end = month_bounds(now)
            totals = MeteringRepository.monthly_totals(
                session, tenant_id, period_start, period_end
            )
            api_calls_used = totals.get(UsageType.API_CALLS, 0)
            ai_tokens_used = totals.get(UsageType.AI_TOKENS, 0)
            QuotaService.ensure_allowed(
                plan=plan,
                api_calls_used=api_calls_used,
                ai_tokens_used=ai_tokens_used,
                api_calls_requested=1,
                ai_tokens_requested=request.ai_token_quantity,
            )

            pricing = PricingService.calculate(
                api_calls=1,
                input_tokens=request.input_tokens,
                cached_input_tokens=request.cached_input_tokens,
                output_tokens=request.output_tokens,
                reasoning_tokens=request.reasoning_tokens,
            )
            metering_request = MeteringRequest(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            session.add(metering_request)
            session.flush()

            MeteringRepository.add_event(
                session,
                tenant_id=tenant_id,
                request_id=metering_request.id,
                usage_type=UsageType.API_CALLS,
                quantity=1,
                idempotency_key=f"{idempotency_key}:api_calls",
                cost_microcents=API_CALL_MICROCENTS,
                details={"unit_rate_microcents": API_CALL_MICROCENTS},
            )
            if request.ai_token_quantity:
                breakdown = pricing.to_dict()
                MeteringRepository.add_event(
                    session,
                    tenant_id=tenant_id,
                    request_id=metering_request.id,
                    usage_type=UsageType.AI_TOKENS,
                    quantity=request.ai_token_quantity,
                    idempotency_key=f"{idempotency_key}:ai_tokens",
                    cost_microcents=pricing.ai_token_cost_microcents,
                    details={
                        "input_tokens": request.input_tokens,
                        "cached_input_tokens": request.cached_input_tokens,
                        "output_tokens": request.output_tokens,
                        "reasoning_tokens": request.reasoning_tokens,
                        "pricing": breakdown,
                    },
                )

            response = GenerateResponse(
                request_id=metering_request.id,
                tenant_id=tenant_id,
                api_calls_added=1,
                ai_tokens_added=request.ai_token_quantity,
                total_cost_microcents=pricing.total_cost_microcents,
            )
            metering_request.response_data = response.model_dump(mode="json")
            return response
