import json
from typing import Any

import stripe

from app.core.config import Settings, get_settings
from app.core.errors import BillingError


class StripeConfigurationError(BillingError):
    status_code = 503
    code = "stripe_configuration_error"


class StripeUnavailable(BillingError):
    status_code = 502
    code = "stripe_unavailable"


class StripeAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _client(self) -> stripe.StripeClient:
        if not self.settings.stripe_secret_key.startswith("sk_test_"):
            raise StripeConfigurationError("Stripe test-mode credentials are not configured")
        return stripe.StripeClient(self.settings.stripe_secret_key)

    def create_checkout_session(self, *, tenant_id: str, customer_id: str | None) -> dict[str, Any]:
        if not self.settings.stripe_pro_price_id.startswith("price_"):
            raise StripeConfigurationError("A Stripe test-mode Pro Price ID is not configured")
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": self.settings.stripe_pro_price_id, "quantity": 1}],
            "success_url": self.settings.stripe_success_url,
            "cancel_url": self.settings.stripe_cancel_url,
            "client_reference_id": tenant_id,
            "metadata": {"tenant_id": tenant_id, "plan_name": "Pro"},
            "subscription_data": {"metadata": {"tenant_id": tenant_id, "plan_name": "Pro"}},
        }
        if customer_id:
            params["customer"] = customer_id
        try:
            checkout = self._client().v1.checkout.sessions.create(params)
        except stripe.StripeError as error:
            raise StripeUnavailable("Stripe could not create a Checkout session") from error
        return {"id": checkout.id, "url": checkout.url}

    def construct_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        if not signature:
            raise ValueError("Missing Stripe-Signature header")
        if not self.settings.stripe_webhook_secret.startswith("whsec_"):
            raise StripeConfigurationError("Stripe webhook verification is not configured")
        try:
            event_data = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid Stripe webhook JSON payload") from error
        if not isinstance(event_data, dict):
            raise ValueError("Stripe webhook payload must be a JSON object")
        try:
            stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature,
                secret=self.settings.stripe_webhook_secret,
            )
        except (ValueError, stripe.SignatureVerificationError) as error:
            raise ValueError("Invalid Stripe webhook signature or payload") from error
        return event_data
