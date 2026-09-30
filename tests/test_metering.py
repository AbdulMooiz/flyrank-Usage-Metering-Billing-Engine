import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import IdempotencyConflict, PaymentRequired, QuotaExceeded
from app.models import MeteringRequest, Subscription, UsageEvent, UsageType
from app.schemas.usage import GenerateRequest
from app.services.metering import MeteringService

from tests.conftest import FREE_TENANT_ID, PRO_TENANT_ID


def _request() -> GenerateRequest:
    return GenerateRequest(
        input_tokens=120,
        cached_input_tokens=20,
        output_tokens=30,
        reasoning_tokens=10,
    )


def _meter(session_factory, tenant_id: uuid.UUID, key: str, request: GenerateRequest):
    with session_factory() as session:
        return MeteringService.record_generate(
            session,
            tenant_id=tenant_id,
            idempotency_key=key,
            request=request,
            now=datetime(2026, 9, 30, 12, tzinfo=UTC),
        )


def _seed_usage(session_factory, tenant_id: uuid.UUID, usage_type: UsageType, quantity: int) -> None:
    request_id = uuid.uuid4()
    key = f"baseline-{usage_type.value}"
    payload_hash = hashlib.sha256(key.encode()).hexdigest()
    with session_factory.begin() as session:
        session.add(
            MeteringRequest(
                id=request_id,
                tenant_id=tenant_id,
                idempotency_key=key,
                request_hash=payload_hash,
                response_data={},
            )
        )
        session.flush()
        session.add(
            UsageEvent(
                tenant_id=tenant_id,
                request_id=request_id,
                usage_type=usage_type,
                quantity=quantity,
                idempotency_key=f"{key}:{usage_type.value}",
                cost_microcents=0,
                details={},
                timestamp=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )


def test_first_request_records_both_usage_types(database) -> None:
    response = _meter(database, FREE_TENANT_ID, "first", _request())

    assert response.api_calls_added == 1
    assert response.ai_tokens_added == 160
    with database() as session:
        events = session.scalars(select(UsageEvent).where(UsageEvent.request_id == response.request_id)).all()
    assert {event.usage_type: event.quantity for event in events} == {
        UsageType.API_CALLS: 1,
        UsageType.AI_TOKENS: 160,
    }


def test_same_key_and_payload_returns_original_without_duplicate_events(database) -> None:
    first = _meter(database, FREE_TENANT_ID, "same", _request())
    retry = _meter(database, FREE_TENANT_ID, "same", _request())

    assert retry == first
    with database() as session:
        assert session.scalar(select(func.count()).select_from(MeteringRequest)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 2


def test_same_key_with_different_payload_conflicts(database) -> None:
    _meter(database, FREE_TENANT_ID, "reuse", _request())
    changed = GenerateRequest(input_tokens=121, cached_input_tokens=20, output_tokens=30, reasoning_tokens=10)

    with pytest.raises(IdempotencyConflict):
        _meter(database, FREE_TENANT_ID, "reuse", changed)


def test_same_key_is_independent_between_tenants(database) -> None:
    first = _meter(database, FREE_TENANT_ID, "shared", _request())
    second = _meter(database, PRO_TENANT_ID, "shared", _request())

    assert first.tenant_id == FREE_TENANT_ID
    assert second.tenant_id == PRO_TENANT_ID
    assert first.request_id != second.request_id


def test_concurrent_duplicate_requests_create_one_logical_result(database) -> None:
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(
            executor.map(
                lambda _: _meter(database, FREE_TENANT_ID, "parallel", _request()),
                range(10),
            )
        )

    assert all(response == responses[0] for response in responses)
    with database() as session:
        assert session.scalar(select(func.count()).select_from(MeteringRequest)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 2


def test_exact_api_quota_boundary_allowed_then_next_call_rejected(database) -> None:
    _seed_usage(database, FREE_TENANT_ID, UsageType.API_CALLS, 999)

    allowed = _meter(database, FREE_TENANT_ID, "boundary", GenerateRequest())
    assert allowed.api_calls_added == 1
    with pytest.raises(QuotaExceeded, match="exceeds the 1000 limit"):
        _meter(database, FREE_TENANT_ID, "over", GenerateRequest())

    with database() as session:
        assert session.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.usage_type == UsageType.API_CALLS)) == 2
        assert session.scalar(select(func.count()).select_from(MeteringRequest)) == 2


def test_exact_ai_token_boundary_allowed_and_over_limit_rejected(database) -> None:
    _seed_usage(database, FREE_TENANT_ID, UsageType.AI_TOKENS, 99_999)

    allowed = _meter(database, FREE_TENANT_ID, "last-token", GenerateRequest(input_tokens=1))
    assert allowed.ai_tokens_added == 1
    with pytest.raises(QuotaExceeded, match="exceeds the 100000 limit"):
        _meter(database, FREE_TENANT_ID, "too-many", GenerateRequest(input_tokens=2))


def test_large_request_is_rejected_without_partial_writes(database) -> None:
    with pytest.raises(QuotaExceeded):
        _meter(database, FREE_TENANT_ID, "large", GenerateRequest(input_tokens=100_001))

    with database() as session:
        assert session.scalar(select(func.count()).select_from(MeteringRequest)) == 0
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 0


def test_inactive_subscription_requires_payment(database) -> None:
    with database.begin() as session:
        subscription = session.scalar(
            select(Subscription).where(Subscription.tenant_id == FREE_TENANT_ID)
        )
        subscription.status = "past_due"

    with pytest.raises(PaymentRequired) as error:
        _meter(database, FREE_TENANT_ID, "blocked", GenerateRequest())
    assert getattr(error.value, "status_code", None) == 402


def test_database_rejects_nonpositive_usage_quantity(database) -> None:
    request_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        with database.begin() as session:
            session.add(
                MeteringRequest(
                    id=request_id,
                    tenant_id=FREE_TENANT_ID,
                    idempotency_key="invalid-quantity",
                    request_hash="0" * 64,
                    response_data={},
                )
            )
            session.flush()
            session.add(
                UsageEvent(
                    tenant_id=FREE_TENANT_ID,
                    request_id=request_id,
                    usage_type=UsageType.API_CALLS,
                    quantity=0,
                    idempotency_key="invalid-quantity:api_calls",
                    cost_microcents=0,
                    details={},
                )
            )
            session.flush()


def test_usage_event_cannot_reference_another_tenants_request(database) -> None:
    request_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        with database.begin() as session:
            session.add(
                MeteringRequest(
                    id=request_id,
                    tenant_id=FREE_TENANT_ID,
                    idempotency_key="tenant-fk",
                    request_hash="1" * 64,
                    response_data={},
                )
            )
            session.flush()
            session.add(
                UsageEvent(
                    tenant_id=PRO_TENANT_ID,
                    request_id=request_id,
                    usage_type=UsageType.API_CALLS,
                    quantity=1,
                    idempotency_key="tenant-fk:api_calls",
                    cost_microcents=0,
                    details={},
                )
            )
            session.flush()
