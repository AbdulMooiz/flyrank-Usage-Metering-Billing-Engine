from app.core.errors import QuotaExceeded
from app.models import Plan


class QuotaService:
    @staticmethod
    def ensure_allowed(
        *,
        plan: Plan,
        api_calls_used: int,
        ai_tokens_used: int,
        api_calls_requested: int,
        ai_tokens_requested: int,
    ) -> None:
        checks = (
            ("api_calls", api_calls_used, api_calls_requested, plan.api_call_limit),
            ("ai_tokens", ai_tokens_used, ai_tokens_requested, plan.ai_token_limit),
        )
        for usage_type, used, requested, limit in checks:
            if used + requested > limit:
                raise QuotaExceeded(
                    f"{usage_type} quota exceeded: {used} used + {requested} requested exceeds the {limit} limit",
                    {
                        "usage_type": usage_type,
                        "used": used,
                        "requested": requested,
                        "limit": limit,
                        "upgrade_plan": "Pro" if plan.name == "Free" else None,
                    },
                )
