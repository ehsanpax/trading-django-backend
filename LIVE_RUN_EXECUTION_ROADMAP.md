# Live Run Execution – Rollout Plan and Progress Tracker

Purpose
- Deliver live execution in the monolith first; then enable event-driven execution (RabbitMQ/Kafka).
- Keep a single execution DTO and gateway so strategy/engine code doesn’t change between phases.

Status Legend
- [ ] Not started  [~] In progress  [x] Done  [!] Blocked

<<<<<<< Updated upstream
## Concurrency & Idempotency Addendum (2025-08-14)
- See `EXECUTION_CONCURRENCY_PLAN.md` for details.
- Current status:
  - [x] Phase 1 – Idempotency guard in `trades/services.py` (pre-check + persist short-circuit)
  - [~] Phase 2 – Redis lock scaffold and settings added; gating integrated in `TradeService.execute_on_broker` with safe no-op when Redis absent
  - [~] Phase 3 – Cooldown hook integrated; default cooldown is 0s (disabled) until configured
  - [ ] Phase 4 – Max-open including pending (to be added inside the lock)
  - [ ] Phase 5 – Worker serialization (optional)
  - [ ] Phase 6 – DB uniqueness constraint (optional)

---

## Update – 2025-08-13

Progress snapshot
- Phase 1 – Data model and API wiring: [x] Completed (LiveRun.account, serializer/view wiring, account passed to live loop)
- Phase 2 – Execution DTO and Gateway (monolith): [~] In progress (ExecutionAdapter builds DTO; shared helper still pending)
- Phase 3 – Live loop (MVP): [x] Completed (candle/tick support, indicators, STOPPING, error handling, logging)
- Phase 4 – Exits/reduction: [~] In progress (CLOSE_POSITION and partial close supported; SL/TP modify pending)
- Phase 5 – Observability/safety: [~] In progress (structured logs; guardrails via risk; heartbeat/metrics pending)
- Phases 6–9: [ ] Not started

Key changes implemented
- ExecutionAdapter
  - Derives take-profit when missing using RR multiple against SL distance; default RR sourced from strategy params (fallback 2.0).
  - Fills missing symbol from context default.
  - Adds verbose logging for payload, validation results, broker response, and persistence.
  - Supports CLOSE_POSITION actions:
    - qty = "ALL": closes all open trades for the symbol via close_trade_globally.
    - numeric qty: partially closes most recent open trade via partially_close_trade.
- Live loop (bots.tasks.live_loop)
  - Warmup: loads ~200 bars, computes indicators after warmup; logs indicator snapshot.
  - On each new candle: updates DataFrame, recomputes indicators, logs snapshot, enforces min bars needed, runs strategy, executes actions.
  - Tick mode: updates tick column and tick-sourced price indicator columns, runs strategy and executes actions when decision_mode=TICK.
  - No ORM access in the main loop; a separate stop-poller thread checks DB with safe connection handling.
  - Supports timeframe and decision_mode from LiveRun.
- Platform API
  - MT5APIClient.get_live_price: avoids unsafe async calls; uses websocket cache if present, else falls back to REST endpoint; logs cache miss and HTTP calls.
- Accounts service
  - get_account_details (sync): replaced AsyncToSync wrapper with a REST-based synchronous implementation safe to call in threads with running event loops; async variant retained for async contexts.
- Risk/TradeService
  - TradeService.validate continues to use risk.management.validate_trade_request and perform_risk_checks. With the updated accounts service, the AsyncToSync error is eliminated.

Issues encountered and fixes
1) RuntimeError: "You cannot use AsyncToSync in the same thread as an async event loop"
   - Cause: accounts.services.get_account_details used @async_to_sync in a thread that already had a running event loop (due to websocket feed).
   - Fix: Implemented a synchronous, REST-based get_account_details that bypasses AsyncToSync; kept async version for async-only contexts.

2) Indicator column errors in SectionedStrategy (missing columns / NaNs)
   - Cause: Indicators were not computed after warmup or not updated per bar; tick-sourced price column not synced.
   - Fix: Compute indicators after warmup and on each new bar; in tick mode, update tick column and any price(source=tick) indicator columns before strategy run.

3) Trades skipped due to missing take-profit in actions
   - Cause: Strategy emitted OPEN_TRADE with sl but tp=None.
   - Fix: ExecutionAdapter derives TP from SL and RR (default 2.0 or from strategy params risk.default_rr). Logged derived TP.

