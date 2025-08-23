# cTrader Microservice and Backend Client — Delivery Plan

Last updated: 2025-08-19
Owner: TBD
Status: Draft

## Executive Summary
Build a containerized FastAPI microservice that integrates with cTrader Open API (ProtoBuf/TLS), plus a Python backend client, both mirroring the behavior of the existing MT5 service/client. Use microservices for live trading connectors; keep backtests offline with a simulated broker for determinism and safety.

- Update: Microservice now publishes normalized snapshots to RabbitMQ on connect: account_info, open_positions, pending_orders.

## Goals
- Parity with `MT5-fastapi-integrated`: REST/WS interface, resilience, and caching.
- Support DEMO and LIVE environments via OAuth2 (cTrader ID) with secure token storage and refresh.
- One runtime session per `account_id`, with reconnect/re-auth and re-subscribe.
- WebSocket fan-out for price, candles, account info, open positions, and closed trades.
- Drop-in Python client (similar to `MT5APIClient`).
- RabbitMQ fan-out between microservice and backend (parity with MT5 backend transport).

## Non-Goals
- Backtesting through the live service (keep backtests in-process with a simulated broker).
- GUI/Web UI changes beyond consuming the existing WS/REST shapes.

## References
- cTrader Open API: https://help.ctrader.com/open-api/
- MT5 parity reference (workspace): `mt5-fastapi-integrated` (FastAPI service + client)

---

## Key Learnings & Must-Follow Conventions (2025-08-19)
- Transport/protocol
  - The JSON channel of cTrader Open API must use WebSocket over TLS: `wss://{demo|live}.ctraderapi.com:5036`.
  - Do not use raw TCP or newline-delimited JSON; each WS frame contains a single JSON message.
- Message flow for onboarding account listing
  - Send 2100 `ApplicationAuthReq` with `{clientId, clientSecret}` → expect 2101 `ApplicationAuthRes`.
  - Send 2149 `GetAccountListByAccessTokenReq` with `{accessToken}` → expect 2150 response containing `ctidTraderAccount[]`.
  - Optionally send 2151 `GetCtidProfileByAccessTokenReq` → expect 2152 response with `profile.userId` (ctid_user_id).
  - Always handle 2142 `ProtoOAErrorRes` and surface `{errorCode, description}`.
- Field mapping conventions
  - Accounts are in `payload.ctidTraderAccount[]`; use `ctidTraderAccountId` as the account key.
  - Broker display: prefer `brokerTitleShort` fallback `brokerName`.
  - Environment: derive from `isLive` → `LIVE` else `DEMO`.
- OAuth & tokens
  - Token exchange endpoint: GET `https://openapi.ctrader.com/apps/token` with query params `{grant_type=authorization_code, code, redirect_uri, client_id, client_secret}`. Accept JSON response.
  - The cTrader "grantingaccess" flow may omit `state` in the callback; support a `temp_id` path: cache `{code}` by `temp_id` for 15 minutes and complete later.
  - Do not persist tokens in the service; immediately forward to backend via internal endpoint, keep only short-lived onboarding cache.
- Security/observability
  - Never log tokens or PII; redact sensitive fields. Cache TTL for onboarding state = 15 minutes.
  - Return precise errors for OpenAPI failures including `{errorCode, description}`; use 5xx for upstream failures, 4xx for client/state issues.
  - Frontend must use Django proxy endpoints and Django Channels; do not expose the microservice publicly. WebSocket endpoints are internal-only (backend <-> microservice).

---

## FIX-ready architecture (hybrid with Open API)
To enable adding cTrader FIX later without rework, we will keep the transport layer pluggable.
- Transport-agnostic interface
  - Define `BrokerExecution` interface: connect, disconnect, place_order, amend_order, cancel_order, close_position, get_positions, get_account, subscribe_prices, subscribe_events.
  - Domain models remain unified; adapters map transport-specific fields to domain enums (e.g., FIX ExecType/OrdStatus).
