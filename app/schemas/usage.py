import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0, strict=True)
    cached_input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(default=0, ge=0, strict=True)
    reasoning_tokens: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def cached_tokens_must_be_input_tokens(self) -> "GenerateRequest":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        return self

    @property
    def ai_token_quantity(self) -> int:
        return self.input_tokens + self.output_tokens + self.reasoning_tokens


class GenerateResponse(BaseModel):
    request_id: uuid.UUID
    tenant_id: uuid.UUID
    api_calls_added: int
    ai_tokens_added: int
    total_cost_microcents: int
    currency: str = "USD"


class UsageResponse(BaseModel):
    tenant_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    current_plan: str
    subscription_status: str
    api_calls_used: int
    api_call_limit: int
    ai_tokens_used: int
    ai_token_limit: int
    monthly_cost_cents: int
    currency: str = "USD"