4) CLOSE_POSITION actions ignored
   - Cause: Adapter only supported OPEN_TRADE.
   - Fix: Added CLOSE_POSITION support. For qty="ALL": close all open trades for the symbol. For numeric qty: partial close via partially_close_trade.

5) MT5 price fetch async error / cache misses
   - Cause: Attempted unsafe async operations in sync context; cache often cold.
   - Fix: MT5APIClient.get_live_price now checks websocket cache first; on miss, uses REST without any asyncio.run. Added explicit logging for cache miss and HTTP calls.

6) ORM access inside async context
   - Cause: Polling stop flag from DB inside the live loop could clash with async state.
   - Fix: Moved DB polling to a dedicated thread with close_old_connections and DJANGO_ALLOW_ASYNC_UNSAFE set, avoiding ORM in the main loop.

Operational notes
- Logging now includes per-bar snapshots of key indicator outputs, action counts, execution payloads, and broker responses, making live debugging straightforward.
- Guardrails (daily loss, cooldown, max open per symbol, etc.) are enforced via perform_risk_checks during TradeService.validate.

Next steps
- Phase 2: Extract a shared build_trade_request helper used by both LiveRun and ExecuteAITradeView to remove duplication and ensure consistency.
- Phase 4: Implement MODIFY_SLTP mapping via update_trade_stop_loss_globally/update_trade_protection_levels.
- Phase 5: Add LiveRun heartbeat and basic metrics (intents sent/succeeded/failed) and optional correlation_id.
- Phase 6: Add idempotency key generation/storage to dedupe duplicate signals.

---

=======
>>>>>>> Stashed changes
Milestones
- M1 Monolith live execution (account-bound) usable end-to-end
- M2 Observability, idempotency, safety rails
- M3 Event-driven execution via message bus (RabbitMQ or Kafka)

Phase 0 – Prerequisites
- [ ] Fix bid/ask selection in `risk.management.calculate_position_size` (BUY=ask, SELL=bid)
<<<<<<< Updated upstream
- [x] Add shared helper to fetch pip_size/contract_size consistently (reuse `trades.helpers.fetch_symbol_info_for_platform`)
- [ ] Define a system user/service principal for headless execution (used by LiveRun)

Phase 1 – Data model and API wiring
- [x] Add `LiveRun.account = ForeignKey(Account, null=False)`
- [x] Migrations and admin list displays
- [x] Update `CreateLiveRunSerializer` to accept `account_id` and validate ownership
- [x] Update `StartLiveRunAPIView` to set `LiveRun.account`
- [x] Update `services.start_bot_live_run` to use `live_run.account` (drop reliance on `bot.account`)
- [x] Pass `account_id` into Celery `live_loop`
=======
- [ ] Add shared helper to fetch pip_size/contract_size consistently (reuse `trades.helpers.fetch_symbol_info_for_platform`)
- [ ] Define a system user/service principal for headless execution (used by LiveRun)

Phase 1 – Data model and API wiring
- [ ] Add `LiveRun.account = ForeignKey(Account, null=False)`
- [ ] Migrations and admin list displays
- [ ] Update `CreateLiveRunSerializer` to accept `account_id` and validate ownership
- [ ] Update `StartLiveRunAPIView` to set `LiveRun.account`
- [ ] Update `services.start_bot_live_run` to use `live_run.account` (drop reliance on `bot.account`)
- [ ] Pass `account_id` into Celery `live_loop`
>>>>>>> Stashed changes

Acceptance: Create multiple LiveRuns for the same BotVersion across different user accounts.

Phase 2 – Execution DTO and Gateway (monolith)
<<<<<<< Updated upstream
- [~] Define a single in-process DTO for execution (inputs to TradeService):
  - account_id (UUID), symbol, direction, order_type, limit_price?, stop_loss_distance_pips, take_profit_price, risk_percent, metadata (live_run_id, bot_version_id, signal_id, reason), projections (projected_profit, projected_loss, rr_ratio), idempotency_key (optional)
- [ ] Implement `build_trade_request(...)` helper used by both LiveRun and AI view to build the DTO (computes SL distance from absolute SL; TP is absolute)
- [x] Implement `ExecutionAdapter` that wraps `TradeService`

Acceptance: Unit tests for the helper across instruments (forex pairs with USD/non-USD quote, indices/CFD) and both sides BUY/SELL.