- Adapter implementations
  - `OpenApiAdapter` (current) wraps Open API WS session and REST helpers.
  - `FixAdapter` (later) manages FIX session, sequence store, and message mapping.
- Runtime selection per account
  - Backend persists `transport=openapi|fix` per account; service chooses adapter on connect.
  - SessionManager stores adapter sessions (not hard-coded Open API).
- Idempotency & correlation
  - Require client_order_id for all orders; map to broker OrderID/ExecID.
  - Safe retries with duplicate detection.
- Queues, heartbeats, and rate limits
  - One serialized send queue per connection; pluggable throttling (Open API ~50 rps non-historical/5 rps historical; FIX per broker policy).
  - Heartbeat abstraction (Open API 1001 vs FIX Heartbeat/TestRequest) behind adapters.
- Errors, fallbacks, and metrics
  - Normalize errors to domain types; optional feature-flag fallback to Open API if FIX down.
  - Tag logs/metrics with transport=openapi|fix for observability.
- Symbols & IDs
  - Central symbol cache/mapping, with thin adapter-specific conversions.

---

## Environment & Secrets
- CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_REDIRECT_URI
- CTRADER_ENV=DEMO|LIVE
- CTRADER_OPENAPI_HOST, CTRADER_OPENAPI_PORT (default: demo/live:5036)
- CTRADER_AUTH_URL (authorize endpoint for your app)
- CTRADER_TOKEN_URL (default: https://openapi.ctrader.com/apps/token)
- SERVICE_BASE_URL, WS_BASE_URL
- BACKEND_BASE_URL (Django API base)
- INTERNAL_SHARED_SECRET (for internal token endpoints)
- FRONTEND_ORIGIN (exact origin for OAuth postMessage and CORS, e.g. http://localhost:8000)
- Django setting: CTRADER_API_BASE_URL (points to FastAPI base, e.g. http://localhost:7999)
- RABBITMQ_URL (enabled; primary transport between microservice and backend fan-out)
- AMQP_EVENTS_EXCHANGE (optional, default: `mt5.events`)
- FIX configuration (future)
  - FIX_HOST, FIX_PORT, FIX_SENDER_COMP_ID, FIX_TARGET_COMP_ID
  - FIX_TLS_ENABLED=true|false, FIX_CA_BUNDLE
  - FIX_HEARTBTINT (seconds), FIX_LOGON_RESET=true|false
  - FIX_IP_ALLOWLIST notes (managed outside envs)
- Secure token/secret store per `account_id`

---

## Backend integration contract
- Internal tokens endpoint: `PUT/GET /api/accounts/internal/brokers/ctrader/{id}/tokens` with header `X-Internal-Secret`.
  - Note: `{id}` may be the numeric CTraderAccount.id or the internal Account UUID. The backend resolves either form.
- Persist: `{access_token, refresh_token, token_expires_at, ctid_user_id, ctid_trader_account_id, environment}`.
- Backend transport (fan-out): microservice publishes to RabbitMQ topics; Django subscribes and fans out to Channels.
  - Topics (implemented):
    - `account.{account_id}.account_info` — envelope type: `account_info`
    - `account.{account_id}.open_positions` — envelope type: `open_positions`
    - `account.{account_id}.pending_orders` — envelope type: `pending_orders`
    - `price.{account_id}.{symbol}` (planned)

### Event payloads (normalized)
- account_info
  - `{ account_id, source: 'ctrader', balance, equity, margin, free_margin, currency, leverage, raw }`
- open_positions
  - `{ account_id, source: 'ctrader', positions: [{ id, symbol, volume, side, open_price, stop_loss, take_profit, commission, swap, profit, raw }...] }`
- pending_orders
  - `{ account_id, source: 'ctrader', pending_orders: [{ id, symbol, volume, side, type, price, stop_loss, take_profit, state, raw }...] }`

### Django proxy endpoints (now implemented)
These backend routes proxy to the FastAPI microservice, so the frontend never calls the microservice directly.
- POST `/ctrader/onboard/` → forwards to FastAPI `POST /ctrader/onboard` with `X-Internal-Secret`
- GET  `/ctrader/oauth/callback` → redirects to FastAPI `GET /ctrader/oauth/callback`
- GET  `/ctrader/accounts/` → forwards to FastAPI `GET /ctrader/accounts` with `X-Internal-Secret`
- POST `/ctrader/onboard/<str:account_id>/complete` → forwards to FastAPI `POST /ctrader/onboard/{account_id}/complete` with `X-Internal-Secret` (accepts UUID or int)
- POST `/ctrader/connect/` → forwards to FastAPI `POST /ctrader/connect` with `X-Internal-Secret`
- POST `/ctrader/close/` → forwards to FastAPI `POST /ctrader/close` with `X-Internal-Secret`
- DELETE `/ctrader/instance/<str:account_id>` → forwards to FastAPI `DELETE /ctrader/instance/{account_id}` with `X-Internal-Secret`
Notes:
- Configure Django env `CTRADER_API_BASE_URL` to the FastAPI base URL.
- Ensure `INTERNAL_SHARED_SECRET` matches between Django and the FastAPI service.
- Accounts proxy is hardened to surface non‑JSON upstream responses as structured errors (status, content_type, body snippet) for easier debugging.

---

## Terminology & Key Mappings
- Volume: 1 lot = 100000 units (cTrader uses units). Round to symbol volume step.
- Timeframes: {M1,M5,M15,M30,H1,H4,D1} ↔ ProtoOATrendbarPeriod enums.
- Precision: round prices to symbol.digits; respect min sl/tp distance and step.
- Hedging vs netting: Normalize cTrader netting to our “position” schema; document aggregation rules.
- Symbol mapping: cTrader uses `symbolId` per account; cache {name ↔ id} per account.

---

## Target API Surface (parity with MT5)

REST (prefix: `/ctrader`)
- Onboarding & Session
  - POST `/ctrader/onboard` → start OAuth (returns authorization URL)
  - GET  `/ctrader/oauth/callback` → exchange code, store tokens, list accounts
  - POST `/ctrader/onboard/{account_id}/complete` → link selected cTrader trading account to the newly created internal account; persist tokens and accountId
  - POST `/ctrader/connect` → ensure session for `account_id`
  - POST `/ctrader/close` → stop session
  - DELETE `/ctrader/instance/{account_id}` → delete runtime and mappings

- Trading
  - POST `/ctrader/trade` → market/limit/stop; buy/sell; optional `client_order_id`
  - POST `/ctrader/positions/close` → full/partial close by `position_id`
  - POST `/ctrader/positions/modify_protection` → set SL/TP
  - POST `/ctrader/orders/cancel` → cancel pending order

- Account/Positions/Orders
  - POST `/ctrader/positions/open` → positions + pending orders
  - POST `/ctrader/positions/details`
  - POST `/ctrader/positions/by_order`
  - POST `/ctrader/account_info`

- Market Data
  - POST `/ctrader/price` → latest tick for symbol (from cache)
  - POST `/ctrader/symbol_info` → precision, steps, contract size
  - POST `/ctrader/candles` → history: `count` or `start_time`/`end_time`
  - POST `/ctrader/deals/history` → deals by time range
  - POST `/ctrader/deals/sync_data` → aggregated sync for a position (MT5 parity)

WebSocket (internal) `/ws/{account_id}/{client_id}`
- Inbound control
  - `subscribe_price` / `unsubscribe_price` {symbol}
  - `subscribe_candles` / `unsubscribe_candles` {symbol, timeframe}
- Outbound messages (published to RabbitMQ; Django fans out to frontend via Channels)
  - `account_info` {data}
  - `open_positions` {data}
  - `closed_position` {data}
  - `live_price` {data}
  - `candle_update` {symbol, timeframe, data}

---

## Architecture Overview
- FastAPI app with modules: connector (ProtoOA), session manager, websocket manager, onboarding (OAuth), messaging (RabbitMQ enabled).
- One connector per `account_id` (long-lived session); registry of active subscriptions.
- Microservice publishes to RabbitMQ; Django subscribes and fans out to Channels (same pattern as MT5).
- Containerized (Docker); healthchecks, metrics, structured logs; configurable via `.env`.
- Python backend client mirrors MT5 client (WS + REST; listeners, caches, reconnection) and/or RabbitMQ consumers.

---

## Repo Layout (proposed)
```
ctrader-fastapi-integrated/
  app/
    main.py
    connector.py          # cTraderConnector (ProtoOA/TLS, auth, subs, trading)
    session_manager.py
    websocket_manager.py
    auth.py               # OAuth2 onboarding, token refresh
    models.py             # Pydantic request/response models
    messaging/
      publisher.py        # RabbitMQ publishers
      pollers.py          # optional polling orchestration
    proto/                # generated ProtoOA stubs (pinned)
  tests/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.sample
```

---

## Phase-by-Phase Plan

Each phase includes status checkboxes to track progress. Update as you complete tasks.

### Phase 0 — Foundations & Skeleton
- [x] Create repo structure and scaffolding
- [x] Implement FastAPI app with `/healthz`, `/readyz`
- [x] Dockerfile, docker-compose, requirements
- [ ] CI: build, lint, unit-test scaffold
- [x] Introduce transport abstraction (interface + adapter registry) — skeleton only

Deliverables:
- Bootable container with healthchecks and CI green

Exit Criteria:
- `docker-compose up` starts service; `/healthz` returns 200

---

### Phase 1 — OAuth Onboarding & Token Storage
- [x] POST `/ctrader/onboard` → returns authorize URL
- [x] GET `/ctrader/oauth/callback` → exchanges code, persists tokens to backend; supports `temp_id` when `state` missing
- [x] GET `/ctrader/accounts` → lists accounts via OpenAPI WebSocket (2100→2149/2150, 2151/2152)
- [x] POST `/ctrader/onboard/{account_id}/complete` → bind selected trading account and finalize onboarding
- [ ] Token store abstraction (encrypted at rest)
- [ ] Token refresh job and retry on 401

Progress notes:
- Implemented token exchange against `https://openapi.ctrader.com/apps/token` (GET with params).
- Replaced earlier TCP attempt with proper WebSocket to `wss://{demo|live}.ctraderapi.com:5036` for JSON channel.
- Token refresh-on-connect implemented in Connect endpoint; background refresh daemon and retry-on-401 pending.
- Error handling surfaces `ProtoOAErrorRes` details; onboarding cache uses 15-minute TTL.

Deliverables:
- End-to-end onboarding for demo env

Exit Criteria:
- Able to bind `account_id` to a cTrader account with valid, refreshable tokens

#### Onboarding flow (clarified)
1) In Django, user creates an Account with platform = cTrader. Backend creates:
   - `accounts.Account` (internal account, has UUID `account_id`)
   - `accounts.CTraderAccount` placeholder linked to the above, status = `PENDING`, tokens null.
2) Backend initiates onboarding: call `POST /ctrader/onboard` with `account_id`.
   - Service generates OAuth state bound to `account_id` (+ nonce, expiry), returns the cTrader authorization URL.
3) User authenticates with cTrader ID; service handles `GET /ctrader/oauth/callback?code&state`.
   - If `state` missing (grantingaccess), generate a `temp_id` and cache `{code}` under it for ~15 min.
   - If `state` present, exchange `code` → tokens and cache under `state`.
   - Popup posts a message to the frontend and closes. Fallback: redirect to frontend with `?ctrader_temp_id=...`.
