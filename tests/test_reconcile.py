import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.jobs import reconcile
from app.models import MeteringRequest, UsageEvent, UsageType
from tests.conftest import FREE_TENANT_ID


def test_clean_seed_state_has_no_reconciliation_anomalies(database) -> None:
    report = reconcile.reconcile_once(
        database,
        now=datetime(2026, 9, 30, 12, tzinfo=UTC),
    )

    assert report.subscriptions_checked == 2
    assert report.anomalies == ()


def test_reconciliation_reports_usage_above_plan_limit(database) -> None:
    request_id = uuid.uuid4()
    with database.begin() as session:
        session.add(
            MeteringRequest(
                id=request_id,
                tenant_id=FREE_TENANT_ID,
                idempotency_key="reconcile-over-limit",
                request_hash=hashlib.sha256(b"reconcile-over-limit").hexdigest(),
                response_data={},
            )
        )
        session.flush()
        session.add(
            UsageEvent(
                tenant_id=FREE_TENANT_ID,
                request_id=request_id,
                usage_type=UsageType.API_CALLS,
                quantity=1_001,
                idempotency_key="reconcile-over-limit:api_calls",
                cost_microcents=0,
                details={},
                timestamp=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )

    report = reconcile.reconcile_once(
        database,
        now=datetime(2026, 9, 30, 12, tzinfo=UTC),
    )

    assert {
        "tenant_id": str(FREE_TENANT_ID),
        "kind": "monthly_limit_exceeded",
        "usage_type": "api_calls",
        "used": 1_001,
        "limit": 1_000,
    } in report.anomalies


def test_worker_retries_transient_database_failures_with_exponential_backoff(
    database, monkeypatch
) -> None:
    attempts = 0
    delays: list[float] = []
    report = reconcile.reconcile_once(database)

    def intermittent_failure(_session_factory):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("database unavailable", {}, RuntimeError("offline"))
        return report

    monkeypatch.setattr(reconcile, "reconcile_once", intermittent_failure)
    result = reconcile.run_with_retries(
        database,
        max_attempts=3,
        base_delay_seconds=0.25,
        sleep=delays.append,
    )

    assert result == report
    assert attempts == 3
    assert delays == [0.25, 0.5]


def test_worker_logs_and_raises_after_retry_exhaustion(database, monkeypatch, caplog) -> None:
    def unavailable(_session_factory):
        raise OperationalError("database unavailable", {}, RuntimeError("offline"))

    monkeypatch.setattr(reconcile, "reconcile_once", unavailable)

    with pytest.raises(OperationalError):
        reconcile.run_with_retries(
            database,
            max_attempts=2,
            base_delay_seconds=0,
            sleep=lambda _delay: None,
        )

    assert "Billing reconciliation exhausted retries" in caplog.text