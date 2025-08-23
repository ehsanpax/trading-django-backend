# cTrader Microservice Handover (Contract & Requirements)

Owner: Core Backend Team
Date: 2025-08-21
Status: Ready for implementation

This is the API/contract the cTrader microservice should implement so our Django TradingService + connector can integrate cleanly. It covers HTTP endpoints for snapshots and trade ops, RabbitMQ streaming for live data, non-functional requirements, and examples.

## Goals
- Provide platform-agnostic HTTP APIs for account snapshots, positions, symbol info, candles, prices, and trade operations.
- Provide RabbitMQ (AMQP) streaming for price ticks and candle updates; our Django app relays to WebSocket clients via Channels.
- Maintain stable, predictable payloads. Use snake_case JSON.

## Non-functional requirements
- Auth: service-to-service Bearer token (Authorization: Bearer <token>)
- Required headers:
  - X-Request-ID: echoed in responses and logs
  - Idempotency-Key: required on all write endpoints; dedupe for 24h
- Timestamps: ISO-8601 UTC, e.g., 2025-08-20T12:34:56Z
- Numerics: numeric JSON (not strings); preserve price precision
- Timeouts: snapshot endpoints return in ~1s P95; price <= 200ms P95 if backed by in-memory cache
- Rate limit: return 429 with Retry-After when applicable
- Versioning: Base URL includes version, e.g., /api/v1; breaking changes require v2