4) UI then calls `GET /ctrader/accounts?temp_id=<temp_id>` (or `state=<state>`) to exchange code (if needed) and list accounts via Open API WS; also retrieves `ctid_user_id`.
5) UI posts selection to `POST /ctrader/onboard/{account_id}/complete` with `{temp_id|state, ctrader_account_id, environment, ctid_user_id?}`.
   - Service persists tokens and selection to the backend for that `account_id`.
   - Optional: call `/ctrader/connect` to start the session.

Frontend callback handshake
- The callback window executes a small script to:
  - postMessage `{ source: 'ctrader', temp_id|state }` to `FRONTEND_ORIGIN` if `window.opener` is available, then close.
  - fallback-redirect to the frontend origin with `?ctrader_temp_id=...` (and `state` if present) so the app can pick it up.
- The frontend must:
  - attach a `window.addEventListener('message', ...)` before opening the popup;
  - trust only the expected origin(s) in production;
  - on receiving `{ temp_id|state }`, call `/api/ctrader/accounts` with that key and render the returned accounts.

ID handling
- The service and Django now accept either a numeric `CTraderAccount.id` or the internal Account UUID for `broker_connection_id`/`account_id` where applicable.
- Recommendation: use the Account UUID end‑to‑end for consistency.

---

### Phase 2 — Low-level Connector (ProtoOA/TLS)
- [x] JSON WS session scaffold (2100 app auth, 2102 account auth, heartbeat 1001)
- [ ] Adapterize current connector as `OpenApiAdapter` (implements BrokerExecution)
- [ ] SessionManager to depend on interface; store adapter session per account
- [ ] Per-socket send queue and basic throttling (Open API limits)
- [ ] Reconnect (exponential backoff + jitter), re-auth, re-subscribe

