# MT5 → Backend via RabbitMQ: Migration Plan

Owner: Backend Platform
Status: Phase 2 and core fanout complete; cutover in progress

Purpose
- Move MT5→backend updates (positions/account/prices/candles) to RabbitMQ to ensure reliability and decouple UI.
- Keep a single MT5 poller per account; backend fans out to UI and triggers DB sync.

Glossary
- Events exchange: `mt5.events` (topic)
- Commands exchange: `mt5.commands` (topic) [deferred]
- Backend consumer queue: `backend.mt5.events`

Architecture snapshot (current)
- MT5 FastAPI server
  - Headless control via HTTP: `/mt5/headless/poller/start`, `/mt5/headless/subscribe/price`, `/mt5/headless/subscribe/candles`
  - Diagnostics: `/mt5/headless/health/{internal_account_id}`
  - Publishes events to RabbitMQ using `messaging/publisher.py`:
    - `position.closed`, `positions.snapshot`, `account.info`, `price.tick`, optional `candle.update`
  - Preserves original symbol/timeframe casing for API ops; may uppercase only for internal keys when needed
- RabbitMQ
  - Exchange `mt5.events` (topic, durable)
  - Backend binds to `account.#`, `price.#`, `candle.#`, `positions.#`, `position.#`
- Django backend
  - AMQP consumer `messaging/consumer.py` (Redis-backed idempotency)
  - Resolves internal account id from `internal_account_id` → UUID `account_id` → `broker_login`
  - Fans out to Channels groups:
    - Price ticks → `prices_{internal_account_id}_{SYMBOL_UPPER}`
    - Candle updates → `candles_{internal_account_id}_{SYMBOL_UPPER}_{TIMEFRAME}`
    - Positions snapshot → `account_{internal_account_id}`
    - Account info → `account_{internal_account_id}`
  - Frontend WS consumers
    - `price/consumers.py`: ensures MT5 headless readiness; subscribes via HTTP; joins Channels groups (now normalizes group symbol to UPPERCASE)
    - `accounts/consumers.py`: immediate initial state using cache or REST fallback; joins account group; reacts to fanout

Phases
1) Phase 0 – Prereqs and infrastructure [DONE]
   - RabbitMQ added to docker-compose with durable exchange; management UI enabled.
   - AMQP env vars added and URL normalization for default vhost `%2F` implemented.

2) Phase 1 – Event schema and idempotency [DONE]
   - `messaging/schemas.py` with envelope definitions.
   - `messaging/consumer.py` with Redis dedupe; routing for event types.
   - Routing for `position.closed` → `synchronize_account_trades(account_uuid)`.

3) Phase 2 – MT5 server publisher and poll loop [DONE]
   - Implemented `mt5-fastapi-integrated/messaging/publisher.py` with durable topic publish.
   - Headless HTTP control endpoints added; single poller per account enforced.
   - Diagnostics endpoint added; auto-attaches price when subscribing to candles.
   - Publishing events: `positions.snapshot`, `account.info`, `price.tick`; optional `candle.update` for charts.

4) Phase 3 – MT5 server command consumer [DEFERRED]
   - Decision: use HTTP headless control for now; AMQP command handling postponed.

5) Phase 4 – Backend consumer and integration [DONE]
   - AMQP consumer forwards events to Channels groups; account resolution and dedupe in place.
   - Group naming strategy finalized (see Casing & Group Keys).

6) Phase 5 – Backend command producer and lifecycle [PARTIAL]
   - Backend uses HTTP wrappers (`mt5_ensure_ready`, `mt5_subscribe_price`, `mt5_subscribe_candles`, `mt5_unsubscribe_*`).
   - AMQP command producer left for future alignment.

7) Phase 6 – Reliability, security, observability [IN PROGRESS]
   - Diagnostics endpoint; logs enriched with routing keys.
   - Next: DLQ, publisher confirms/metrics, health probes, retries, end-to-end tracing.

8) Phase 7 – Migration & cutover [IN PROGRESS]
   - Ingestion decoupled from UI. Multi-tab works; backend fans out via Channels.
   - Pending: broader e2e verification and soak testing; switch off any remaining WS-based ingestion paths.

Routing keys (events → mt5.events)
- `account.{account_key}.position.closed`
- `account.{account_key}.positions.snapshot`
- `account.{account_key}.account.info`
- `account.{account_key}.price.tick`
- `account.{account_key}.candle.update` (optional)
Note: `{account_key}` SHOULD be the internal Account UUID when available; otherwise broker login (numeric). Backend binds broadly and resolves to internal UUID.

Event envelope (current)
```
{
  "event_id": "uuid4",
  "event_version": 1,
  "source": "mt5",
  "platform": "MT5",
  "type": "position.closed|positions.snapshot|account.info|price.tick|candle.update",
  "account_id": "<internal_account_uuid preferred or broker_login>",
  "broker_login": "<mt5_login>",
  "occurred_at": "ISO8601",
  "sent_at": "ISO8601",
  "payload": { ... }
}
```

