from pydantic import BaseModel, HttpUrl


class CheckoutResponse(BaseModel):
    session_id: str
    checkout_url: HttpUrl


class WebhookResponse(BaseModel):
    received: bool = True
    duplicate: bool