Deliverables:
- Stable connection receiving heartbeats/events

Exit Criteria:
- Connector survives transient network drops; auto-recovers

---

### Phase 3 — Symbols & Account Info
- [ ] Symbol catalog cache per account (GetAllSymbols/GetSymbolByName)
- [ ] POST `/ctrader/symbol_info`
- [ ] Account info retrieval and WS broadcast
- [ ] POST `/ctrader/account_info`

Deliverables:
- Accurate precision/steps; account snapshots via REST & WS

Exit Criteria:
- Symbol/Account endpoints mirror MT5 parity shapes

---

### Phase 4 — Price Stream (Spots)
- [ ] SubscribeSpots per requested symbol
- [ ] Cache last tick per symbol
- [ ] WS `subscribe_price`/`unsubscribe_price`
- [ ] Broadcast `live_price`; REST `/ctrader/price` returns cache

Deliverables:
- Multi-client fan-out per account

Exit Criteria:
- Sub/unsub changes server load; REST returns recent tick without blocking

---

### Phase 5 — Candles/Trendbars
- [ ] History via `GetTrendbars` (count or window)
- [ ] Live: `SubscribeLiveTrendbar`; finalize bar at close
- [ ] Mapping timeframe ↔ proto enums
- [ ] REST `/ctrader/candles`, WS `candle_update`