Casing & group keys
- External calls (MT5 endpoints) preserve symbol/timeframe casing exactly.
- Channels group keys normalize symbol to uppercase to ensure consistent fanout:
  - Price: `prices_{internal_account_id}_{SYMBOL_UPPER}`
  - Candles: `candles_{internal_account_id}_{SYMBOL_UPPER}_{TIMEFRAME}`
  - Account: `account_{internal_account_id}`
- Backend consumer uppercases symbols before fanout, and the UI WS joins uppercase groups. This prevents mismatches across brokers with mixed-case symbols.

Implemented components (code map)
- MT5 server
  - `messaging/publisher.py`: publisher singleton with durable topic exchange; helpers for each event type.
  - `main.py`: headless endpoints (poller start, price/candles subscribe), diagnostics health endpoint, improved polling logic.
- Django backend
  - `messaging/consumer.py`: AMQP consumer with Redis dedupe; group fanout; account resolution via `MT5Account`.
  - `price/consumers.py`: headless orchestration via HTTP; joins uppercase groups; manages timeframe subscriptions; indicator calc pipeline intact.
  - `accounts/consumers.py`: instant initial account info/positions via MT5 client cache or REST fallback (`accounts.services.get_account_details`).

Recent issues & fixes
- Missing endpoints (404) on MT5 server
  - Cause: routes not registered for new headless endpoints.
  - Fix: added FastAPI routes for `/mt5/headless/*` and diagnostics.
- No live price for available symbol (e.g., BTCUSD.a)
  - Cause: Channels group name mismatch (backend uppercased symbols; UI used original case).
  - Fix: UI now normalizes group symbol to uppercase when joining groups. MT5 calls still preserve original casing.
- Symbol not available (e.g., EURUSD not present)
  - Observed: `get_symbol_info` returns 400 as expected. Switching to available symbol works.
- Delayed initial account info on connect
  - Cause: waiting for next snapshot could delay UI.
  - Fix: `accounts/consumers.py` now sends cached MT5 data or falls back to REST immediately.
- Duplicate poller warnings
  - Observed: "Poller already exists" when multiple clients subscribe.
  - Status: expected; one poller per account maintained; subscriptions are reference-counted.

Verification checklist
- MT5 server
  - `POST /mt5/headless/poller/start` returns 200 and logs poller start (or already exists).
  - `POST /mt5/headless/subscribe/price` and `/subscribe/candles` return 200.
  - Diagnostics `/mt5/headless/health/{internal_account_id}` shows active poller and subscriptions.
- RabbitMQ
  - Exchange `mt5.events` exists; consumer queue `backend.mt5.events` bound to patterns listed above.
  - Events visible in management UI; routing keys carry account identifier.
- Django
  - AMQP consumer running; logs show fanout to group names.
  - Frontend receives:
    - `account_update` on `accounts` WS
    - `live_price` on `price` WS
    - `new_candle` and indicator updates after candle subscribe
- Bots (AMQPFeed)
  - Containers rebuilt so `aio-pika` is installed.
  - On bot start, logs contain: `AMQPFeed ready` with expected `bindings` including the internal UUID (and broker_login during transition).
  - In RabbitMQ UI, the bot's exclusive queue shows bindings for:
    - `account.{<internal_account_id>}.price.tick`
    - `account.{<internal_account_id>}.candle.update`
    - and, if present, the broker_login fallbacks.
  - Queue message rates show incoming deliveries as ticks/candles arrive for the symbol/timeframe in the LiveRun.

Operational runbook (current orchestration)
- Price WS connect → Django ensures headless poller via HTTP, subscribes to price and candles per client request.
- Backend AMQP consumer fans out events to Channels; UI WS receives from groups.
- Account WS connect → sends immediate state from cache or REST; further updates via AMQP fanout.

Open items / next steps
- Reliability
  - Add DLQ and retry/backoff strategy for AMQP consumer; error categorization.
  - Enable publisher confirms/ack handling in MT5 publisher; metric counters.
  - Heartbeat reconciler for stale live runs (task exists; document cadence).
- State and caching
  - Cache last price and last N candles per symbol/timeframe/account in Redis; send immediately on WS connect.
  - Maintain subscription ref-counts centrally and expose via diagnostics.
- Commands plane (deferred)
  - Introduce `mt5.commands` and move HTTP headless control to AMQP over time (`ensure_session`, `release_session`, `request_snapshot`).
- Observability
  - Add Prometheus metrics for event rates, lag, publish/consume errors; dashboards and alerts.
  - Trace IDs in envelope and propagate through fanout for end-to-end tracing.
- Testing & hardening
  - E2E tests for multi-tab, reconnects, and symbol switches.
  - Fuzz tests for symbol casing and timeframe variants.
  - Load tests for high-frequency tick/candle throughput.


