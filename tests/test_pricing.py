import pytest

from app.services.pricing import PricingService


def test_cached_input_and_reasoning_pricing_have_exact_integer_total() -> None:
    breakdown = PricingService.calculate(
        api_calls=1,
        input_tokens=1_000,
        cached_input_tokens=400,
        output_tokens=100,
        reasoning_tokens=50,
    )

    assert breakdown.fresh_input_cost_microcents == 180_000
    assert breakdown.cached_input_cost_microcents == 12_000
    assert breakdown.output_cost_microcents == 225_000
    assert breakdown.api_call_cost_microcents == 1_000
    assert breakdown.total_cost_microcents == 418_000
    assert PricingService.to_cents(breakdown.total_cost_microcents) == 0


def test_monthly_cost_rounds_half_up_using_integer_arithmetic() -> None:
    assert PricingService.to_cents(1_499_999) == 1
    assert PricingService.to_cents(1_500_000) == 2


@pytest.mark.parametrize(
    "values",
    [
        {"api_calls": -1, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
        {"api_calls": 1, "input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 0, "reasoning_tokens": 0},
    ],
)
def test_pricing_rejects_invalid_quantities(values: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        PricingService.calculate(**values)
