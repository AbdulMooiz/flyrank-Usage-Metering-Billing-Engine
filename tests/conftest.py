import os
import re
import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import get_db
from app.db.base import Base
from app.main import app
from app.models import Plan, Subscription, Tenant

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://usage:usage@localhost:5432/usage_metering_test",
)
FREE_TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
PRO_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _test_engine():
    database_url = make_url(TEST_DATABASE_URL)
    database_name = database_url.database
    if database_name is None or re.fullmatch(r"[A-Za-z0-9_]+", database_name) is None:
        raise ValueError("TEST_DATABASE_URL must use a simple PostgreSQL database name")

    admin_engine = create_engine(database_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
            {"database_name": database_name},
        )
        if not exists:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    admin_engine.dispose()
    return create_engine(TEST_DATABASE_URL, pool_pre_ping=True)


@pytest.fixture()
def database() -> Generator[sessionmaker[Session], None, None]:
    engine = _test_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestSession.begin() as session:
        free_plan = Plan(name="Free", api_call_limit=1_000, ai_token_limit=100_000)
        pro_plan = Plan(name="Pro", api_call_limit=100_000, ai_token_limit=10_000_000)
        session.add_all([free_plan, pro_plan])
        session.flush()
        session.add_all(
            [
                Tenant(id=FREE_TENANT_ID, name="Test Free Tenant"),
                Tenant(id=PRO_TENANT_ID, name="Test Pro Tenant"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Subscription(tenant_id=FREE_TENANT_ID, plan_id=free_plan.id, status="active"),
                Subscription(tenant_id=PRO_TENANT_ID, plan_id=pro_plan.id, status="active"),
            ]
        )

    def override_get_db() -> Generator[Session, None, None]:
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestSession
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(database: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
