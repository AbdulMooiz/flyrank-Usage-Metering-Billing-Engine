import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.stripe_adapter import StripeAdapter
from app.schemas.stripe import CheckoutResponse, WebhookResponse
from app.schemas.usage import GenerateRequest, GenerateResponse, UsageResponse
from app.services.metering import MeteringService
from app.services.stripe_billing import StripeBillingService
from app.services.usage import UsageService

router = APIRouter()


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/generate", response_model=GenerateResponse, tags=["metering"])
def generate(
    body: GenerateRequest,
    tenant_id: Annotated[uuid.UUID, Header(alias="X-Tenant-ID")],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255, alias="Idempotency-Key")],
    session: Session = Depends(get_db),
) -> GenerateResponse:
    return MeteringService.record_generate(
        session,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        request=body,
    )


@router.get("/usage", response_model=UsageResponse, tags=["metering"])
def get_usage(
    tenant_id: Annotated[uuid.UUID, Header(alias="X-Tenant-ID")],
    session: Session = Depends(get_db),
) -> UsageResponse:
    return UsageService.get_monthly_usage(session, tenant_id)


@router.post("/checkout", response_model=CheckoutResponse, tags=["billing"])
def checkout(
    tenant_id: Annotated[uuid.UUID, Header(alias="X-Tenant-ID")],
    session: Session = Depends(get_db),
) -> CheckoutResponse:
    result = StripeBillingService.create_checkout(
        session, tenant_id=tenant_id, stripe=StripeAdapter()
    )
    return CheckoutResponse(session_id=result["id"], checkout_url=result["url"])


@router.post("/webhooks/stripe", response_model=WebhookResponse, tags=["billing"])
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
    session: Session = Depends(get_db),
) -> WebhookResponse:
    adapter = StripeAdapter()
    try:
        event = adapter.construct_event(await request.body(), stripe_signature)
        processed = StripeBillingService.process_event(session, event)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return WebhookResponse(duplicate=not processed)
