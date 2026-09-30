from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://usage:usage@localhost:5432/usage_metering"
    stripe_secret_key: str = "sk_test_replace_me"
    stripe_webhook_secret: str = "whsec_replace_me"
    stripe_pro_price_id: str = "price_replace_me"
    stripe_success_url: str = "http://localhost:8000/health?checkout=success&session_id={CHECKOUT_SESSION_ID}"
    stripe_cancel_url: str = "http://localhost:8000/health?checkout=cancel"
    reconciliation_interval_seconds: int = 300
    api_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
