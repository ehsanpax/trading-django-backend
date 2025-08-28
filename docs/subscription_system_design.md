# Subscription & Entitlements System Design (Django Backend)

Status: Draft (design discussion)  
Scope: Per-user subscriptions, feature gating, and quotas. Billing to be added later.  
Date: 2025-08-28

## Goals
- Per-user subscription tiers controlling access to features.  
- Quotas per feature (e.g., N AI chat messages/day, N backtests/day).  
- Centralized, fast, race-safe enforcement used by views and background jobs.  
- Durable usage audit and reporting.  
- Extensible for future features and token-based metering.

Non-goals (for now)
- Billing and invoicing (Stripe/LemonSqueezy) — will integrate later.  
- Team/org subscriptions — per-user only initially.


## Requirements mapping
- Subscriptions per user: UserSubscription model mapping user→tier.  
- Feature list and limits by tier: Feature + TierFeature configuration.  
- Quotas and windows: per-day/per-week/per-month/rolling/lifetime; start with day/week/lifetime.  
- AI chat: count per message now, later add token-based metering.  
- Enforcement: single API `check`/`check_and_consume` used by DRF endpoints and Celery tasks.  
- Race-safety & performance: Redis atomic counters with Lua; DB for audit/aggregates.  
- Visibility: endpoints for remaining usage; admin list and drill-down.  
- Extensibility: new features added via config, not code changes.


## Key concepts
- Feature: a metered capability. Initial set:  
  - `trade_execute` (execute orders)  
  - `account_add` (link trading accounts)  
  - `backtest_run` (start a backtest)  
  - `ai_chat_message` (send one chat message)  
- Subscription tier: a named plan defining which features are available and at what limits.
- Usage event: an atomic consumption of a feature (cost usually 1) in a window.
- Window: time bucket for quotas (calendar day UTC to start, configurable later).


## High-level architecture
- Entitlements service (app-level service module):  
  - Public methods: `check`, `check_and_consume`, `reserve`, `finalize`, `release`, `get_usage`.  
  - Uses Redis for instantaneous counters and idempotent operations via Lua.  
  - Writes append-only UsageEvent rows for audit; rolls up to aggregates.
- Data store:  
  - PostgreSQL: durable configuration (tiers/features), subscriptions, events, aggregates.  
  - Redis: counters and reservations; TTL aligned with window end.
- Integration points:  
  - DRF views: decorators/permissions to guard endpoints.  
  - Celery tasks: reservation on enqueue, finalize on start, release on fail/cancel.


## Data model (new `subscriptions` Django app)
- Feature  
  - `code` (slug, unique): e.g., `ai_chat_message`  
  - `name`, `description`  
  - `default_window` (enum: day, week, month, rolling, lifetime)  
  - `default_cost_per_use` (int, default=1)

- SubscriptionTier  
  - `code` (slug, unique): e.g., `free`, `pro`, `enterprise`  
  - `name`, `description`  
  - Optional: `is_active`, `sort_order`

- TierFeature (per tier, per feature rule)  
  - FK: `tier` → SubscriptionTier, `feature` → Feature  
  - `access` (enum: OFF, ON)  
  - `limit_type` (enum: unlimited, quota)  
  - `quota_value` (int, nullable)  
  - `window` (enum; defaults to feature default; supports day, week, month, rolling, lifetime)  
  - `soft_limit_percent` (int, e.g., 110 for +10% grace)  
  - `cost_per_use` (int, default=feature default)

- UserSubscription  
  - FK: `user`  
  - FK: `tier`  
  - `status` (enum: ACTIVE, PAST_DUE, CANCELED, GRACE, EXPIRED)  
  - `start_at`, `current_period_end`, `grace_end_at`  
  - `metadata` (JSON)  
  - Index on (`user`, `status` in ACTIVE/GRACE)

- UserEntitlementOverride (optional)  
  - FK: `user`, `feature`  
  - Override fields: `access`, `limit_type`, `quota_value`, `window`, `cost_per_use`  
  - For coupons/promotions/support adjustments.

- UsageEvent (append-only, idempotent)  
  - `id` (uuid)  
  - `user`, `feature`, `cost` (int), `state` (PENDING|CONSUMED|RELEASED)  
  - `idempotency_key` (unique nullable)  
  - `created_at`, `finalized_at` (nullable)  
  - `context` (JSON: e.g., backtest_id, chat_id)

- UsageAggregateDaily  
  - `user`, `feature`, `window_start` (date), `consumed` (int)  
  - Unique (`user`, `feature`, `window_start`)  
  - Used for reports, dashboards, and reconciliation.

Notes
- Keep models small and normalized; heavy writes happen in Redis.  
- DB used for audit and eventual consistency.


