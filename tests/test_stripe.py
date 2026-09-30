import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.integrations.stripe_adapter import StripeAdapter, StripeConfigurationError
from app.models import Plan, StripeEvent, Subscription
from tests.conftest import FREE_TENANT_ID, PRO_TENANT_ID

WEBHOOK_SECRET = "whsec_replace_me"


def _checkout_event(event_id: str = "evt_checkout") -> dict:
    tenant_id = str(FREE_TENANT_ID)
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "client_reference_id": tenant_id,
                "customer": "cus_test_free",
                "subscription": "sub_test_free",
                "metadata": {"tenant_id": tenant_id, "plan_name": "Pro"},
            }
        },
    }


def _signed_headers(event: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, dict[str, str]]:
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signed_payload = str(timestamp).encode() + b"." + payload
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={timestamp},v1={signature}"}


def _send_event(client, event: dict, secret: str = WEBHOOK_SECRET):
    payload, headers = _signed_headers(event, secret)
    return client.post("/webhooks/stripe", content=payload, headers=headers)


def test_checkout_creation_uses_test_price_and_tenant_metadata(monkeypatch) -> None:
    captured: dict = {}

    class FakeSessions:
        def create(self, params):
            captured["params"] = params
            return SimpleNamespace(id="cs_test_123", url="https://checkout.stripe.test/session")

    class FakeStripeClient:
        def __init__(self, secret_key):
            captured["secret_key"] = secret_key
            self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=FakeSessions()))

    monkeypatch.setattr("app.integrations.stripe_adapter.stripe.StripeClient", FakeStripeClient)
    adapter = StripeAdapter(
        Settings(
            stripe_secret_key="sk_test_capstone",
            stripe_pro_price_id="price_test_pro",
            stripe_success_url="https://example.test/complete?session_id={CHECKOUT_SESSION_ID}",
            stripe_cancel_url="https://example.test/cancel",
        )
    )

    result = adapter.create_checkout_session(tenant_id=str(FREE_TENANT_ID), customer_id="cus_existing")

    assert result == {"id": "cs_test_123", "url": "https://checkout.stripe.test/session"}
    assert captured["secret_key"] == "sk_test_capstone"
    assert captured["params"]["mode"] == "subscription"
    assert captured["params"]["line_items"] == [{"price": "price_test_pro", "quantity": 1}]
    assert captured["params"]["customer"] == "cus_existing"
    assert captured["params"]["client_reference_id"] == str(FREE_TENANT_ID)
    assert captured["params"]["subscription_data"]["metadata"]["tenant_id"] == str(FREE_TENANT_ID)


def test_live_stripe_key_is_rejected(monkeypatch) -> None:
    adapter = StripeAdapter(Settings(stripe_secret_key="sk_live_never_allowed"))

    with pytest.raises(StripeConfigurationError):
        adapter.create_checkout_session(tenant_id=str(FREE_TENANT_ID), customer_id=None)


def test_checkout_endpoint_creates_pro_session_and_rejects_duplicate_pro(client, database, monkeypatch) -> None:
    calls = []

    def fake_checkout(self, *, tenant_id: str, customer_id: str | None):
        calls.append((tenant_id, customer_id))
        return {"id": "cs_test_api", "url": "https://checkout.stripe.test/api"}

    monkeypatch.setattr(StripeAdapter, "create_checkout_session", fake_checkout)
    headers = {"X-Tenant-ID": str(FREE_TENANT_ID)}
    response = client.post("/checkout", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "session_id": "cs_test_api",
        "checkout_url": "https://checkout.stripe.test/api",
    }
    assert calls == [(str(FREE_TENANT_ID), None)]

    pro_response = client.post("/checkout", headers={"X-Tenant-ID": str(PRO_TENANT_ID)})
    assert pro_response.status_code == 409
    assert len(calls) == 1


def test_verified_checkout_upgrades_tenant_and_duplicate_is_ignored(client, database) -> None:
    event = _checkout_event()
    first = _send_event(client, event)
    repeated = _send_event(client, event)

    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    usage = client.get("/usage", headers={"X-Tenant-ID": str(FREE_TENANT_ID)})
    assert usage.json()["current_plan"] == "Pro"
    assert usage.json()["subscription_status"] == "active"
    assert usage.json()["api_call_limit"] == 100_000
    assert usage.json()["ai_token_limit"] == 10_000_000

    with database() as session:
        assert session.scalar(select(func.count()).select_from(StripeEvent)) == 1


