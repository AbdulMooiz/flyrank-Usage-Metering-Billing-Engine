from enum import Enum


class PlanName(str, Enum):
    FREE = "Free"
    PRO = "Pro"


class UsageType(str, Enum):
    API_CALLS = "api_calls"
    AI_TOKENS = "ai_tokens"