## Redis design
- Key format (UTC):  
  - Day counter: `usage:{user_id}:{feature}:day:{YYYYMMDD}`  
  - Week counter: `usage:{user_id}:{feature}:week:{ISOYEAR}{ISOWeek}` (ISO-8601 week)  
  - Month counter (future): `usage:{user_id}:{feature}:month:{YYYYMM}`  
  - Lifetime: prefer DB-backed aggregates; optionally cache in Redis `usage:{user_id}:{feature}:lifetime` without TTL.  
  - Pending reservation: `usage:pending:{idempotency_key}`  
- Value: integer counts; for day/week/month, set EXPIRE to window end + small buffer (e.g., 2 days) for safety. For lifetime, do not expire; rely on DB as source of truth.  
- Lua script (atomic):  
  - Inputs: `key`, `limit`, `cost`, `window_expiry_ts`, `soft_limit`  
  - Steps: read, compute `next = current + cost`, compare to `limit` and `soft_limit`, if allowed then increment and set TTL (when applicable); return (allowed, remaining, limit, window_end).  
- Rolling windows (future): separate key scheme (`YYYYMMDDHHmm` bucketing) or sliding counters; keep design pluggable.  
- Durability and restart behavior:  
  - Dual record all successful consumptions to PostgreSQL as `UsageEvent` (CONSUMED) immediately; this is the authoritative audit log.  
  - Maintain `UsageAggregateDaily/Weekly` tables via scheduled jobs or on-write upserts.  
  - On Redis restart/cache loss: rehydrate counters on demand by reading the current window aggregate from DB (or summing events) and setting Redis to that value with proper TTL. Lifetime quotas are recomputed from DB and optionally cached without TTL.  
  - Optionally enable Redis AOF/RDB persistence to reduce reconstruction events; never rely on Redis as sole source of truth.  
- Degraded mode when Redis is unavailable:  
  - Fallback to DB-only checks by computing current consumption for the active window from `UsageEvent`; slower but correct.  
  - Use a circuit breaker to protect DB; for non-critical features, return 503 if needed.


## Enforcement API (service module)
Location proposal: `subscriptions/services.py`

- `check(user_id, feature_code, cost=1)`  
  - Returns: `{allowed: bool, remaining: int|None, limit: int|None, window_end: datetime|None, reason: str|None}`  
  - Does not mutate counters; fast path for UI.

- `check_and_consume(user_id, feature_code, cost=1, idempotency_key=None, context=None)`  
  - Atomic consume via Redis+Lua; writes UsageEvent (CONSUMED).  
  - Idempotent by `idempotency_key` if provided.

- `reserve(user_id, feature_code, cost=1, idempotency_key, ttl_seconds, context=None)`  
  - Creates a pending reservation if within limit; sets a TTL.  
  - Used for long-running jobs (e.g., backtests) at enqueue time.

- `finalize(idempotency_key)`  
  - Converts a reservation into a consumed usage; updates UsageEvent.

