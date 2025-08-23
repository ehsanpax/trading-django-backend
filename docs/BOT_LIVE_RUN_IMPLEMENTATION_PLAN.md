# Bot Live Run – Platform-Agnostic Implementation Plan

Owner: Backend
Branch: dev3
Last updated: 2025-08-13

## Context
We already centralize trade execution via `trades.services.TradeService` (validate → execute_on_broker → persist). Bots, manual UI, and AI trades should all use this pipeline. We’ll implement a live-run loop for bots that is platform-agnostic and scalable, starting with MT5 and leaving room for additional brokers.

Guiding principles:
- Single source of truth for execution (TradeService).
- Strict separation of platform details behind connector interfaces.
- Async-friendly streaming; sync-safe execution (ORM/Risk/Service).
- Idempotent and observable bot actions.

---

## Update – 2025-08-13
Progress snapshot
- Phase 0 – ConnectorFactory wiring: Done
- Phase 1 – Live runner MVP: Done (price/tick feed, indicators, strategy eval, ExecutionAdapter, graceful stop)
- Multi-bot support: Done (shared asyncio loop for MT5 feed; per-symbol/account locks)
- Trade lineage: Done (Trade.live_run, Trade.bot_version, Trade.source, Trade.correlation_id; indexed)
- Close scoping: Done (CLOSE_POSITION only affects trades for the current live_run and matching direction)
- State management: Done (last_heartbeat, last_action_at on LiveRun; reconciler via Celery Beat)
- Async/sync fixes: Done (removed unsafe AsyncToSync paths; ORM off event loop)
- Remaining: SL/TP modify mapping, idempotency key, shared DTO helper, metrics

Key changes implemented
- ExecutionAdapter
  - OPEN_TRADE: builds payloads consistent with manual/AI paths; derives TP from SL + RR when missing; fills symbol from context; detailed logging.
  - CLOSE_POSITION: filtered by `live_run` and `direction`; qty="ALL" closes all for that side; numeric qty partially closes most-recent position.
- Live loop (`bots.tasks.live_loop`)
  - Warmup bars, indicator computation after warmup and per bar; tick-mode updates; STOPPING/STOPPED handling; structured logging.
- Feeds
  - MT5 websocket feed refactored to use a shared asyncio loop to run multiple bots concurrently.
- State and recovery
  - LiveRun heartbeat + last_action_at; `bots.reconciler.reconcile_live_runs` marks stale runs and attempts clean shutdown.
- Platform + services
  - `MT5APIClient.get_live_price` avoids unsafe async; uses WS cache then REST; logs cache misses.
  - Accounts service exposes a sync path safe under running event loops; TradeService validate path unchanged but safe.

Issues and fixes
- AsyncToSync in thread with running loop → replaced with sync REST path.
- Indicator column NaNs/missing → compute on warmup and per bar; update tick-sourced columns.
- Missing TP in signals → derive via RR default (2.0 unless overridden in strategy params).
- Event-loop conflicts with multiple bots → shared loop thread.
- Broad CLOSE_POSITION → limited to current live_run and direction.

Operational notes
- Extensive logs for indicators, actions, execution payloads, and broker responses.
- Guardrails remain enforced via `risk.management` during TradeService.validate.

Next steps
- SL/TP modification mapping; shared `build_trade_request` helper; idempotency key + dedupe; basic metrics.

---

## Phase 0 – Minimal Abstraction (do now)
Goal: Introduce a small connector factory and use it in TradeService without changing behavior. Unblocks live-run and future platforms.

Deliverables:
- ConnectorFactory that returns an MT5-backed connector for an `Account`.
- `TradeService._get_connector` uses the factory.

Steps:
- Add `connectors/factory.py` with `get_connector(account: Account) -> Connector`.
- Implement MT5Connector as a thin wrapper over `trading_platform.mt5_api_client.MT5APIClient` (expose the subset already used by services: place_trade/order, close, modify protection, symbol info, price, positions, pending orders).
- Wire `trades/services.py` to call factory.

