from typing import Any


class BillingError(Exception):
    status_code = 400
    code = "billing_error"

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class TenantNotFound(BillingError):
    status_code = 404
    code = "tenant_not_found"


class PaymentRequired(BillingError):
    status_code = 402
    code = "payment_required"


class QuotaExceeded(BillingError):
    status_code = 429
    code = "quota_exceeded"


class IdempotencyConflict(BillingError):
    status_code = 409
    code = "idempotency_conflict"