Deliverables:
- Finalized candles match historical responses; live bar separated

Exit Criteria:
- Parity with MT5 client expectations (live vs historical semantics)

---

### Phase 6 — Positions, Orders, Trading Events
- [ ] Snapshot endpoints: `/ctrader/positions/open`, `/details`, `/by_order`
- [ ] Subscribe trading events; cache positions/orders; WS `open_positions`, `closed_position`
- [x] Normalize JSON to MT5 parity (types/fields); include pending orders in stream — initial snapshots on connect
- [ ] Equity strategy: prefer SubscribeSpots for held symbols (+ conversion chain) and compute PnL locally; fallback to `ProtoOAGetPositionUnrealizedPnLReq` every 2–3s
- [x] Publish normalized payloads to RabbitMQ topics (`account.{account_id}.*`) — snapshots on connect

Deliverables:
- Deterministic open_positions response; live updates without polling

Exit Criteria:
- Downstream consumers work unchanged

Note: Phase 6 is being prioritized ahead of Phases 3–5 to deliver live account/positions streaming first.

---

### Phase 7 — Trading Operations
- [ ] `/ctrader/trade` → market/limit/stop with `client_order_id`
- [ ] Error mapping and idempotency across transports
- [ ] Feature-flag to route via FIX adapter when available

Deliverables:
- E2E trading on demo accounts

