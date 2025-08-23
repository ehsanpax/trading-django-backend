# Sectioned Bot Builder – Phase 9: Validation, Explainability & Debugging

Owner: Backend (Bots)
Date: 2025-08-18
Scope: SectionedStrategy (no-code builder) and BacktestEngine

Summary
- Implement deep static validation for sectioned strategy specs.
- Add structured, per-bar decision tracing with low overhead.
- Persist traces for backtests; add explain API for UI.
- Provide ops tooling, sampling, and performance safeguards.

Success Criteria
- Invalid specs are rejected with actionable errors before run-time.
- For any backtest bar, the system can explain why an entry/exit occurred or not.
- Trace retrieval API returns structured, filtered decision paths in <200ms for typical queries.
- Overhead of tracing (enabled) adds <20% wall-clock time on 100k-bar runs; when disabled, near-zero overhead.

In-Scope Files
- bots/sectioned_adapter.py (SectionedStrategy)
- bots/engine.py (BacktestEngine)
- bots/gates.py (filters/risk/fill)
- bots/models.py (BacktestRun, new trace model)
- bots/tasks.py (run_backtest orchestration)
- bots/services.py (validation entry points)
- bots/views.py (BacktestRunViewSet actions for explain/trace)

Milestones & Tasks
1) Static Spec Validation (backend-only)
- Create validator: bots/validation/sectioned.py
  - validate_sectioned_spec(spec: dict) -> list[Issue]
  - Checks:
    - Indicators referenced exist and are supported (name, timeframe, output keys).
    - Parameters and operator compatibility (>, <, cross_over, between, etc.).
    - Output key existence and type for each indicator.
    - Risk schema completeness (position sizing, SL/TP, RR, max concurrent positions, etc.).
    - Timeframe consistency; compute warmup bars needed.
    - Reserved keywords, naming collisions, dangling references.
  - Normalization:
    - Normalize operators and operands (e.g., string to enum), coerce numeric types, resolve defaults.
- Integrate with StrategyManager before run creation.
- Add unit tests for representative valid/invalid specs.

2) Instrumentation Hooks (trace collection in-memory)
- SectionedStrategy
  - Add trace_enabled flag and emit_trace(callback) method.
  - At each run_tick:
    - Capture: inputs snapshot (ohlcv, indicator values), condition evals, filter results, risk decisions, order intents, fills, state transition summary.
    - Use compact dicts with stable keys; avoid copying large arrays (only per-bar values).
- BacktestEngine
  - Pass a trace_callback to strategy; capture engine-level events: position open/close, SL/TP triggers, balance/equity delta, partial fills.
- gates.py
  - Emit trace atoms for filter/risk/fill with reason codes and thresholds.
- Sampling & caps
  - Settings: TRACE_MAX_ROWS (default 250k), TRACE_SAMPLING (0,1,N), TRACE_ENABLED_DEFAULT.

3) Persistence (backtests)
- Add model: BacktestDecisionTrace
  - id (PK), backtest_run (FK), ts (datetime), bar_index (int), symbol (str), timeframe (str),
    section (nullable str: entry/exit/filter/risk/fill/engine), kind (str), payload (JSON),
    created_at (auto), idx (optional int for stable order)
  - Indexes: (backtest_run, bar_index), (backtest_run, ts), (backtest_run, section)
- Write path
  - Buffer in memory; bulk_create in batches (e.g., 1k) to minimize DB overhead.
  - Ensure truncation if exceeding TRACE_MAX_ROWS. [done]
  - Log a single warning when truncation starts.
- Retention
  - Optional TTL via scheduled job; management command to purge by run or age.

4) APIs
- GET /api/bots/backtests/{id}/trace
  - Params: bar_index, ts (epoch or ISO), section, kind, limit, offset
  - Returns: { items: [...], count }
- GET /api/bots/backtests/{id}/explain
  - Params: bar_index | ts, include={conditions,filters,risk,orders,fills,state}
  - Returns: structured summary + grouped atoms by section
