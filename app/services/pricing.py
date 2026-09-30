from dataclasses import asdict, dataclass

from app.core.pricing_config import (
    API_CALL_MICROCENTS,
    CACHED_INPUT_MICROCENTS_PER_TOKEN,
    FRESH_INPUT_MICROCENTS_PER_TOKEN,
    MICROCENTS_PER_CENT,
    OUTPUT_MICROCENTS_PER_TOKEN,
)


@dataclass(frozen=True)
class PricingBreakdown:
    api_call_cost_microcents: int
    fresh_input_cost_microcents: int
    cached_input_cost_microcents: int
    output_cost_microcents: int

    @property
    def ai_token_cost_microcents(self) -> int:
        return (
            self.fresh_input_cost_microcents
            + self.cached_input_cost_microcents
            + self.output_cost_microcents
        )

    @property
    def total_cost_microcents(self) -> int:
        return self.api_call_cost_microcents + self.ai_token_cost_microcents

    def to_dict(self) -> dict[str, int]:
        return asdict(self) | {
            "ai_token_cost_microcents": self.ai_token_cost_microcents,
            "total_cost_microcents": self.total_cost_microcents,
        }


class PricingService:
    @staticmethod
    def calculate(
        *,
        api_calls: int,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
    ) -> PricingBreakdown:
        quantities = (api_calls, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens)
        if any(quantity < 0 for quantity in quantities):
            raise ValueError("Pricing quantities cannot be negative")
        if cached_input_tokens > input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")

        fresh_input_tokens = input_tokens - cached_input_tokens
        return PricingBreakdown(
            api_call_cost_microcents=api_calls * API_CALL_MICROCENTS,
            fresh_input_cost_microcents=(
                fresh_input_tokens * FRESH_INPUT_MICROCENTS_PER_TOKEN
            ),
            cached_input_cost_microcents=(
                cached_input_tokens * CACHED_INPUT_MICROCENTS_PER_TOKEN
            ),
            output_cost_microcents=(
                (output_tokens + reasoning_tokens) * OUTPUT_MICROCENTS_PER_TOKEN
            ),
        )

    @staticmethod
    def to_cents(microcents: int) -> int:
        if microcents < 0:
            raise ValueError("Cost cannot be negative")
        return (microcents + MICROCENTS_PER_CENT // 2) // MICROCENTS_PER_CENT
