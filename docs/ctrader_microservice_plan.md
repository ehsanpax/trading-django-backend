# cTrader Microservice and Backend Client — Delivery Plan

Last updated: 2025-08-19
Owner: TBD
Status: Draft

## Executive Summary
Build a containerized FastAPI microservice that integrates with cTrader Open API (ProtoBuf/TLS), plus a Python backend client, both mirroring the behavior of the existing MT5 service/client. Use microservices for live trading connectors; keep backtests offline with a simulated broker for determinism and safety.

## Goals
- Parity with `MT5-fastapi-integrated`: REST/WS interface, resilience, and caching.
- Support DEMO and LIVE environments via OAuth2 (cTrader ID) with secure token storage and refresh.
- One runtime session per `account_id`, with reconnect/re-auth and re-subscribe.
- WebSocket fan-out for price, candles, account info, open positions, and closed trades.
- Drop-in Python client (similar to `MT5APIClient`).

## Non-Goals
- Backtesting through the live service (keep backtests in-process with a simulated broker).
- GUI/Web UI changes beyond consuming the existing WS/REST shapes.

## References
- cTrader Open API: https://help.ctrader.com/open-api/
- MT5 parity reference (workspace): `mt5-fastapi-integrated` (FastAPI service + client)

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

WebSocket `/ws/{account_id}/{client_id}`
- Inbound control
  - `subscribe_price` / `unsubscribe_price` {symbol}
  - `subscribe_candles` / `unsubscribe_candles` {symbol, timeframe}
- Outbound messages
  - `account_info` {data}
  - `open_positions` {data}
  - `closed_position` {data}
  - `live_price` {data}
  - `candle_update` {symbol, timeframe, data}

---

## Architecture Overview
- FastAPI app with modules: connector (ProtoOA), session manager, websocket manager, onboarding (OAuth), messaging (RabbitMQ optional).
- One connector per `account_id` (long-lived session); registry of active subscriptions.
- Containerized (Docker); healthchecks, metrics, structured logs; configurable via `.env`.
- Python backend client mirrors MT5 client (WS + REST; listeners, caches, reconnection).

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
      publisher.py        # optional RabbitMQ publishers
      pollers.py          # optional polling orchestration
    proto/                # generated ProtoOA stubs (pinned)
  tests/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.sample