- `release(idempotency_key)`  
  - Cancels a reservation; frees capacity if pre-incremented (we'll prefer post-increment on finalize to avoid compensating decrements).

- `get_usage(user_id)`  
  - Returns a list of features with `remaining`, `limit`, `window_end` for the current window.

Implementation notes
- Gather entitlement (tier + overrides) from DB, cache in Redis (e.g., 5-15 minutes) with cache bust on tier changes.  
- All time computation server-side in UTC.  
- For idempotency, store a small Redis record `usage:idemp:{key}` mapping to last result; avoid double-consumption on retries.


## DRF and task integration
- Decorator for views:  
  - `@require_feature("ai_chat_message", cost=1, mode="consume")`  
  - On deny: HTTP 402/429 with JSON `{detail, remaining, limit, window_end, feature}`.  
  - Mode `check` only for gradual rollout.

- Permission class:  
  - `HasFeaturePermission(feature_code, cost=1, mode="consume")`  
  - Works for class-based views.

- Celery tasks (e.g., backtests):  
  - When enqueueing: `reserve(..., idempotency_key=job_id)`.  
  - On task start: `finalize(job_id)` (atomic consume now).  
  - On failure/cancel: `release(job_id)` or simply let reservation expire if we use post-increment on finalize.


## Initial configuration (tiers and features)
Features  
- `ai_chat_message`: default window=day, cost=1  
- `backtest_run`: default window=week, cost=1  
- `trade_execute`: default window=day (used only for Free tier), cost=1  
- `account_add`: default window=lifetime, cost=1  

Assumptions  
- Account add limits are lifetime (confirmed).  
- UTC time for window boundaries (agreed).  

Tiers (as specified)  
- `free`:  
  - trade_execute: quota 1/day  
  - ai_chat_message: quota 2 lifetime (window=lifetime)  
  - backtest_run: quota 1 lifetime (window=lifetime)  
  - account_add: OFF (0 allowed)  

- `basic`:  
  - trade_execute: unlimited  
  - ai_chat_message: quota 2/day  
  - backtest_run: quota 3/week  
  - account_add: quota 1 lifetime (window=lifetime)  

- `pro`:  
  - trade_execute: unlimited  
  - ai_chat_message: quota 5/day  
  - backtest_run: quota 10/week  
  - account_add: quota 2 lifetime (window=lifetime)  

- `premium`:  
  - All features unlimited


## AI chat specifics
- Now: per-message counting (cost=1 per message) on the message send endpoint.  
- Later: token-based metering  
  - Add `ai_chat_token` feature with cost equal to token count; enforce with rolling or daily window.  
  - Optionally run both: message count as guardrail + token overage on high usage tiers.
- Anti-abuse: per-user burst limits (rate limiting) orthogonal to quotas.


## Observability & admin
- Endpoints  
  - `GET /api/v1/me/usage` → list of features with remaining/limit/window_end  
  - `GET /api/v1/me/subscription` → current tier/status/period  
- Admin screens  
  - ModelAdmin for Feature, SubscriptionTier, TierFeature, UserSubscription, UsageEvent, Aggregates.  
- Alerts  
  - Emit events when users cross 80%/100% usage (email/webhook/log).


## Reconciliation & durability
- Nightly job: roll Redis counters into `UsageAggregateDaily` (upsert) per user-feature.  
- Optional: dual-write a UsageEvent row on every consume; keep it small.
- Reconcile script: compare Redis counter to sum(UsageEvent) within current window; log anomalies.


## Error modes & edge cases
- No active subscription → deny with reason `no_subscription`.  
- Feature not in tier → deny `not_entitled`.  
- Quota exceeded → deny `quota_exceeded`, include `window_end`.  
- Soft overage (<= soft_limit) → allow with `overage=true`, log event for upsell.  
- Concurrency spikes → Redis Lua atomicity prevents over-consumption.  
- Retries/timeouts → idempotency keys ensure exactly-once consumption.


## Security & privacy
- Use server-side clocks only for windows; UTC storage.  
- Sanitize `context` metadata (no secrets).  
- RBAC for admin operations on tiers and overrides.


## Testing strategy
- Unit tests for Lua paths (allow/deny, soft overage, TTL setting).  
- Service tests for `check`, `consume`, idempotency, reservations.  
- Integration tests: DRF decorator on AI chat endpoint; Celery backtest flow.  
- Property tests for window boundary behaviors (e.g., 23:59:59→00:00:01 UTC).


## Rollout plan
1) Create `subscriptions` app with models and admin; seed features/tiers.  
2) Implement entitlements service with Redis and Lua; add basic endpoints (`/me/usage`, `/me/subscription`).  
3) Integrate AI chat send endpoint with `@require_feature("ai_chat_message", mode="consume")`.  
4) Add backtest reservation/finalize; guard backtest creation.  
5) Extend to account add and trade execute paths.  
6) Observability and alerts; admin UX.  
7) Billing integration (Stripe) updating UserSubscription via webhooks; maintain grace periods.


## Minimal API contract (for all call sites)
Request  
- Inputs: `user_id`, `feature_code`, `cost` (int), optional `idempotency_key`, optional `context` (JSON)  
Response  
- `allowed` (bool), `remaining` (int|null), `limit` (int|null), `window_end` (ISO or epoch), `reason` (null|enum)

HTTP behavior (when used via decorator/permission)  
- 200 OK on allowed.  
- 402 Payment Required or 429 Too Many Requests on deny (tunable); error clearly states subscription/entitlement limitation with `reason`=`quota_exceeded|not_entitled|no_subscription`.  
- JSON body includes `feature`, `remaining`, `limit`, `window_end`, `reason`.


## Implementation notes and choices
- Window alignment: use UTC calendar day initially for simplicity; optionally switch to user-local later by tracking timezone.  
- Caching: tier+feature rules cached in Redis for 5–15 minutes; invalidate on admin changes.  
- Reservations: prefer post-increment on finalize to avoid compensating decrements on failure paths.  
- Token-based evolution: introduce parallel feature `ai_chat_token` rather than changing semantics of `ai_chat_message`.  
- Config-driven: adding new feature = create Feature + TierFeature rows; no code change required except where the feature is enforced.


## File/map proposal (to be created in future PRs)
- `subscriptions/apps.py, models.py, admin.py, services.py, decorators.py, permissions.py, urls.py, views.py, tests/`  
- Redis Lua scripts embedded in `services.py` or colocated under `subscriptions/lua/` and loaded at startup.  
- Example enforcement points:  
  - AI: `AI/views.py` send-message endpoint → decorator  
  - Backtests: `analysis/views.py` or enqueue layer → reservation/finalize  
  - Trades: `trading/` or `bots/` services → check/consume  
  - Accounts: `accounts/views.py` add endpoint → check/consume


## Open questions
- Do we prefer 402 or 429 for quota exceeded?  
- Any grace-overage expectations for paid tiers?  
- Window semantics per user timezone for AI chat?  
- What are initial concrete quotas for Free/Pro?

---
This document is the agreed blueprint to proceed with a minimal, robust entitlements core. Billing can attach later by updating `UserSubscription` on webhook events and syncing periods.
