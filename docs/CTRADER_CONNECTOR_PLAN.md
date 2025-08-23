# cTrader Connector Migration Plan and Tracker

Owner: Core Backend Team
Status: In progress
Start date: 2025-08-20
Scope: Implement a cTrader connector that aligns with the standardized TradingService/connector architecture, delegating to our cTrader microservice. Preserve MT5 response shapes until callers are updated.

## Principles
- Single entry via `connectors.trading_service.TradingService`.
- All platform-specific logic in `connectors/*`.
- Keep MT5-compatible payloads at the service boundary where callers rely on them.
- Ship incrementally with tight, verifiable acceptance criteria.

## Assumptions (to confirm)
- The cTrader microservice exposes HTTP endpoints under `CTRADER_API_BASE_URL` (env), examples below.
- Endpoints accept `account_id` and validate auth using `access_token` or service-side session.
- Streaming is RabbitMQ-based: microservice publishes events to AMQP; our backend consumer relays to Channels groups using the same patterns as MT5 (`prices_{accountId}_{SYMBOL}`, `candles_{accountId}_{SYMBOL}_{TF}`).

If endpoints differ, we will adjust URLs in the connector; the code centralizes path building for easy updates.

## Endpoints (proposed/expected)
- POST /connect, POST /disconnect
- GET /account-info?account_id=
- GET /open-positions?account_id=
- GET /symbol-info?symbol=&account_id=
- GET /candles?symbol=&timeframe=&count|start|end&account_id=
- GET /price?symbol=&account_id=
- POST /trade/place
- POST /trade/close
- POST /trade/modify-protection
- POST /order/cancel
- GET /trade/sync-data?position_id=&symbol=&account_id=
- POST /subscribe/price, POST /unsubscribe/price (control: start/stop AMQP production for a symbol)
- POST /subscribe/candles, POST /unsubscribe/candles (control: start/stop AMQP production for symbol@timeframe)

## Streaming over RabbitMQ (chosen)
- AMQP URL: env-driven (AMQP_URL). Exchange name: env-driven (AMQP_EVENTS_EXCHANGE). Type: topic. Durable: true.
- Routing keys to publish:
	- price.tick
	- candle.update
	- positions.snapshot
	- position.closed
	- account.info
- Envelope (JSON):
	{
		"event_id": uuid,
		"event_version": 1,
		"source": "ctrader",
		"platform": "cTrader",
		"type": "price.tick" | "candle.update" | ...,
		"account_id": "<internal UUID or broker login>",
		"broker_login": "<optional>",
		"internal_account_id": "<UUID>" (recommended),
		"occurred_at": ISO8601,
		"sent_at": ISO8601,
		"payload": { ... }
	}
- Payloads:
	- price.tick: { symbol, bid, ask, time: ISO8601 }
	- candle.update: { symbol, timeframe, candle: { time: unix_seconds, open, high, low, close, volume|tick_volume } }
	- positions.snapshot: { open_positions: [ ... normalized positions ... ] }
	- position.closed: { position_id, symbol, direction, volume, open_time, open_price, close_time, close_price, profit, commission, swap, broker_deal_id?, reason? }
	- account.info: { balance, equity, margin, free_margin, margin_level, currency }
- Our consumer binds: account.#, price.#, candle.#, positions.#, position.# and will relay to Channels groups.

## Phases, tasks, and status

### Phase 1 – Read-only snapshots
- [x] Create plan doc and start connector scaffold
- [ ] Implement CTrader HTTP connector skeleton and register in factory
- [ ] Methods: get_account_info, get_open_positions
- [ ] Methods: get_symbol_info, get_historical_candles (adapter to TradingService shape)
- [ ] Method: get_live_price (optional if microservice supports)
- [ ] Acceptance: accounts/services and trades read-only paths work via TradingService for cTrader

### Phase 2 – Write flows
- [ ] Methods: place_trade, close_position, modify_position_protection, cancel_order
- [ ] Method: fetch_trade_sync_data (optional helper for `synchronize_trade_with_platform`)
- [ ] Acceptance: feature-flag TS execution path on cTrader and verify market/limit, partial close, SL/TP updates

### Phase 3 – Streaming (headless)
- [ ] Methods: subscribe_price/unsubscribe_price
- [ ] Methods: subscribe_candles/unsubscribe_candles
- [ ] Acceptance: price/consumers subscribe via TradingService for cTrader and receive updates through Channels groups

### Phase 4 – Cleanup and platform-agnostic callers
- [ ] Remove residual cTrader-specific branches from services/consumers once parity is validated
- [ ] Keep all platform specifics behind connectors

## Mapping notes
- AccountInfo: balance, equity, margin, free_margin, margin_level, currency
- PositionInfo: id, symbol, direction (BUY/SELL), volume (lots), open/current price, sl/tp, profit, swap, commission
- Candles: map trendbar fields to open/high/low/close/volume/time (iso8601)
- Symbol info: maintain keys consumed by callers (digits, tick_size, contract_size, pip_size if used)

## Risks and mitigations
- Token expiry: treat 401/403 as AuthenticationError; connector may retry refresh via a proxy if exposed by microservice
- Volume units: confirm lots vs units; normalize to lots to match MT5 callers
- Symbol naming: normalize in `get_symbol_info`
- Endpoint mismatches: keep URLs centralized in connector for quick fixes

## Verification

## Authentication Note
- All HTTP requests from the connector to the cTrader microservice use Bearer token authentication.
- The token value is loaded from `.env` as `INTERNAL_SHARED_SECRET`.
- The connector sets `Authorization: Bearer <INTERNAL_SHARED_SECRET>` on every request.


- 2025-08-20: Created plan document; starting HTTP-based cTrader connector scaffold and registration (Phase 1 kickoff)