def test_subscription_update_and_deletion_sync_plan_status_and_entitlement(client, database) -> None:
    assert _send_event(client, _checkout_event()).status_code == 200
    tenant_id = str(FREE_TENANT_ID)
    updated = {
        "id": "evt_subscription_updated",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test_free",
                "customer": "cus_test_free",
                "status": "past_due",
                "current_period_start": 1_790_000_000,
                "current_period_end": 1_792_592_000,
                "metadata": {"tenant_id": tenant_id},
            }
        },
    }
    assert _send_event(client, updated).status_code == 200
    usage = client.get("/usage", headers={"X-Tenant-ID": tenant_id})
    assert usage.json()["current_plan"] == "Pro"
    assert usage.json()["subscription_status"] == "past_due"
    blocked = client.post(
        "/generate",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "past-due"},
        json={},
    )
    assert blocked.status_code == 402

    deleted = {
        "id": "evt_subscription_deleted",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test_free",
                "customer": "cus_test_free",
                "status": "canceled",
                "metadata": {"tenant_id": tenant_id},
            }
        },
    }
    assert _send_event(client, deleted).status_code == 200
    free_usage = client.get("/usage", headers={"X-Tenant-ID": tenant_id})
    assert free_usage.json()["current_plan"] == "Free"
    assert free_usage.json()["subscription_status"] == "canceled"
    assert free_usage.json()["api_call_limit"] == 1_000
    assert client.post(
        "/generate",
        headers={"X-Tenant-ID": tenant_id, "Idempotency-Key": "free-after-cancel"},
        json={},
    ).status_code == 200

    with database() as session:
        row = session.scalar(select(Subscription).where(Subscription.tenant_id == FREE_TENANT_ID))
        assert row.stripe_subscription_id == "sub_test_free"
        assert row.current_period_start is not None
        assert row.current_period_end is not None


def test_forged_webhook_returns_400_without_state_change(client, database) -> None:
    payload, headers = _signed_headers(_checkout_event(), secret="whsec_other")

    response = client.post("/webhooks/stripe", content=payload, headers=headers)

    assert response.status_code == 400
    usage = client.get("/usage", headers={"X-Tenant-ID": str(FREE_TENANT_ID)})
    assert usage.json()["current_plan"] == "Free"
    with database() as session:
        assert session.scalar(select(func.count()).select_from(StripeEvent)) == 0


def test_unknown_subscription_event_is_recorded_without_cross_tenant_update(client, database) -> None:
    event = {
        "id": "evt_unknown_subscription",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_not_linked",
                "customer": "cus_test_free",
                "status": "active",
                "metadata": {"tenant_id": str(FREE_TENANT_ID)},
            }
        },
    }

    response = _send_event(client, event)

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    usage = client.get("/usage", headers={"X-Tenant-ID": str(FREE_TENANT_ID)})
    assert usage.json()["current_plan"] == "Free"
    with database() as session:
        row = session.scalar(select(Subscription).where(Subscription.tenant_id == FREE_TENANT_ID))
        assert row.stripe_subscription_id is None
        assert session.scalar(select(func.count()).select_from(StripeEvent)) == 1


def test_malformed_signed_event_returns_400_without_recording(client, database) -> None:
    response = _send_event(
        client,
        {"id": "evt_malformed", "type": "checkout.session.completed", "data": {}},
    )

    assert response.status_code == 400
    with database() as session:
        assert session.scalar(select(func.count()).select_from(StripeEvent)) == 0
        free_plan = session.scalar(select(Plan).where(Plan.name == "Free"))
        row = session.scalar(select(Subscription).where(Subscription.tenant_id == FREE_TENANT_ID))
        assert row.plan_id == free_plan.id


def test_signed_non_object_payload_returns_400_without_recording(client, database) -> None:
    payload, headers = _signed_headers(["not", "an", "event"])

    response = client.post("/webhooks/stripe", content=payload, headers=headers)

    assert response.status_code == 400
    with database() as session:
        assert session.scalar(select(func.count()).select_from(StripeEvent)) == 0