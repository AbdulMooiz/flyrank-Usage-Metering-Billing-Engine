import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BillingError, PaymentRequired, TenantNotFound
from app.integrations.stripe_adapter import StripeAdapter
from app.models import Plan, StripeEvent, Subscription, Tenant
from app.repositories.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class MalformedStripeEvent(BillingError):
    status_code = 400
    code = "malformed_stripe_event"


class CheckoutConflict(BillingError):
    status_code = 409
    code = "checkout_conflict"


class StripeBillingService:
    @staticmethod
    def create_checkout(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        stripe: StripeAdapter | None = None,
    ) -> dict[str, Any]:
        with session.begin():
            tenant = TenantRepository.get_for_update(session, tenant_id)
            if tenant is None:
                raise TenantNotFound("The requested tenant does not exist")
            subscription = session.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant_id)
            )
            if subscription is None:
                raise PaymentRequired("The tenant has no subscription record")
            pro_plan = session.scalar(select(Plan).where(Plan.name == "Pro"))
            if pro_plan is None:
                raise PaymentRequired("The Pro plan is not configured")
            if subscription.plan_id == pro_plan.id and subscription.status not in {
                "canceled",
                "incomplete_expired",
            }:
                raise CheckoutConflict("The tenant already has a Stripe Pro subscription")
            customer_id = subscription.stripe_customer_id

        adapter = stripe or StripeAdapter()
        return adapter.create_checkout_session(
            tenant_id=str(tenant_id), customer_id=customer_id
        )

    @staticmethod
    def process_event(session: Session, event: dict[str, Any]) -> bool:
        if not isinstance(event, dict):
            raise MalformedStripeEvent("Stripe event must be a JSON object")
        event_id = event.get("id")
        event_type = event.get("type")
        event_data = event.get("data")
        if not isinstance(event_id, str) or not isinstance(event_type, str):
            raise MalformedStripeEvent("Stripe event must contain an id and type")
        if not isinstance(event_data, dict) or not isinstance(event_data.get("object"), dict):
            raise MalformedStripeEvent("Stripe event data.object is missing or malformed")

        try:
            with session.begin():
                existing = session.scalar(
                    select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)
                )
                if existing is not None:
                    return False
                session.add(StripeEvent(stripe_event_id=event_id, event_type=event_type))
                session.flush()
                StripeBillingService._apply_event(
                    session,
                    event_type=event_type,
                    event_object=event_data["object"],
                )
            return True
        except IntegrityError:
            session.rollback()
            duplicate = session.scalar(
                select(StripeEvent.id).where(StripeEvent.stripe_event_id == event_id)
            )
            if duplicate is not None:
                return False
            raise

    @staticmethod
    def _apply_event(
        session: Session, *, event_type: str, event_object: dict[str, Any]
    ) -> None:
        if event_type == "checkout.session.completed":
            StripeBillingService._apply_checkout_completed(session, event_object)
        elif event_type in {
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            StripeBillingService._apply_subscription_event(
                session, event_type=event_type, event_object=event_object
            )

    @staticmethod
    def _apply_checkout_completed(session: Session, checkout: dict[str, Any]) -> None:
        if checkout.get("mode") != "subscription":
            return
        metadata = checkout.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        tenant_value = checkout.get("client_reference_id") or metadata.get("tenant_id")
        subscription_id = checkout.get("subscription")
        customer_id = checkout.get("customer")
        if not isinstance(tenant_value, str) or not isinstance(subscription_id, str) or not isinstance(customer_id, str):
            raise MalformedStripeEvent("Completed subscription Checkout is missing tenant, customer, or subscription identity")
        try:
            tenant_id = uuid.UUID(tenant_value)
        except ValueError as error:
            raise MalformedStripeEvent("Checkout contains an invalid tenant reference") from error

        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            logger.warning("Ignoring verified Checkout event for an unknown local tenant")
            return
        subscription = session.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant_id).with_for_update()
        )
        pro_plan = session.scalar(select(Plan).where(Plan.name == "Pro"))
        if subscription is None or pro_plan is None:
            logger.warning("Ignoring verified Checkout event without a local subscription or Pro plan")
            return
        customer_owner = session.scalar(
            select(Subscription.tenant_id).where(
                Subscription.stripe_customer_id == customer_id,
                Subscription.tenant_id != tenant_id,
            )
        )
        if customer_owner is not None:
            logger.error("Ignoring Checkout event whose Stripe customer is linked to another tenant")
            return
        subscription_owner = session.scalar(
            select(Subscription.tenant_id).where(
                Subscription.stripe_subscription_id == subscription_id,
                Subscription.tenant_id != tenant_id,
            )
        )
        if subscription_owner is not None:
            logger.error("Ignoring Checkout event whose Stripe subscription is linked to another tenant")
            return
        subscription.plan_id = pro_plan.id
        subscription.status = "active"
        subscription.stripe_customer_id = customer_id
        subscription.stripe_subscription_id = subscription_id

    @staticmethod
    def _apply_subscription_event(
        session: Session, *, event_type: str, event_object: dict[str, Any]
    ) -> None:
        subscription_id = event_object.get("id")
        customer_id = event_object.get("customer")
        if not isinstance(subscription_id, str) or not isinstance(customer_id, str):
            raise MalformedStripeEvent("Subscription event is missing subscription or customer identity")

        subscription = session.scalar(
            select(Subscription)
            .where(Subscription.stripe_subscription_id == subscription_id)
            .with_for_update()
        )
        if subscription is None:
            logger.info("Ignoring verified subscription event for an unknown Stripe customer")
            return
        if subscription.stripe_customer_id not in (None, customer_id):
            logger.error("Ignoring Stripe subscription event with a mismatched customer")
            return
        metadata = event_object.get("metadata") or {}
        tenant_reference = metadata.get("tenant_id") if isinstance(metadata, dict) else None
        if tenant_reference and tenant_reference != str(subscription.tenant_id):
            logger.error("Ignoring Stripe subscription event with a mismatched tenant reference")
            return

        free_plan = session.scalar(select(Plan).where(Plan.name == "Free"))
        pro_plan = session.scalar(select(Plan).where(Plan.name == "Pro"))
        if free_plan is None or pro_plan is None:
            raise MalformedStripeEvent("Subscription plans are not seeded")
        if event_type == "customer.subscription.deleted":
            subscription.plan_id = free_plan.id
            subscription.status = "canceled"
        else:
            status = event_object.get("status")
            supported_statuses = {
                "active",
                "trialing",
                "past_due",
                "canceled",
                "unpaid",
                "incomplete",
                "incomplete_expired",
                "paused",
            }
            if status not in supported_statuses:
                raise MalformedStripeEvent("Subscription update has a missing or unsupported status")
            subscription.status = status
            subscription.plan_id = pro_plan.id
        subscription.stripe_customer_id = customer_id
        subscription.stripe_subscription_id = subscription_id
        for field in ("current_period_start", "current_period_end"):
            value = event_object.get(field)
            if isinstance(value, int):
                setattr(subscription, field, datetime.fromtimestamp(value, tz=UTC))