Acceptance tests:
- Manual/AI trade flows produce identical broker requests and DB records as before.
- Update/close/partial-close still work for MT5.

Decisions:
- Keep DTOs informal in this phase; use pass-through structures matching current service expectations.

Risks & mitigations:
- Regression in execution path → Add before/after snapshots on a staging account and compare persisted records.

---

## Phase 1 – Live Runner MVP (do now)
Goal: Ship a working live-run for bots using MT5 streaming; still rely on centralized TradeService for execution.

Architecture components:
- PriceFeed (async): subscribes to price/candles for (account, symbol, timeframe) via `connection_manager.get_client(...)`, maintains a rolling DataFrame, signals candle-close.
- IndicatorCalc: reuse `IndicatorService` logic (as in `price/consumers.py`) to compute indicators on candle close and mid-candle.
- StrategyRunner: on each tick/candle, call `strategy.run_tick(df_window, account_equity)` to produce normalized actions.
- ExecutionAdapter: convert actions to TradeService payloads (compute stop_loss_distance from SL/TP using pip_size), run TradeService in a thread executor.

Steps:
- Create `bots/execution.py`: PriceFeed, IndicatorCalc, StrategyRunner, ExecutionAdapter (MT5 only for streaming in MVP).
- Implement `bots.tasks.live_loop` as an asyncio runner:
  - Load `LiveRun`, validate `account` + `instrument_symbol`.
  - Instantiate strategy via `StrategyManager`.
  - Start PriceFeed subscriptions; on candle close → compute indicators → run strategy → execute actions via ExecutionAdapter.
  - Poll `LiveRun.status` for STOPPING/STOPPED and cleanly shutdown (unsubscribe, detach listeners).
- Add basic rate limiting + per-symbol lock to avoid duplicate orders.

Acceptance tests:
- E2E dry-run on a test account: bot produces at least one valid signal and places exactly one order per signal.
- Stop API moves run from RUNNING → STOPPED gracefully.
- ORM is never accessed from the event loop without an executor (no blocking warnings).

Decisions:
- Only single timeframe in MVP.
- Use ExecutionAdapter to calculate distance pips exactly as `automations.ExecuteAITradeView` does.

Risks & mitigations:
- Async/sync contention → Offload all ORM/TradeService calls with `run_in_executor`/`sync_to_async`.
- Price cache misses → pre-subscribe symbols at run start.

---

## Phase 2 – Hardening & Platform-Agnostic Parity (after MVP)
Goal: Strengthen the platform-agnostic layer and correctness.

Deliverables:
- BrokerConnector ABC + normalized DTOs (OrderRequest, OrderResult, Position, SymbolInfo, Candle, PriceTick).
- Rounding/precision utilities based on `SymbolInfo` (digits/tick_size/pip_size).
- First-class idempotency (client_tag) in execution payloads.
- Move pending-orders and sync-data fetch fully behind connectors.

Steps:
- Add `connectors/base.py` (ABC) and `connectors/dto.py` (dataclasses).
- Implement MT5Connector against the ABC, mapping MT5 schemas to DTOs.
- Update `ConnectorFactory` to return ABC types.
- Refactor `trades/services.py` to use normalized DTOs and rounding helpers; remove MT5 assumptions (e.g., `order_id == position_id`).
- Extend serializers to accept optional `client_tag`; persist on Order/Trade (or encode in reason if schema change deferred).

Acceptance tests:
- Contract tests for MT5Connector DTO mapping.
- Unit tests for rounding/precision helpers.
- Idempotency tests: duplicate action with same client_tag does not create duplicate trade.

Decisions:
- DTO field names (canonical): direction BUY|SELL, type MARKET|LIMIT|STOP, quantities in lots, timestamps epoch secs, prices float.

Risks & mitigations:
- Widespread refactor → do behind feature flags or in a branch; keep MT5-only code path as fallback until tests pass.

---

## Phase 3 – Additional Platforms (cTrader)
Goal: Add cTrader without touching bots/TradeService.

