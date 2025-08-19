# trading-django-backend

Backend for the trading platform (Django + DRF).

Status
- Phase 9 (Validation, Explainability & Debugging): Complete as of 2025-08-18
- Details: see `docs/SECTIONED_BUILDER_PHASE9_VALIDATION_EXPLAINABILITY.md`

Tracing & Explainability
- Persistence: `bots.models.BacktestDecisionTrace`
- Settings (env or `trading_platform/settings.py`):
  - `BOTS_TRACE_ENABLED_DEFAULT` (default: false)
  - `BOTS_TRACE_MAX_ROWS` (default: 250000)
  - `BOTS_TRACE_BATCH_SIZE` (default: 1000)
  - `BOTS_TRACE_SAMPLING` (default: 1)
- APIs (authenticated; same permissions as backtest read):
  - GET `/api/bots/backtests/{id}/trace`
    - Query: `bar_index`, `ts` (epoch or ISO), `section`, `kind`, `limit`, `offset`
    - Response: `{ items: [...], count: <int> }`
  - GET `/api/bots/backtests/{id}/explain`
    - Query: `bar_index` or `ts`, `include` (comma-separated)
    - Response: summary + grouped trace path

Backtests
- Backtest results and traces are scoped to the run owner (creator) unless staff/superuser.

LiveRun health
- LiveRun has task_id, last_heartbeat, last_action_at.
- live_loop updates last_heartbeat every 5s and sets last_action_at when actions execute.
- Reconciler task `bots.reconciler.reconcile_live_runs` can be scheduled via Celery Beat to mark stale RUNNING as ERROR and finalize STOPPING to STOPPED when heartbeats are stale.

Testing
- Uses pytest / pytest-django (see `pytest.ini`).

API Handoff
- OpenAPI spec for Trace & Explain: `docs/openapi/bots-trace-explain.yaml`
- Postman collection: `docs/postman/bots-trace-explain.postman_collection.json` (set variables baseUrl, token, runId, bar_index)
- Seed sample run: `python manage.py seed_sample_trace_run --username demo --symbol EURUSD --timeframe M1 --bar_index 5`
- Auth: DRF Token auth header `Authorization: Token <token>`
- Permissions: backtest runs are only visible to their creator unless staff/superuser.
- Example flow (dev):
  1) Run the seed command to create a demo run and traces.
  2) Hit GET `/api/bots/backtest-runs/{id}/trace?bar_index=5`.
  3) Hit GET `/api/bots/backtest-runs/{id}/explain?bar_index=5`.