## Phase 2.1 – Trade tagging and journaling (decision: Option B)
- [x] Decision: Denormalized dual FK on Trade (keep it tidy; no signal_id/context on Trade)
- [x] Schema changes:
  - Add Trade.live_run (FK → bots.LiveRun, null=True, index)
  - Add Trade.bot_version (FK → bots.BotVersion, null=True, index)
  - Add Trade.source (choices: MANUAL, AI, BOT, BACKTEST), default=BOT for live runs
  - Add Trade.correlation_id (UUID, indexed) for traceability
  - Add DB indexes: (bot_version_id, created_at), (live_run_id, created_at), (source, created_at), correlation_id
- [~] Execution path wiring:
  - Pass live_run_id, bot_version_id, source="BOT", correlation_id from live loop → ExecutionAdapter → TradeService [wired]
  - Persist these on Trade in TradeService.persist [wired]
- [ ] Journaling alignment:
  - Keep detailed reasons/context in TradeJournal; create entry on open with live_run_id/bot_version_id/correlation_id and reason
  - Optionally async task for attachments/snapshots

Notes:
- Run migrations to apply model changes.
- Verify admin filters on Trade for source/bot_version/live_run.

Acceptance: Admin/API can filter trades by bot_version and live_run without joins; journals show bot lineage and reasons.

Phase 3 – Live loop (minimum viable)
- [x] Implement bar/tick update (poll current price or bars)
- [x] Compute required indicators once, then incremental updates
- [x] Evaluate strategy; for OPEN_TRADE map to DTO and call `ExecutionAdapter`
- [x] Respect STOPPING; set STOPPED on exit
- [x] Error handling: set ERROR + last_error, safe shutdown
=======
- [ ] Define a single in-process DTO for execution (inputs to TradeService):
  - account_id (UUID), symbol, direction, order_type, limit_price?, stop_loss_distance_pips, take_profit_price, risk_percent, metadata (live_run_id, bot_version_id, signal_id, reason), projections (projected_profit, projected_loss, rr_ratio), idempotency_key (optional)
- [ ] Implement `build_trade_request(...)` helper used by both LiveRun and AI view to build the DTO (computes SL distance from absolute SL; TP is absolute)
- [ ] Implement `ExecutionGatewayLocal` that wraps `TradeService`

Acceptance: Unit tests for the helper across instruments (forex pairs with USD/non-USD quote, indices/CFD) and both sides BUY/SELL.

Phase 3 – Live loop (minimum viable)
- [ ] Implement bar/tick update (poll current price or bars)
- [ ] Compute required indicators once, then incremental updates
- [ ] Evaluate strategy; for OPEN_TRADE map to DTO and call `ExecutionGatewayLocal`
- [ ] Respect STOPPING; set STOPPED on exit
- [ ] Error handling: set ERROR + last_error, safe shutdown
>>>>>>> Stashed changes

Acceptance: A simple EMA cross Sectioned strategy places simulated orders on a real/sandbox account on demand.

Phase 4 – Exits, reduction, SL/TP modification
<<<<<<< Updated upstream
- [x] Map CLOSE_POSITION → `close_trade_globally`
- [x] Map REDUCE_POSITION → `partially_close_trade`
- [ ] Map MODIFY_SLTP → `update_trade_stop_loss_globally` or `update_trade_protection_levels`
- [ ] Persist mapping: `LiveRunTradeLink(live_run, symbol, side, trade_id, opened_at)` for lookups

New: Closure tagging and partials
- Data model
  - Add `Trade.close_reason` (enum: TP_HIT, SL_HIT, STRATEGY_EXIT, MANUAL_CLOSE, RISK_CUTOFF, RECONCILER_CLEANUP, STOP_OUT) nullable until CLOSED; indexed
  - Add `Trade.close_subreason` (short code: EXIT_LONG, EXIT_SHORT, TRAILING_STOP_HIT, TIME_STOP, INVALIDATION) nullable
  - Add `Order.close_reason` and `Order.close_subreason` for close/reduce orders so partials are tagged at the order level
- Semantics
  - Strategy exits (adapter): close_reason=STRATEGY_EXIT; close_subreason=EXIT_LONG/EXIT_SHORT based on direction
  - Broker-driven exits: if broker provides a code, map to TP_HIT/SL_HIT/STOP_OUT; otherwise infer by comparing close_price to tp/sl within tolerance
  - Partial closes: tag the closing Order with reason(s); set `Trade.close_reason` only when qty → 0 (final close event)
- Broker mapping notes
  - Many brokers expose a reason/entry/comment on fills/positions; when absent or inconsistent, fall back to inference against SL/TP
  - Maintain a small tolerance band and unit tests per instrument type (FX, CFD) to avoid misclassification