## Environment/config
- CTRADER_APP_CLIENT_ID, CTRADER_APP_CLIENT_SECRET (managed microservice-side)
- CTRADER_SANDBOX=true|false (environment)
- RABBITMQ / AMQP
  - AMQP_URL (e.g., amqp://guest:guest@rabbitmq:5672/%2F)
  - AMQP_EVENTS_EXCHANGE (topic, durable) — e.g., trading.events
- Auth
  - SERVICE_TOKEN (bearer token used by our Django server)

We’ll pass the following in requests from Django:
- account_id: internal account identifier (UUID) or broker login, depending on the call
- Optional: symbol/timeframe fields as needed

## Canonical schemas (JSON; snake_case)
- AccountInfo
  - balance, equity, margin, free_margin, margin_level, currency
- PositionInfo
  - position_id, symbol, direction (BUY|SELL), volume (lots), open_price, current_price, sl, tp, profit, swap, commission
- Price
  - symbol, bid, ask, timestamp
- Candle
  - symbol, timeframe (M1,M5,M15,M30,H1,H4,D1,W1,MN1), open, high, low, close, volume, time (ISO-8601)
- SymbolInfo
  - symbol, digits, tick_size, contract_size, pip_size, leverage, min_lot, lot_step

## HTTP endpoints
Base: https://ctrader-ms.internal/api/v1 (example)

Headers for all endpoints:
- Authorization: Bearer <SERVICE_TOKEN>
- X-Request-ID: <uuid>

### Session control
- POST /connect
  - Body: { account_id: string }
  - 200: { connected: true }
- POST /disconnect
  - Body: { account_id: string }
  - 200/204

### Read-only snapshots (Phase 1)
- GET /account-info?account_id=...
  - 200: AccountInfo

- GET /open-positions?account_id=...
  - 200: { open_positions: PositionInfo[] }

- GET /position-details?account_id=...&position_id=...
  - 200: PositionInfo | 404

- GET /symbol-info?account_id=...&symbol=...
  - 200: SymbolInfo

- GET /price?account_id=...&symbol=...
  - 200: Price

- GET /candles?account_id=...&symbol=...&timeframe=...&count=... (or start_time/end_time)
  - 200: { candles: Candle[] }

### Control for streaming (RabbitMQ producers)
- POST /subscribe/price
  - Body: { account_id: string, symbol: string }
  - 202: { subscribed: true }
- POST /unsubscribe/price
  - Body: { account_id: string, symbol: string }
  - 202: { unsubscribed: true }
- POST /subscribe/candles
  - Body: { account_id: string, symbol: string, timeframe: string }
  - 202: { subscribed: true }
- POST /unsubscribe/candles
  - Body: { account_id: string, symbol: string, timeframe: string }
  - 202: { unsubscribed: true }

### Write operations (Phase 2)
Headers must include Idempotency-Key for all endpoints below.

- POST /trade/place
  - Body: { account_id, symbol, direction: "BUY"|"SELL", lot_size: float,
           order_type: "MARKET"|"LIMIT"|"STOP", limit_price?, stop_price?, sl?, tp? }
  - 200: { status: "accepted"|"filled", order_id, position_id?, fills?: [{deal_id, price, volume, time}], message? }

- POST /trade/close
  - Body: { account_id, position_id, symbol, volume: float }
  - 200: { status: "accepted"|"filled", position_id, closed_volume, deal_id?, message? }

- POST /trade/modify-protection
  - Body: { account_id, position_id, symbol, sl: float|null, tp: float|null }
  - 200: { status: "updated", position_id, sl, tp }

- POST /order/cancel
  - Body: { account_id, order_id }
  - 200: { status: "cancelled", order_id }

- GET /trade/sync-data?account_id=...&position_id=...&symbol=...
  - 200: {
        position: PositionInfo,
        deals: [{ deal_id, side, volume, price, time, commission, swap, profit, reason }],
        last_sync_time: ISO-8601
      }

## RabbitMQ streaming contract (Phase 3)
- Exchange: AMQP_EVENTS_EXCHANGE (topic, durable)
- Publish the following routing keys:
  - price.tick
  - candle.update
  - positions.snapshot
  - position.closed
  - account.info

### Envelope (JSON)
```
{
  "event_id": "uuid",
  "event_version": 1,
  "source": "ctrader",
  "platform": "cTrader",
  "type": "price.tick" | "candle.update" | "positions.snapshot" | "position.closed" | "account.info",
  "account_id": "<internal UUID or broker login>",
  "broker_login": "<optional numeric login>",
  "internal_account_id": "<UUID>" ,
  "occurred_at": "2025-08-20T12:34:56Z",
  "sent_at": "2025-08-20T12:34:57Z",
  "payload": { ... }
}
```

Our consumer binds patterns: account.#, price.#, candle.#, positions.#, position.# and relays to Channels groups:
- price → group prices_{internal_account_id}_{SYMBOL}
- candle → group candles_{internal_account_id}_{SYMBOL}_{TF}

### Payloads by type
- price.tick
```
{ "symbol": "EURUSD", "bid": 1.10000, "ask": 1.10020, "time": "2025-08-20T12:34:56Z" }
```
- candle.update
```
{ "symbol": "EURUSD", "timeframe": "M1",
  "candle": { "time": 1724144190, "open": 1.1, "high": 1.101, "low": 1.0995, "close": 1.1008, "volume": 152 } }
```
- positions.snapshot
```
{ "open_positions": [
  { "position_id": "123", "symbol": "EURUSD", "direction": "BUY", "volume": 0.10,
    "open_price": 1.10000, "current_price": 1.10123, "sl": 1.095, "tp": 1.110,
    "profit": 12.3, "swap": -0.1, "commission": -0.2 }
]}
```
- position.closed
```
{ "position_id": "123", "symbol": "EURUSD", "direction": "BUY", "volume": 0.10,
  "open_time": "2025-08-20T12:00:00Z", "open_price": 1.1000,
  "close_time": "2025-08-20T12:30:00Z", "close_price": 1.1010,
  "profit": 10.0, "commission": -0.2, "swap": -0.1, "broker_deal_id": "mt-deal-1", "reason": "manual" }
```
- account.info
```
{ "balance": 10000.12, "equity": 10010.34, "margin": 50.0, "free_margin": 9960.34, "margin_level": 20012.34, "currency": "USD" }
```

## Error model
- JSON only; no HTML bodies
- 4xx: validation/auth; schema:
```
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "details": { ... } } }
```
- 401/403: authentication/authorization failures
- 404: resource not found
- 409: conflict (idempotency or state)
- 429: rate-limited; include Retry-After header
- 5xx: internal; include correlation (X-Request-ID) in response and logs

## Idempotency & concurrency (writes)
- All write endpoints require Idempotency-Key header
- Dedupe window: 24h per (account_id, operation, natural key)
- Return original successful response on replay; do not place duplicate orders
- Close/modify must be safe on retries

## Observability
- Logs: include level, timestamp, X-Request-ID, account_id, symbol, endpoint, latency
- Metrics: request count, error rate, latency percentiles; streaming throughput; order success/failure; retry counts
- Traces: propagate X-Request-ID

## Security
- Validate and sanitize inputs; enforce symbol whitelist per account
- Never log secrets or tokens
- Consider mTLS for intra-cluster traffic

## Examples

GET /account-info → 200
```
{ "balance": 10000.12, "equity": 10010.34, "margin": 50.0, "free_margin": 9960.34, "margin_level": 20012.34, "currency": "USD" }
```

GET /open-positions → 200
```
{ "open_positions": [
  { "position_id": "123", "symbol": "EURUSD", "direction": "BUY", "volume": 0.10,
    "open_price": 1.10000, "current_price": 1.10123, "sl": 1.095, "tp": 1.110,
    "profit": 12.3, "swap": -0.1, "commission": -0.2 }
]}
```

POST /trade/place → 200
```
{ "status": "filled", "order_id": "789", "position_id": "123",
  "fills": [{ "deal_id":"d1","price":1.1001,"volume":0.1,"time":"2025-08-20T12:34:56Z" }] }
```

POST /subscribe/candles → 202
```
{ "subscribed": true }
```

## Deliverables
- OpenAPI v3 spec (yaml/json) covering all endpoints and schemas
- Example payloads (Postman collection or similar)
- Sandbox credentials and test scripts to: fetch snapshots; place/close/modify; stream price/candles
- Instructions for AMQP exchange/queue configuration and environment variables
