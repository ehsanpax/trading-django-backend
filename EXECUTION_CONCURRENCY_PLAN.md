# Trade Execution Concurrency Plan

Goal: prevent duplicate/parallel opens during rapid ticks and make execution deterministic without breaking existing flows (manual/AI/BOT).

Scope applies to all callers via central TradeService.

Phases

Phase 0 — Baseline (done)
- Centralized execution through TradeService
- Live-run metadata (source, live_run_id, bot_version_id, correlation_id) passes through the stack

Phase 1 — Idempotency guard (implemented)
- Behavior: If a trade already exists for (live_run_id, correlation_id) in open state, skip broker submit and return the existing Order/Trade.
- Location: TradeService.execute_on_broker pre-check; TradeService.persist short-circuits to return existing objects.
- Notes:
  - Non-breaking; no new settings or migrations.
  - Requires callers to pass correlation_id. ExecutionAdapter already supplies one (uses provided or random UUID per intent).
  - Limits: a true race before the first trade is persisted can still slip through; addressed by Phase 2 lock.

Phase 2 — Per-run/symbol/side lock (implemented, behind settings)
- Lock type: Redis-based short TTL lock using SET NX PX.
- Key format: lock:open:{live_run_id}:{symbol}:{side}
- TTL: 3–5s (configurable). If lock not acquired: skip with log.
- Placement: Wrap the open critical section in TradeService around idempotency/max-open checks and broker submit.
- Fallback: If Redis unavailable, the guard becomes a safe no-op (existing behavior preserved).

Phase 3 — Cooldown/debounce (implemented, default off)
- Prevent bursty re-entries even after lock release.
- Key: cooldown:open:{live_run_id}:{symbol}:{side}
- Window: MIN_ENTRY_COOLDOWN_SEC (settings or strategy param). If within window: skip and log.
- Placement: After acquiring the lock and passing idempotency checks; timestamp set on successful submit.

Phase 4 — Max-open including pending (planned)
- Treat opening/submitting orders as occupying capacity.
- Gate: count open trades + pending/partial orders for live_run_id (optionally per symbol/side).
- Placement: inside lock, before broker call.

Phase 5 — Worker serialization (optional)
- Route execution for a live_run_id to a dedicated Celery queue with concurrency=1.
- Guarantees per-run single-threaded execution even under bursts.

Phase 6 — DB uniqueness (optional, later)
- Add a unique constraint on (live_run, correlation_id) at the Order level once Order has lineage fields, or keep at Trade if business rules allow.
- Requires migration and code updates; do after runtime guards are proven.

Implementation details

- Correlation ID:
  - ExecutionAdapter already forwards correlation_id if provided; else generates a UUID. Deterministic hashing can be introduced later (e.g., sha1 of live_run_id+symbol+side+SL+RR+price bucket) to increase dedupe across identical signals.

- Logging/metrics:
  - Log keys: lock_acquired/lock_miss, cooldown_active, idempotent_hit, max_open_block.
  - Export counters via existing logging/monitoring where available.

Tests to validate
- Burst opens with the same correlation_id → exactly one Order/Trade created; others return idempotent result.
- Lock contention (Phase 2): concurrent attempts, only first acquires lock; others skip.
- Cooldown (Phase 3): two attempts within window → second skipped.
- Max-open including pending (Phase 4): at limit → further opens skipped.

Rollout
- Phase 1 merged first (no external dependencies).
- Phase 2 introduces Redis utils and toggles; ship behind settings flags.
- Phase 3/4 gated by settings and strategy params.
- Phase 5/6 optional and scheduled after runtime stability.

Current status
- Phase 1 implemented in trades/services.py with idempotent pre-check and short-circuit persist.
- Phase 2 lock + Phase 3 cooldown wired in trades/services.py using utils/concurrency.py; settings knobs added in trading_platform/settings.py.
- Pytest with fakeredis added; service-layer tests pass.

What changed in code
- trades/services.py: lock + cooldown gates, idempotency short-circuit, graceful skip handling.
- utils/concurrency.py: RedisLock, is_in_cooldown, mark_cooldown with safe no-op when Redis absent.
- trading_platform/settings.py: REDIS_URL, EXEC_LOCK_TTL_MS, MIN_ENTRY_COOLDOWN_SEC.
- trades/tests/test_concurrency_guards.py: pytest tests for idempotency/lock/cooldown.

How to run tests (dev)
- pip install -r requirements-dev.txt
- pytest -vv -rA trades/tests/test_concurrency_guards.py
  - Expect 3 passed; warnings may appear from third-party libs.

Next steps
- Implement Phase 4 gate (include pending/partial orders in capacity count) inside the lock.
- Optional: deterministic correlation_id generator in ExecutionAdapter.
- Optional: HTML/JUnit reports via pytest plugins for CI visibility.
