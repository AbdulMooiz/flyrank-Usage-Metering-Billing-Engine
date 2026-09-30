from sqlalchemy import func, select

from app.models import UsageEvent, UsageType
from tests.conftest import FREE_TENANT_ID, PRO_TENANT_ID


def test_generate_and_usage_are_tenant_scoped(client, database) -> None:
    response = client.post(
        "/generate",
        headers={"X-Tenant-ID": str(FREE_TENANT_ID), "Idempotency-Key": "api-generate"},
        json={
            "input_tokens": 100,
            "cached_input_tokens": 25,
            "output_tokens": 40,
            "reasoning_tokens": 10,
        },
    )
    assert response.status_code == 200
    assert response.json()["api_calls_added"] == 1
    assert response.json()["ai_tokens_added"] == 150

    free_usage = client.get("/usage", headers={"X-Tenant-ID": str(FREE_TENANT_ID)})
    pro_usage = client.get("/usage", headers={"X-Tenant-ID": str(PRO_TENANT_ID)})
    assert free_usage.status_code == pro_usage.status_code == 200
    assert free_usage.json()["api_calls_used"] == 1
    assert free_usage.json()["ai_tokens_used"] == 150
    assert free_usage.json()["current_plan"] == "Free"
    assert pro_usage.json()["api_calls_used"] == 0
    assert pro_usage.json()["ai_tokens_used"] == 0
    assert pro_usage.json()["current_plan"] == "Pro"


def test_validation_rejects_bad_quantities_with_422(client, database) -> None:
    for body in (
        {"input_tokens": -1},
        {"input_tokens": 3, "cached_input_tokens": 4},
        {"input_tokens": 1.5},
        {"unknown": 1},
    ):
        response = client.post(
            "/generate",
            headers={"X-Tenant-ID": str(FREE_TENANT_ID), "Idempotency-Key": "invalid"},
            json=body,
        )
        assert response.status_code == 422

    with database() as session:
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 0


def test_missing_headers_and_unknown_tenant_are_clean_4xx(client, database) -> None:
    assert client.get("/usage").status_code == 422
    response = client.get("/usage", headers={"X-Tenant-ID": "33333333-3333-4333-8333-333333333333"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tenant_not_found"


def test_quota_error_has_specific_context_and_429(client, database) -> None:
    for index in range(1_000):
        response = client.post(
            "/generate",
            headers={"X-Tenant-ID": str(FREE_TENANT_ID), "Idempotency-Key": f"quota-{index}"},
            json={},
        )
        assert response.status_code == 200

    rejected = client.post(
        "/generate",
        headers={"X-Tenant-ID": str(FREE_TENANT_ID), "Idempotency-Key": "quota-over"},
        json={},
    )
    assert rejected.status_code == 429
    assert "exceeds the 1000 limit" in rejected.json()["error"]["message"]
    assert rejected.json()["error"]["context"]["upgrade_plan"] == "Pro"
    with database() as session:
        assert session.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.usage_type == UsageType.API_CALLS)) == 1_000