import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import MeteringRequest, Subscription, UsageEvent, UsageType
from app.repositories.metering_repository import MeteringRepository
from app.services.metering import month_bounds

logger = logging.getLogger("app.jobs.reconcile")


@dataclass(frozen=True)
class ReconciliationReport:
    subscriptions_checked: int
    anomalies: tuple[dict[str, Any], ...]


def reconcile_once(
    session_factory: sessionmaker[Session] = SessionLocal,
    *,
    now: datetime | None = None,
) -> ReconciliationReport:
    now = now or datetime.now(UTC)
    period_start, period_end = month_bounds(now)
    anomalies: list[dict[str, Any]] = []

    with session_factory() as session:
        subscriptions = session.execute(
            select(Subscription).order_by(Subscription.tenant_id)
        ).scalars()
        checked = 0
        for subscription in subscriptions:
            checked += 1
            plan = subscription.plan
            totals = MeteringRepository.monthly_totals(
                session, subscription.tenant_id, period_start, period_end
            )
            for usage_type, used, limit in (
                ("api_calls", totals.get(UsageType.API_CALLS, 0), plan.api_call_limit),
                ("ai_tokens", totals.get(UsageType.AI_TOKENS, 0), plan.ai_token_limit),
            ):
                if used > limit:
                    anomalies.append(
                        {
                            "tenant_id": str(subscription.tenant_id),
                            "kind": "monthly_limit_exceeded",
                            "usage_type": usage_type,
                            "used": used,
                            "limit": limit,
                        }
                    )
            if bool(subscription.stripe_customer_id) != bool(subscription.stripe_subscription_id):
                anomalies.append(
                    {
                        "tenant_id": str(subscription.tenant_id),
                        "kind": "partial_stripe_mapping",
                    }
                )

        mismatched_request_count = session.scalar(
            select(func.count())
            .select_from(UsageEvent)
            .join(
                MeteringRequest,
                MeteringRequest.id == UsageEvent.request_id,
            )
            .where(UsageEvent.tenant_id != MeteringRequest.tenant_id)
        )
        if mismatched_request_count:
            anomalies.append(
                {
                    "kind": "cross_tenant_usage_request_reference",
                    "count": int(mismatched_request_count),
                }
            )

    if anomalies:
        logger.warning(
            "Billing reconciliation found inconsistent state",
            extra={"anomalies": anomalies},
        )
    else:
        logger.info("Billing reconciliation passed", extra={"subscriptions_checked": checked})
    return ReconciliationReport(checked, tuple(anomalies))


def run_with_retries(
    session_factory: sessionmaker[Session] = SessionLocal,
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    sleep=time.sleep,
) -> ReconciliationReport:
    for attempt in range(1, max_attempts + 1):
        try:
            return reconcile_once(session_factory)
        except OperationalError as error:
            if attempt == max_attempts:
                logger.error(
                    "Billing reconciliation exhausted retries",
                    extra={"attempt": attempt, "error_type": type(error).__name__},
                )
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Billing reconciliation database failure; retrying",
                extra={
                    "attempt": attempt,
                    "retry_in_seconds": delay,
                    "error_type": type(error).__name__,
                },
            )
            sleep(delay)
    raise RuntimeError("Reconciliation retry loop exited unexpectedly")


def run_forever() -> None:
    interval = max(1, get_settings().reconciliation_interval_seconds)
    while True:
        try:
            run_with_retries()
        except Exception as error:
            logger.error(
                "Billing reconciliation cycle failed",
                extra={"error_type": type(error).__name__},
            )
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