Acceptance: Closed trades display consistent reasons in admin/API; partial-close Orders carry reason tags; unit tests cover TP/SL inference and strategy exits.

Phase 5 – Observability and safety
- [ ] Heartbeat updates on `LiveRun` (last_action_at, counters)
- [~] Structured logs with correlation_id (live_run_id, signal_id)
- [ ] Metrics: intents sent/succeeded/failed, latency, retries
- [x] Guardrails: cooldown, max open per symbol, daily loss (reuse risk.management)
=======
- [ ] Map CLOSE_POSITION → `close_trade_globally`
- [ ] Map REDUCE_POSITION → `partially_close_trade`
- [ ] Map MODIFY_SLTP → `update_trade_stop_loss_globally` or `update_trade_protection_levels`
- [ ] Persist mapping: `LiveRunTradeLink(live_run, symbol, side, trade_id, opened_at)` for lookups

Acceptance: Strategy exits correctly close or reduce positions created by this LiveRun.

Phase 5 – Observability and safety
- [ ] Heartbeat updates on `LiveRun` (last_action_at, counters)
- [ ] Structured logs with correlation_id (live_run_id, signal_id)
- [ ] Metrics: intents sent/succeeded/failed, latency, retries
- [ ] Guardrails: cooldown, max open per symbol, daily loss (reuse risk.management)
>>>>>>> Stashed changes

Acceptance: Dashboard/metrics show live activity; guardrails block entries when tripped.

Phase 6 – Idempotency and dedupe
- [ ] Compute `idempotency_key = sha256(live_run_id + bar_time + symbol + side + signal_fingerprint)`
- [ ] Store idempotency_key on `Order` or a new `ExecutionIntent` table; reject duplicates

Acceptance: Replayed signals do not place duplicate orders.

Phase 7 – ExecuteAITradeView alignment (optional)
- [ ] Fix `ExecuteAITradeView` account_id resolution bug
- [ ] Switch it to use the same `build_trade_request` helper
- [ ] Move journaling/attachments behind an optional flag; decouple from execution path

Acceptance: AI and LiveRun produce identical execution payloads for the same inputs.

Phase 8 – Event-driven execution (RabbitMQ or Kafka)
Option A – RabbitMQ (fastest path; aligns with Celery)
- [ ] Define queue `trade.intents` (durable, quorum), DLQ, publisher confirms
- [ ] Implement `ExecutionGatewayRMQ` to publish intents; consumer executes via TradeService
- [ ] Enforce per-account concurrency (routing key = account_id)

Option B – Kafka (high throughput, replayability)
- [ ] Topics: `trade.intents` (key=account_id), `trade.results`
- [ ] Avro/Protobuf schema; schema registry
- [ ] Idempotent producer; consumer dedupe by idempotency_key
- [ ] Outbox pattern for reliable publish from DB

Acceptance: Toggle gateway to bus-backed without changing strategy/engine code; end-to-end execution works.

Phase 9 – Cutover and resilience
- [ ] Feature flag to choose gateway (local/bus)
- [ ] Backpressure and retry policy defined
- [ ] Rollback plan to local gateway

Open Questions
- What to do when SectionedStrategy emits no SL? (Enforce SL policy vs. reject)
- Where to persist projections if TradeService recalculates them? (Single source of truth)
- MT5/cTrader session affinity constraints per account (single consumer?)
<<<<<<< Updated upstream
- Do we need a `TradeCloseEvent`/`OrderEvent` table for high fidelity auditing, or are journal + order rows sufficient?
=======
>>>>>>> Stashed changes

Testing Plan
- Unit tests: DTO builder, risk conversions, idempotency
- Integration: LiveRun placing/closing trades on demo
- E2E: Backtest → LiveRun → execution → DB state → telemetry

Appendix – Execution DTO (canonical)
```
{
  account_id: UUID,
  symbol: string,
  direction: "BUY"|"SELL",
  order_type: "MARKET"|"LIMIT"|"STOP",
  limit_price?: number,
  stop_loss_distance_pips: number, // integer
  take_profit_price: number,       // absolute
  risk_percent: number,            // percent units, e.g., 1.0
  metadata: {
    live_run_id?: UUID,
    bot_version_id?: UUID,
    signal_id?: string,
    reason?: string
  },
  projections: {
    projected_profit: number,
    projected_loss: number,
    rr_ratio: number
  },
  idempotency_key?: string
}
```