- Implementation
  - bots/views.py: BacktestRunViewSet actions: trace, explain
  - serializers.py: BacktestDecisionTraceSerializer
  - Permissions: same as backtest read

5) Frontend Contracts (for UI team)
- Trace Item (example)
  {
    "ts": "2024-01-01T00:00:00Z",
    "bar_index": 1234,
    "symbol": "EURUSD",
    "timeframe": "M5",
    "section": "filter|risk|entry|exit|fill|engine",
    "kind": "condition_eval|order_intent|result|blocked|entry|exit|reduce|modify_sltp",
    "payload": { "...": "..." },
    "idx": 1
  }
- Explain Response (example)
  {
    "bar_index": 1234,
    "symbol": "EURUSD",
    "timeframe": "M5",
    "summary": {
      "action": "no_entry",
      "reason": "Filter blocked: session_closed"
    },
    "path": [ ... trace items grouped by section ... ],
    "state": { "position": null, "balance": 10000.0 }
  }

6) DevOps & Controls
- Settings/env vars
  - BOTS_TRACE_ENABLED_DEFAULT=false
  - BOTS_TRACE_MAX_ROWS=250000
  - BOTS_TRACE_BATCH_SIZE=1000
  - BOTS_TRACE_SAMPLING=1
- Management commands
  - bots_purge_traces --run <id> | --older-than <days>
  - bots_trace_stats --run <id>

7) Performance Testing
- Datasets: 10k, 100k, 1M bars synthetic + 3 real symbols
- Measure with and without tracing; assert thresholds in CI.
- Fallback to sampling or section-filtered tracing if limits exceeded.

8) QA & Acceptance
- Golden test specs (small) with deterministic outcomes and expected decision paths.
- API contract tests for trace/explain endpoints.
- Schema migration tests for BacktestDecisionTrace.

Rollout Plan
- Phase A (internal): enable tracing only in test runs.
- Phase B (beta): allow tracing for on-demand user backtests with sampling.
- Phase C (GA): enable explain API broadly; keep tracing default off for prod.

Risks & Mitigations
- DB bloat: enforce caps, TTL, purging commands.
- Performance regressions: sampling, batching, feature flags.
- Schema churn: isolate model in its own app table, version payloads with kind.

Open Questions
- Do we need live-run traces now, or only backtests? (Default: backtests only)
- Preferred storage: DB vs object store for very large runs? (Start with DB)
- Multi-symbol runs: include symbol/timeframe on every row? (Yes)

Status Tracker
- [x] Design sign-off (backend, frontend)
- [x] Validator scaffold (bots/validation/sectioned.py)
- [x] Integrate validator in StrategyManager
- [x] Add trace hooks in SectionedStrategy
- [x] Add engine/gates trace atoms
- [x] BacktestDecisionTrace model + migration
- [x] Bulk persistence path
- [x] Caps/limits enforcement
- [x] Trace API endpoint
- [x] Explain API endpoint
- [x] Unit tests (validator, trace, explain)
- [x] Performance benchmarks
- [x] Ops commands + docs

Changelog
- 2025-08-18: Initial document created.
- 2025-08-18: Added validator scaffold at bots/validation/sectioned.py
- 2025-08-18: Integrated validator into StrategyManager; added BacktestDecisionTrace model. Cleaned up migrations (kept 0011, removed 000X and merge).
- 2025-08-18: Implemented SectionedStrategy trace hooks and engine/gates trace atoms; added BacktestEngine bulk persistence of BacktestDecisionTrace with batching and sampling (caps pending).
- 2025-08-18: Added trace/explain API endpoints with basic filters and grouping.
- 2025-08-18: Enforced trace caps and batching by settings; truncates in-memory and on write with a single warning.
- 2025-08-18: Phase 9 accepted as complete (100%); status updated accordingly.
