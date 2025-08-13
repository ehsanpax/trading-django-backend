# Live Run Execution – Rollout Plan and Progress Tracker

Purpose
- Deliver live execution in the monolith first; then enable event-driven execution (RabbitMQ/Kafka).
- Keep a single execution DTO and gateway so strategy/engine code doesn’t change between phases.

Status Legend
- [ ] Not started  [~] In progress  [x] Done  [!] Blocked

Milestones
- M1 Monolith live execution (account-bound) usable end-to-end
- M2 Observability, idempotency, safety rails
- M3 Event-driven execution via message bus (RabbitMQ or Kafka)

Phase 0 – Prerequisites
- [ ] Fix bid/ask selection in `risk.management.calculate_position_size` (BUY=ask, SELL=bid)
- [ ] Add shared helper to fetch pip_size/contract_size consistently (reuse `trades.helpers.fetch_symbol_info_for_platform`)
- [ ] Define a system user/service principal for headless execution (used by LiveRun)

Phase 1 – Data model and API wiring
- [ ] Add `LiveRun.account = ForeignKey(Account, null=False)`
- [ ] Migrations and admin list displays
- [ ] Update `CreateLiveRunSerializer` to accept `account_id` and validate ownership
- [ ] Update `StartLiveRunAPIView` to set `LiveRun.account`
- [ ] Update `services.start_bot_live_run` to use `live_run.account` (drop reliance on `bot.account`)
- [ ] Pass `account_id` into Celery `live_loop`

Acceptance: Create multiple LiveRuns for the same BotVersion across different user accounts.

Phase 2 – Execution DTO and Gateway (monolith)
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

Acceptance: A simple EMA cross Sectioned strategy places simulated orders on a real/sandbox account on demand.

Phase 4 – Exits, reduction, SL/TP modification
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
