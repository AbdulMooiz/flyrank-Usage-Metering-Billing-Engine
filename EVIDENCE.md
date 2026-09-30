# Evidence

All automated evidence below was produced against PostgreSQL using the isolated `usage_metering_test` database. The complete suite reported `32 passed, 1 warning` on 2026-09-30. The warning is Starlette's current `httpx` TestClient deprecation notice; it does not affect test results.

Shared named-scenario command (actual output: `6 passed, 1 warning in 36.85s`):

```powershell
docker compose run --rm --volume "$($PWD.Path):/app" api pytest tests/test_metering.py::test_same_key_and_payload_returns_original_without_duplicate_events tests/test_api.py::test_quota_error_has_specific_context_and_429 tests/test_stripe.py::test_checkout_endpoint_creates_pro_session_and_rejects_duplicate_pro tests/test_stripe.py::test_verified_checkout_upgrades_tenant_and_duplicate_is_ignored tests/test_stripe.py::test_forged_webhook_returns_400_without_state_change tests/test_pricing.py::test_cached_input_and_reasoning_pricing_have_exact_integer_total -q
```

## Evidence 1: Idempotent Metering

- Test: `test_same_key_and_payload_returns_original_without_duplicate_events`
- Command: Shared named-scenario command above.
- Important output: `6 passed`; this test asserts both responses are equal, one `metering_requests` row exists, and exactly one event per usage type exists after the retry.
- Expected result: the matching retry returns the stored logical result and adds no usage or cost; the tenant-scoped unique key and row lock protect concurrent requests.

## Evidence 2: Exact Quota Boundary

- Test: `test_quota_error_has_specific_context_and_429`
- Command: Shared named-scenario command above.
- Important output: `6 passed`; this test accepts 1,000 API calls, rejects the next with `429`, checks the 1,000 limit and Pro upgrade response, and asserts exactly 1,000 API-call events remain.
- Expected result: usage exactly at the limit is allowed; any positive next increment is rejected without a partial write.

## Evidence 3: Stripe Checkout and Upgrade Projection

- Tests: `test_checkout_endpoint_creates_pro_session_and_rejects_duplicate_pro`, `test_verified_checkout_upgrades_tenant_and_duplicate_is_ignored`
- Command: Shared named-scenario command above.
- Important output: `6 passed`; Checkout uses a test Price ID, subscription mode, and tenant metadata; a correctly signed `checkout.session.completed` changes the local tenant from Free to Pro, and `GET /usage` reports Pro limits.
- Expected result: the verified webhook, not the Checkout request, changes the local subscription projection.
- Limitation: no Stripe account credentials or test Price ID were present, so a hosted Stripe Checkout session was not completed against Stripe's network. The outbound SDK request is mocked; signature verification and webhook state changes are exercised locally with a real HMAC signature.

## Evidence 4: Forgery Rejection and Event Replay

- Tests: `test_forged_webhook_returns_400_without_state_change`, `test_verified_checkout_upgrades_tenant_and_duplicate_is_ignored`
- Command: Shared named-scenario command above.
- Important output: `6 passed`; a forged signature returns `400` with zero `stripe_events` rows and no plan change; replaying a valid event returns `duplicate: true` and leaves exactly one processed event.
- Expected result: signature verification precedes database work, and persistent event-ID uniqueness makes valid event processing idempotent.

## Evidence 5: Pinned Pricing

- Test: `test_cached_input_and_reasoning_pricing_have_exact_integer_total`
- Command: Shared named-scenario command above.
- Important output: `6 passed`; 600 fresh input tokens cost 180,000 microcents, 400 cached input tokens cost 12,000, 150 output-plus-reasoning tokens cost 225,000, and one API call costs 1,000. Total: exactly `418,000` microcents.
- Expected result: cached input uses its cheaper rate, reasoning is priced as output, and all intermediate money arithmetic remains integer-based.

## Additional Verification

- Full suite: `docker compose run --rm --volume "$($PWD.Path):/app" api pytest -q` -> `32 passed, 1 warning`.
- Migration parity: `docker compose run --rm --volume "$($PWD.Path):/app" api alembic check` -> `No new upgrade operations detected.`
- Compose: `docker compose up --build -d` -> PostgreSQL healthy, API healthy, worker started; worker log: `Billing reconciliation passed`.
- Live API: `/health` returned `ok`; `/openapi.json` exposed `/health`, `/generate`, `/usage`, `/checkout`, and `/webhooks/stripe`; seeded Free and Pro tenants returned limits `1,000/100,000` and `100,000/10,000,000`.