Platform-agnostic guidelines (target state)
- Account identity
  - internal_account_id: required in all events (this is the Account UUID in Django).
  - source_account_key: optional metadata for the source platform (e.g., broker_login for MT5, ctid_trader_account_id for cTrader). Not used for routing.
  - platform: metadata only (e.g., "MT5", "CTRADER").
- Routing (events → mt5.events)
  - Use internal UUID only: `account.{internal_account_id}.price.tick`, `account.{internal_account_id}.candle.update`, `account.{internal_account_id}.positions.snapshot`, `account.{internal_account_id}.account.info`.
  - No platform-specific routing keys required.
- Standard event schema (target)
```
{
  "event_id": "uuid4",
  "event_version": 1,
  "source": "<connector service>",
  "platform": "<platform name>",
  "type": "price.tick|candle.update|positions.snapshot|account.info|position.closed",
  "internal_account_id": "<account UUID>",
  "source_account_key": "<optional platform-specific id>",
  "occurred_at": "ISO8601",
  "sent_at": "ISO8601",
  "payload": { ... }
}
```
- Connector responsibilities (per platform)
  - Resolve internal_account_id prior to publish (via a Django mapping API or pre-provisioned mapping).
  - Publish to the shared events exchange using the standard schema and internal_account_id-based routing.
  - Preserve symbol/timeframe casing in payloads; any normalization is backend-internal (group keys only).
- Backend responsibilities
  - Keep the consumer platform-neutral. Prefer `internal_account_id` directly; retain temporary fallbacks for transition only.
  - Channels group keys: `prices_{internal_account_id}_{SYMBOL_UPPER}`, `candles_{internal_account_id}_{SYMBOL_UPPER}_{TIMEFRAME}`, `account_{internal_account_id}`.

Transition note
- Current implementation still accepts events where `internal_account_id` is missing and maps via broker_login. Target is for all connectors to include `internal_account_id` so no mapping is needed in the backend.


AMQP-backed bot feed (plan)
- Goal: Bots consume `candle.update`/`price.tick` from RabbitMQ (no WS coupling), keeping minimal platform-specific code.
- Topology
  - Exchange: `mt5.events` (topic, durable)
  - Queue: per LiveRun, exclusive + auto-delete, short expiry.
    - Name: `bot.{live_run_id}.{SYMBOL_UPPER}.{TIMEFRAME}` (informational)
    - Bindings: `account.{internal_account_id}.candle.update` and optionally `account.{internal_account_id}.price.tick`
- Implementation
  - New `AMQPFeed(MarketDataFeed)` in `bots/feeds.py` using a shared asyncio loop and `aio-pika`.
  - Warmup via existing REST: `PriceService.get_mt5_historical_data`.
  - Filter by symbol (upper) and timeframe; coalesce ticks; prioritize candles; ack after enqueue.
  - Reconnect with backoff; delete queue on stop (exclusive+auto_delete covers most cases).
  - Container note: `aio-pika` added to `requirements.txt`; rebuild Django/Celery images so it is available inside containers.
- Integration
  - Feature flag: `BOTS_FEED_MODE=AMQP|WS|POLLING` (default AMQP; fallback to POLLING on failure).
  - `make_feed(account, symbol, timeframe)` returns `AMQPFeed` for MT5 (and future platforms) without branching by platform logic.
- Observability
  - Log queue creation/bindings, consume rate, reconnects; add metrics later (lag, drops).
  - AMQPFeed logs on startup: `AMQPFeed ready: exchange=<name> queue=<auto-name> bindings=<rk list> symbol=<SYMBOL> timeframe=<TF>`.
- Rollout
  1) Implement `AMQPFeed` + flag. [DONE]
  2) Switch default to AMQP for MT5. [DONE]
  3) Verify end-to-end: LiveRun shows heartbeats, candles processed, actions executed. [DONE]
  4) Extend to new platforms by publishing the same events (no Django/bot code changes). [ONGOING]

Implementation notes (current state)
- During transition, AMQPFeed binds to both routing key forms:
  - `account.{internal_account_id}.price.tick` and `account.{internal_account_id}.candle.update`
  - `account.{broker_login}.price.tick` and `account.{broker_login}.candle.update` (fallback)
- This ensures bots receive events even if a connector publishes with `broker_login` temporarily.
- The MT5 server is already publishing with the internal account UUID routing key as shown in debug messages.

Change log
- 2025-08-15: Phase 0/1 complete; RabbitMQ infra, schemas, consumer scaffold, Celery routing.
- 2025-08-16: Phase 2 implemented on MT5 server (publisher, headless endpoints, diagnostics). Backend fanout wired. Fixed price stream issue by normalizing group symbols to uppercase. Added REST fallback for instant account info on WS connect.
- 2025-08-16: Added platform-agnostic guidelines (internal_account_id = Account UUID), updated routing/schema target state, and drafted AMQP-backed bot feed plan.
- 2025-08-16: Implemented AMQPFeed for bots with dual-binding fallback and startup binding logs; added `aio-pika` to requirements and rebuilt containers; validated end-to-end (frontend and bots receive live price/candle).
