# Platform-Agnostic Migration Change Log

Owner: Core Backend Team
Status: Active
Start date: 2025-08-20
Scope: Remove platform-specific logic from services/consumers and route all broker interactions via connectors and TradingService. Maintain MT5 behavior during migration. Enable cTrader adapter next.

## Principles
- Single entry point: connectors/trading_service.TradingService
- Platform code only in connectors/*
- Preserve MT5 response shapes until callers are updated
- Incremental PRs, feature-flag if needed, tight acceptance tests
- After a flow is migrated and validated for MT5, remove platform checks from callers (no `if platform == "MT5"`). Callers stay TS-only; additional platforms are enabled by implementing their connectors without touching the caller.

## Phase 1 – Read-only flows (snapshots)
Goal: Serve account info and open positions snapshots via TradingService for MT5 and (later) cTrader, without changing streaming yet.

### Work item P1-A: Accounts – initial snapshot (balance/equity/margin + open positions)
Files:
- accounts/services.py
- accounts/consumers.py
- connectors/trading_service.py (no interface change; used by callers)

Tasks:
- [x] A1. Replace MT5 direct calls in accounts/services.get_account_details[_async]/_via_rest with TradingService
  - Implemented TS-first with safe platform fallbacks. DTO→dict adapter added.
- [x] A2. accounts/consumers.py: initial snapshot on connect
  - Uses TS for initial account_info and open_positions on MT5 path, with cache/REST fallback. Streaming unchanged.
- [x] A3. DTO → payload mapping
  - AccountInfo/PositionInfo mapped to existing JSON payload (ticket/id preserved).
- [ ] A4. Tests & acceptance
  - Unit tests to mock TradingService; manual parity check on MT5 staging.

Risks:
- Differences in numeric precision/rounding
- Position ID semantics (MT5 ticket vs standardized position_id)
Mitigations:
- Preserve ticket in payload; map DTO fields to existing keys

Status notes:
- Implemented A1–A3 in code; A4 pending.

### Work item P1-B: Trades – read-only queries (symbol info, position details, open positions APIs)
Files:
- trades/services.py
Tasks:
- [ ] B1. Replace platform branches with TradingService calls for read-only endpoints
- [ ] B2. Adapter layer for DTOs where callers expect dicts

Status notes:
- Pending after P1-A

## Phase 2 – Write flows (execute/close/modify)
Tasks:
- [ ] Refactor place/close/modify to TradingService in trades/services.py
- [ ] Keep MT5 response shape via adapter
- [ ] Add connector.fetch_trade_sync_data if needed; wire to services

## Phase 3 – Streaming unification (optional now)
Tasks:
- [ ] Migrate WS subscriptions to connector subscribe_* methods
- [ ] Remove direct MT5 WS coupling from consumers

## Phase 4 – cTrader connector enablement
Tasks:
- [ ] Implement CTraderConnector minimal surface
- [ ] Register in connectors/factory.py
- [ ] Flip accounts & trades onto TradingService for cTrader

## Decision log
- 2025-08-20: Start with snapshots in accounts (P1-A). Streaming stays MT5-specific for now.
- 2025-08-20: Policy adopted — For any migrated service, once MT5 path via TS is validated, eliminate platform conditionals in that caller and keep all platform differences behind connectors. Do not add per-platform branches in consumers/services going forward.

## Next actions (current)
- Add tests for A4 and run manual MT5 parity checks
- Plan B1 (read-only trades) refactor

## Update – 2025-08-20: Price feed migration to TradingService (Phase 3 partial)
Context:
- Migrated MT5 price/candle streaming in `price/consumers.py` to use `connectors.trading_service.TradingService`.
- Aligned `connectors.mt5_connector.MT5Connector` live subscriptions with MT5 headless orchestrator to avoid disabled WS path.

Changes:
- `price/consumers.py`
  - MT5 connect path subscribes via `TradingService.subscribe_price` and `subscribe_candles`.
  - Keeps joining Channels groups `prices_{accountId}_{SYMBOL}` and `candles_{accountId}_{SYMBOL}_{TF}` for backend fanout.
  - Historical candles now fetched via `TradingService.get_historical_candles`; adapted to existing payload shape (timestamp -> unix seconds, volume -> tick_volume) for indicator bootstrap.
  - Added explicit log markers to verify flow: `TS_PATH: subscribed price`, `TS_PATH: subscribed candles`, and unsubscribe counterparts.
- `connectors/trading_service.py`
  - Added wrappers: `subscribe_price`, `unsubscribe_price`, `subscribe_candles`, `unsubscribe_candles`.
  - Maintains optional callback bookkeeping; safe when connectors ignore callbacks (fanout path).
- `connectors/mt5_connector.py`
  - Subscriptions now call headless orchestrator (`mt5_subscribe_price/candles` and corresponding unsubscribe`).
  - Stores credentials in `self._creds` for orchestrator calls; continues to use `MT5APIClient` for REST endpoints.
- `trades/services.py`
  - Fixed missing `get_platform_connector` by aliasing `from connectors.factory import get_connector as get_platform_connector` to preserve existing call sites/tests.

Issues found and fixes:
- MT5 WS path is disabled by feature flag; connector subscribe methods must not rely on `_client.subscribe_*`. Fixed by switching to headless orchestrator functions in `MT5Connector`.
- Consumers previously injected MT5 headless subs directly; moved that responsibility under `TradingService` to centralize platform logic.
- Timestamp/volume schema mismatch broke indicator DF bootstrap; added adapter in consumer to emit `time` as unix seconds and `tick_volume` for continuity.
- NameError in trades due to missing `get_platform_connector` import surfaced while running tests; fixed via alias import.

Verification:
- Logs confirm TS-based candle subscription path:
  - `[INFO] connectors.trading_service: TS subscribe_candles on MT5 EURUSD@M1`
  - `[INFO] price.consumers: TS_PATH: subscribed candles EURUSD@M1`
- Live price and candle updates continue via Channels group fanout.
- Indicators initialize and stream updates on new candles.

Follow-ups:
- Remove now-unused websockets import from `price/consumers.py` (cleanup).
- Add contract tests covering `price/consumers.py` behavior under TS path (groups joined, adapter shape, unsubscribe on disconnect).
- Implement cTrader connector and wire `TradingService` subscriptions accordingly.

## Update – 2025-08-20: Trade execution via TradingService (Phase 2 partial)
Context:
- Added feature-flagged path to execute MT5 trades through `TradingService` while preserving legacy connector fallback.

Changes:
- `trades/services.py`
  - `TradeService._execute_broker_call`: Prefers `TradingService.place_trade_sync` for MT5 when `EXECUTE_VIA_TS` is true.
  - On filled orders, fetches position details via `TradingService.get_position_details_sync` and adapts to legacy payload shape.
  - Adds explicit log marker `TS_EXEC_PATH` to verify TradingService route and failures.
  - Keeps existing legacy MT5 and cTrader paths as fallback/unchanged.
- `trading_platform/settings.py`
  - New feature flag `EXECUTE_VIA_TS` (env-driven) to toggle TS execution path.

Verification plan:
- Enable `EXECUTE_VIA_TS=true` in `.env` on staging MT5 account and place test market orders.
- Confirm logs show `TS_EXEC_PATH` and that API responses include `position_info` with legacy keys.
- Roll back by setting flag to false if discrepancies found.

Follow-ups:
- Add contract tests around execution flow (idempotency, lock/cooldown, TS path mapping).
- Extend TS path to close/modify flows; document any DTO→dict adapters needed.

## Update – 2025-08-20: Partial close via TradingService persists closed Order rows
Context:
- During the Phase 2 migration, the partial close path was routed to `TradingService.close_position_sync` but we relied on background listeners to persist the resulting closed deals. This caused missing `Order` rows for partial closures in some cases.

Changes:
- `trades/services.py` → `partially_close_trade`
  - After invoking `TradingService.close_position_sync`, immediately calls `synchronize_trade_with_platform(trade.id)` to fetch recent deals and persist a filled `Order` for the closed portion and update `remaining_size`.
  - Best-effort tagging of `close_reason`/`close_subreason` on the last filled order remains.

Verification plan:
- Execute a partial close on MT5 and confirm:
  - A new filled `Order` is created for the closed portion with `broker_deal_id` set.
  - `Trade.remaining_size` decreases accordingly.
  - `close_reason` is tagged (manual or inferred) when applicable.

Notes:
- If MT5 `deals/sync_data` endpoint lags, we still tag best-effort on the latest filled order after sync. Further robustness may include retry or a minimal fallback row creation.

## Update – 2025-08-20: Pending order cancellation migrated to TradingService (Phase 2)
Context:
- The pending order cancellation endpoint used MT5APIClient directly. Migrated to `TradingService.cancel_order_sync` to keep platform logic behind connectors.

Changes:
- `connectors/trading_service.py`: added `cancel_order_sync` wrapper.
- `trades/services.py`: `cancel_pending_order` now calls `TradingService.cancel_order_sync` and no longer constructs MT5APIClient.

Verification plan:
- Create a pending MT5 limit order and hit the cancel endpoint; confirm the order status changes to CANCELLED and TS path logs.

Remaining migrations (high level):
- `trades/services.py`:
  - `get_pending_orders` now uses `TradingService.get_pending_orders_sync` (MT5 path supported). Extend to other connectors when implemented.
  - `synchronize_trade_with_platform` now calls `TradingService.fetch_trade_sync_data_sync`. Implement connector methods for other platforms next.
  - Remove residual platform branches once cTrader connector exists for execution/close/modify.
- `accounts/services.py`: remove cTrader REST fallback after cTrader connector ships.

## Update – 2025-08-20: Close flow simplified to platform-agnostic TradingService
Context:
- Removed explicit MT5 branching in `close_trade_globally`; now always resolves ticket and calls `TradingService.close_position_sync`.

Changes:
- `trades/services.py`: `close_trade_globally` simplified to TS path; keeps DB tagging logic unchanged.

Follow-ups:
- If connectors can emit close events reliably, consider removing the best-effort sync/refresh segments and rely on standardized event ingestion.

## Update – 2025-08-20: Symbol info retrieval via TradingService (Phase 1-B)
Context:
- We are standardizing symbol info retrieval behind `TradingService` and removing platform checks from callers per the platform-agnostic policy.

Changes:
- `connectors/trading_service.py`
  - Added `get_symbol_info_sync(symbol)` wrapper to support sync views/services.
- `trades/views.py`
  - `TradeSymbolInfoView` now uses `TradingService.get_symbol_info_sync` instead of `fetch_symbol_info_for_platform` and platform branching.
  - Fixed missing import for DRF `action` decorator causing lint errors elsewhere in file.
- `trades/helpers.py`
  - `fetch_symbol_info_for_platform` now delegates to `TradingService.get_symbol_info_sync` to keep a stable helper API for bots/automations while centralizing logic.

Verification plan:
- Hit `GET /trades/symbol-info/<account_id>/<symbol>/` and confirm logs show TS path and response matches prior MT5 shape (pip_size, tick_size, lot_size/contract_size, swaps).
- Exercise bots and automations that call `fetch_symbol_info_for_platform` and confirm consistent behavior.

Follow-ups:
- Migrate any remaining direct callers in `trades/services.py` that use platform clients for symbol info to call TradingService instead.
- Add a contract test for `TradeSymbolInfoView` to assert endpoint exists and returns expected keys for MT5.

## Update – 2025-08-20: Celery tasks migrated to TradingService (Phase 2 follow-through)
Context:
- Celery tasks in `trades/tasks.py` still used legacy MT5/cTrader clients and platform branching. Migrated to use `connectors.trading_service.TradingService` to keep all platform specifics behind connectors.

Changes:
- `connectors/trading_service.py`
  - Added `get_live_price_sync(symbol)` sync wrapper returning a dict {symbol, bid, ask, timestamp} for use in synchronous Celery tasks.

- `trades/tasks.py`
  - Removed direct imports/usages of `MT5APIClient`, `CTraderClient`, `MT5Account`, `CTraderAccount`.
  - `scan_profit_targets` now uses:
    - `TradingService.get_live_price_sync` to fetch price.
    - `TradingService.close_position_sync` to execute partial closes.
    - `TradingService.modify_position_protection_sync` to move SL to breakeven upon TP1.
    - Calls `trades.services.synchronize_trade_with_platform` immediately after a partial close to persist broker deals into `Order` rows and update `Trade.remaining_size`.
    - Tags both the textual `closure_reason` and structured `close_reason`/`close_subreason` on the specific TP close `Order` when possible.
    - Skips unsupported platforms with `TradingService.is_platform_supported()` and logs the skip.
  - `reconcile_open_positions` and `synchronize_account_trades` now:
    - Iterate over all active `Account`s, not MT5-only.
    - Use `TradingService.get_open_positions_sync()` to compare local open trades vs platform open positions.
    - Skip unsupported platforms via `is_platform_supported()`.
    - Trigger `synchronize_trade_with_platform` for trades that are open locally but missing on the platform.
  - Conservatively left "new platform positions not in DB" detection as a future enhancement pending standardized event shapes.

Verification plan:
- With an active MT5 account, create trades and profit targets, let the task run, and confirm:
  - Partial close produces a filled `Order` row with `broker_deal_id` after sync.
  - `Trade.remaining_size` decreases appropriately.
  - `closure_reason` (text) and `close_reason/close_subreason` (structured) are set on the TP close order.
  - Reconciliation detects locally-open but platform-closed positions and syncs them.

Risks / notes:
- cTrader path is still skipped until its connector implements the necessary surfaces (`get_open_positions`, `close_position`, `modify_position_protection`, and trade sync data).
- Price retrieval and protection modification rely on connector parity; errors are logged and the task advances without crashing the batch.

Follow-ups:
- Add unit tests around `scan_profit_targets` and `reconcile_open_positions` mocking `TradingService` to assert calls and DB effects.
- Implement cTrader connector parity and then remove platform skip guards in tasks.
