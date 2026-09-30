# Build Log

## 2026-09-30

### AI Assistance

GitHub Copilot assisted with the initial system design, FastAPI/SQLAlchemy scaffolding, ORM models and Alembic migration, metering/pricing/quota services, Stripe adapter and webhook handling, reconciliation worker, tests, and project documentation. The generated implementation was validated and corrected through Docker builds, PostgreSQL migrations, HTTPX tests, SDK inspection, OpenAPI probes, and live Compose checks. This log does not claim unverified human work.

### Milestones and Decisions

- `99085f6` Add capstone system design.
- `422428d` Initialize API and local development stack.
- `7772d14` Add billing schema and demo seed data.
- `59c310e` Implement idempotent metering quotas and pricing.
- `133e037` Add Stripe billing and reconciliation worker.
- Tenant row locks serialize quota checks; database uniqueness and tenant-composite foreign keys protect idempotency and ownership.
- Usage cost is integer microcents; one `/generate` request records an API-call event and, when applicable, an AI-token event atomically.
- Stripe uses an instance-scoped test client. Raw webhook bytes are signature-verified, then event-ID insertion and subscription projection update commit together.
- The reconciliation worker is a small PostgreSQL-backed process with bounded retry/backoff; no broker or cache was added.

### Defects Found and Corrections

- The configured Git root is the Windows user profile, not the project folder. The initial commit already tracked this project's README at its nested path. All milestone staging used explicit project paths; unrelated profile files and the remote were left untouched.
- The first SQLAlchemy runtime import exposed a missing `DateTime` import in `UsageEvent`; it was fixed and model metadata then registered all six tables.
- Initial Alembic autogeneration inside a disposable one-off container did not persist its revision. The generation command was rerun with a project bind mount, then applied and checked against PostgreSQL.
- Stripe SDK 15.6.1 did not provide the older `to_dict_recursive()` method. The adapter now verifies the original raw bytes and decodes the same signed JSON only after verification.
- A signed JSON array triggered an uncaught SDK `AttributeError`; the adapter now rejects non-object JSON before calling Stripe verification, returning a controlled `400` with no database changes.
- A local pricing assertion initially rounded a sub-half-cent amount incorrectly; the exact half-up boundaries and total are now asserted using integer microcents.
- The initial `.env.example` used `localhost` for the database URL, which is wrong inside containers. It now uses Compose's `db` hostname and was verified through `docker compose --env-file .env.example config`.

### Verification and Limits

The final automated run reported `32 passed, 1 warning`. Alembic reported no schema drift. Docker Compose started PostgreSQL, the migrated/seeded API, and the reconciliation worker; the worker logged a successful reconciliation. The one warning is the installed Starlette/httpx TestClient deprecation notice.

No Stripe account secret or test Price ID was available in the environment. Checkout request parameters were verified with a mocked Stripe client, and real local HMAC signature verification plus webhook transitions were tested. A hosted Stripe test Checkout was not represented as completed; provide test-mode credentials and a recurring test Price ID to run that external step.