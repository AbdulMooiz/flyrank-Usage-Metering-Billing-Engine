from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("name IN ('Free', 'Pro')", name="ck_plans_supported_name"),
        CheckConstraint("api_call_limit > 0", name="ck_plans_api_call_limit_positive"),
        CheckConstraint("ai_token_limit > 0", name="ck_plans_ai_token_limit_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    api_call_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