Exit Criteria:
- Acceptance tests for place/modify/close pass reliably

---

### Phase 8 — Deals/History & Sync Helpers
- [ ] `/ctrader/deals/history` (time range)
- [ ] `/ctrader/deals/sync_data` (parity with MT5: deals[], closures, final PnL)
- [ ] Sign conventions match MT5 responses

Deliverables:
- Reconciliation works with existing pipelines

Exit Criteria:
- Sync tooling produces same invariants as MT5 version

---

### Phase 9 — Resilience, Security, Observability
- [ ] Reconnect policies; caps and alerts
- [ ] Token refresh daemon and secret rotation
- [ ] Structured logging; PII/tokens redaction
- [ ] Metrics & dashboards; SLOs

Deliverables:
- Runbooks and alerting

Exit Criteria:
- Soak tests (>24h) without manual intervention

---

### Phase 10 — Containerization & Ops
- [ ] Harden Dockerfile (non-root), healthcheck, graceful shutdown
- [ ] docker-compose with profiles (DEMO/LIVE)
- [ ] Secrets management (env/secret store)

Deliverables:
- Reproducible deployments; local dev up

Exit Criteria:
- One-command startup; health checks green

---

### Phase 11 — Python Backend Client (`ctrader_api_client.py`)
- [ ] WS manage_connection with auto-reconnect & re-subscribe (internal WS) or RabbitMQ consumer
- [ ] Listener registries (price/candles/account/positions/closed)
- [ ] Caches: last_account_info, last_open_positions, last_prices
- [ ] REST wrappers: connect, account, price, symbol, candles, positions, trade ops, deals
- [ ] `trigger_instance_initialization` helper
- [ ] Connection manager singleton per `account_id`

Deliverables:
- Drop-in parity with `MT5APIClient`

Exit Criteria:
- Existing backend consumers can switch by broker flag with minimal changes

---

### Phase 12 — Backend Integration
- [ ] BrokerGateway interface implemented for cTrader (LiveGatewayCT)
- [ ] Wire `LiveRun` to choose MT5/cTrader per account/broker
- [ ] Risk and execution rule audit for live reporting

Deliverables:
- Seamless switch between brokers

Exit Criteria:
- Feature flag toggles live provider without regressions

---

### Phase 13 — QA & Rollout
- [ ] Unit/integration test coverage targets achieved
- [ ] Soak/load tests
- [ ] Staged rollout to selected demo, then limited live

Deliverables:
- Release notes, rollback plan

Exit Criteria:
- SLOs met in staging; go/no-go gate approved

---

## Open Questions / Decisions Log
- [ ] FIX availability per broker/account; supported message set and MD access
- [ ] FIX session policies (TLS, IP allowlist, HeartBtInt, reset-on-logon)
- [ ] Whether to implement FIX MD or keep Open API MD only
- [ ] Token storage backend selection (DB vs. secret manager)

---

## Change Log
- 2025-08-19: Initial draft created
- 2025-08-19: Added protocol learnings (WebSocket JSON), onboarding temp_id support, backend token contract, and environment updates
- 2025-08-19: Added FIX-ready architecture, environment placeholders, and abstraction tasks
- 2025-08-19: Documented Django proxy endpoints and FRONTEND_ORIGIN env; added operational steps
- 2025-08-19: Wired Django proxies for connect/close/instance delete and documented them
- 2025-08-19: Clarified internal-only WS (frontend via Django), enabled RabbitMQ fan-out between microservice and backend, documented equity strategy (SubscribeSpots + conversion chain, fallback UnrealizedPnL @2–3s), noted token refresh-on-connect, and reprioritized Phase 6 ahead of Phases 3–5
- 2025-08-19: Implemented RabbitMQ publishing in the microservice (aio-pika). On connect, service publishes `account_info`, `open_positions`, and `pending_orders` snapshots to `account.{account_id}.*`. Added startup/shutdown hooks and env `AMQP_EVENTS_EXCHANGE` (default `mt5.events`).