```

---

## Environment & Secrets
- CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_REDIRECT_URI
- CTRADER_ENV=DEMO|LIVE
- CTRADER_OPENAPI_HOST, CTRADER_OPENAPI_PORT
- SERVICE_BASE_URL, WS_BASE_URL
- RABBITMQ_URL (optional)
- Secure token store per `account_id`: {access_token, refresh_token, expiry, accountId, broker, env}

---

## Observability & Ops
- Health: `/healthz`, `/readyz`
- Logs: structured (JSON), correlation IDs, redaction of PII/tokens
- Metrics: connection status, reconnect count, message rate, WS subscribers, request latency, error codes
- Alerts: sustained reconnect failures, token refresh failures, message backlog

---

## Testing Strategy
- Unit: proto framing, parsers, mappers, validators
- Integration: demo account flows (connect, subscribe, trade, history)
- Soak: long-lived WS with reconnects
- Load: multiple accounts, many subscriptions
- CI: lint/format, unit/integration suites, container build, basic smoke tests

---

## Rollout Plan
- Phase 0–3 internal demos on DEMO env
- Staged enablement for selected demo accounts
- Harden, then limited LIVE rollout
- Feature flag in backend to choose MT5 vs cTrader per account

---

## Risks & Mitigations
- Token expiry/invalid: proactive refresh, retry on 401, alerts
- Netting vs hedging: normalize responses; document semantics; tests for partial closes
- Rate limits: client-side throttling/backoff; batch subscriptions
- Symbol mapping drift: refresh catalog on 404; invalidate on reconnect
- Live candle semantics: finalize bar on close; dedupe updates

---

## Phase-by-Phase Plan

Each phase includes status checkboxes to track progress. Update as you complete tasks.

### Phase 0 — Foundations & Skeleton
- [x] Create repo structure and scaffolding
- [x] Implement FastAPI app with `/healthz`, `/readyz`
- [x] Dockerfile, docker-compose, requirements
- [ ] CI: build, lint, unit-test scaffold

Deliverables:
- Bootable container with healthchecks and CI green

Exit Criteria:
- `docker-compose up` starts service; `/healthz` returns 200

---

### Phase 1 — OAuth Onboarding & Token Storage
- [x] POST `/ctrader/onboard` → returns authorize URL (scaffolded)
- [x] GET `/ctrader/oauth/callback` → exchanges code (placeholder), persists temp state; lists accounts (scaffolded)
- [x] POST `/ctrader/onboard/{account_id}/complete` → bind selected trading account and finalize onboarding (scaffolded)
- [ ] Token store abstraction (encrypted at rest)
- [ ] Token refresh job and retry on 401

Progress notes:
- Scaffolding implemented in `ctrader-fastapi/app/main.py`, with temporary `FileTokenStore` and in-memory state in `app/storage.py`.
- OAuth URLs are placeholders; replace with actual cTrader endpoints and implement token exchange.

Deliverables:
- End-to-end onboarding for demo env

Exit Criteria:
- Able to bind `account_id` to a cTrader account with valid, refreshable tokens

#### Onboarding flow (clarified)
1) In Django, user creates an Account with platform = cTrader. Backend creates:
   - `accounts.Account` (internal account, has UUID `account_id`)
   - `ctrader.CTraderAccount` placeholder linked to the above, status = `PENDING`, tokens null.
2) Backend initiates onboarding: call `POST /ctrader/onboard` with `account_id`.
   - Service generates OAuth state embedding/signed with `account_id` (+ nonce, expiry), returns the cTrader authorization URL.
3) User authenticates with cTrader ID; service handles `GET /ctrader/oauth/callback?code&state`.
   - Exchange `code` → `access_token` + `refresh_token` (+ expiry).
   - Fetch CTID profile and list of trading accounts (accountId, broker, env).
   - Temporarily cache `{tokens, accounts}` keyed by `state` (short-lived, e.g., 15 minutes).
4) UI shows the returned list; user selects one trading account (usually one).
   - Backend calls `POST /ctrader/onboard/{account_id}/complete` with payload `{ctid_user_id, ctrader_account_id, environment}`.
5) Service persists tokens and selection onto the `CTraderAccount` row for that `account_id`:
   - `ctid_user_id`, `ctrader_account_id`, `broker`, `environment`, `access_token`, `refresh_token`, `token_expires_at`, status = `ACTIVE`.
   - Optionally trigger `POST /ctrader/connect` to start the session.

Data model (suggested):
- Table: `ctrader_account`
  - `id` (uuid, PK)
  - `account` (FK → `accounts.Account`, unique)
  - `ctid_user_id` (bigint)
  - `ctrader_account_id` (bigint)
  - `broker` (str), `environment` (enum DEMO/LIVE)
  - `access_token` (encrypted), `refresh_token` (encrypted), `token_expires_at` (datetime), `scope` (str)
  - `status` (PENDING|ACTIVE|ERROR)
  - `created_at`, `updated_at`
  - Indexes: (`ctid_user_id`, `ctrader_account_id`), (`account`)

Token storage options:
- Approach A (simple): store tokens directly on `CTraderAccount` per `account_id`.
  - Pros: straightforward binding and rotation.
  - Cons: duplicates if same CTID used across multiple internal accounts.
- Approach B (centralized): `CTraderUserToken` by `ctid_user_id`, and a mapping table `InternalAccountBinding` with `{account_id, ctrader_account_id, ctid_user_id}` referencing the token row.
  - Pros: single refresh flow, deduped storage.
  - Cons: more moving parts.

Recommendation: start with Approach A; evolve to B if reuse across accounts becomes common.

Security notes:
- Sign and expire `state`; validate `redirect_uri`; store tokens encrypted; never log tokens/PII.
- Enforce that `account_id` in `state` matches the completion call input.

---

### Phase 2 — Low-level Connector (ProtoOA/TLS)
- [ ] TLS socket, length-prefixed ProtoBuf framing
- [ ] Authenticate with access token; `ConnectToTradingAccount(accountId)`
- [ ] Heartbeats and ping/pong
- [ ] Reconnect (exponential backoff + jitter), re-auth, re-subscribe
- [ ] Session manager (one per `account_id`)

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
- [ ] Normalize JSON to MT5 parity (types/fields)

Deliverables:
- Deterministic open_positions response

Exit Criteria:
- Downstream consumers work unchanged

---

### Phase 7 — Trading Operations
- [ ] `/ctrader/trade` → market/limit/stop with `client_order_id`
- [ ] `/ctrader/orders/cancel`
- [ ] `/ctrader/positions/modify_protection` (SL/TP)
- [ ] `/ctrader/positions/close` (full/partial; lots→units)
- [ ] Error mapping and user-friendly messages

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
- [ ] WS manage_connection with auto-reconnect & re-subscribe
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
- [ ] Finalize symbol info fields exposed to match MT5 exactly
- [ ] Decide on RabbitMQ usage vs. WS-only for internal distribution
- [ ] Token storage backend selection (DB vs. secret manager)
- [ ] Netting aggregation details in responses

---

## Change Log
- 2025-08-19: Initial draft created