Steps:
- Implement `CTraderConnector` (DTO translations, capability flags like supports_streaming/pending_orders/partial_close).
- Wire credentials via `Account` → `CTraderAccount`.
- Update settings mapping in `ConnectorFactory`.
- Optional: cTrader streaming wrapper for PriceFeed.

Acceptance tests:
- Place/close/modify orders; fetch live positions; list pending orders.
- If streaming supported, run a live-run on cTrader in a test environment.

---

## Phase 4 – Observability, State, and Scaling
Goal: Improve monitoring and UI feedback; prepare for larger bot fleets.

Steps:
- Structured logging: [LiveRun <id>] [account] [symbol] [action] with correlation_id.
- Heartbeat timestamps and counters on `LiveRun` (last_heartbeat, last_action_at, last_error).
- Reconciler: Celery Beat task to detect stale runs and mark/stop them safely.
- Optional PriceBus (Redis/Kafka) to share normalized ticks/candles across bots/UI.
- Metrics: order latency, duplicate prevention counters, error budgets.

Acceptance tests:
- Logs show end-to-end action flow; UI/monitor displays live bot actions; reconciler updates stale runs.

---

## Phase 5 – Advanced Features
- Multi-timeframe inputs within a run.
- Portfolio-level risk limits across accounts.
- Smart retry/backoff on transient broker errors.
- Warm restart without duplicate orders (persist last action watermark).

---

## Sync/Async Compatibility Guidelines
- Use async strictly for streaming; never block the event loop with ORM or requests.
- Wrap TradeService and any sync connector calls with `run_in_executor` or `sync_to_async` (thread_sensitive=True when touching Django models).
- Pre-subscribe to symbols/timeframes so the cache is warm.

---

## Data Model Considerations
- Ensure `Order.broker_order_id` and `Trade.position_id` support large ids (string if needed).
- Add indexes commonly queried (account, instrument, status, created_at).
- Persist platform name on Order/Trade for auditability.
- Trade lineage fields (implemented):
  - `Trade.live_run` (FK → bots.LiveRun, indexed), `Trade.bot_version` (FK, indexed),
  - `Trade.source` (MANUAL|AI|BOT|BACKTEST), default BOT for live runs,
  - `Trade.correlation_id` (UUID, indexed) for traceability.
  - Admin filters for source/bot_version/live_run.

---

## Rollout Plan & Backout
- Phase 0 + 1 in a feature branch; deploy to staging; validate manual/AI/bot flows.
- Backout: revert to previous `TradeService._get_connector` and disable live-run endpoints.

---

## Checklists
Implementation checklist (Phase 0/1):
- [ ] ConnectorFactory in place; MT5Connector wrapper available.
- [ ] TradeService uses factory; tests still pass.
- [ ] bots/execution.py with PriceFeed/StrategyRunner/ExecutionAdapter.
- [ ] live_loop async runner with graceful stop.
- [ ] Basic dedupe/rate-limiting in ExecutionAdapter.

Test checklist:
- [ ] Unit: payload building (SL/TP → pips) across symbols.
- [ ] Unit: rounding to `digits`.
- [ ] Integration: one order per signal.
- [ ] Integration: stop live-run cleans up subscriptions.
- [ ] Regression: manual and AI trades unaffected.

---

## Open Decisions & Known Issues
Open decisions:
- Where to store client_tag (new column vs encoded in reason). For now: encode in reason; migrate later.
- PriceBus introduction (in-memory vs Redis). Defer until scale demands it.

Known issues & fixes-to-track:
- Some MT5 paths assume `order_id == position_id` on MARKET; remove once DTO normalization lands (Phase 2).
- `get_live_price` occasionally falls back to HTTP; mitigate by pre-subscribing and using the websocket cache.
- Implement MODIFY_SLTP mapping in ExecutionAdapter and services.
- Add idempotency key generation/storage to prevent duplicate orders.

---

## Appendix – Execution DTO (canonical)
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
