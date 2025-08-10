# No-Code Strategy Builder: Implementation Plan & Progress

This document tracks the phased implementation of the no-code strategy builder for the trading platform.

## Status Key
-  статусы:
- ⚪️ **Pending:** Not yet started.
- 🟡 **In Progress:** Actively being worked on.
- ✅ **Completed:** Implemented, tested, and validated.
- 🔵 **Blocked:** Awaiting dependencies.

---

## Group 1: Foundational Improvements (Enhancing Trust & UX)

This group of phases focuses on making the existing backtesting engine more powerful, trustworthy, and ready for serious use.

### Phase 1: Reproducibility & Fingerprinting
- **Status:** ⚪️ Pending
- **Goal:** Ensure any backtest can be perfectly reproduced.
- **Tasks:**
    - [ ] **DB:** Add `runtime_fingerprint` (JSONB) and `random_seed` (Integer) to `BacktestRun` model.
    - [ ] **Backend:** Create `collect_runtime_fingerprint()` service to capture code/lib versions and hashes.
    - [ ] **Task:** Update `run_backtest` to save the fingerprint and use the `random_seed`.
    - [ ] **API:** Update launch endpoint to accept `random_seed`.
- **Hooks for Future Phases:**
    - **Validation & Explain:** The `runtime_fingerprint` will be essential for debugging by knowing the exact code that ran.

### Phase 2: Advanced Portfolio Statistics
- **Status:** ⚪️ Pending
- **Goal:** Provide rich statistical analysis that traders expect.
- **Tasks:**
    - [ ] **Analysis Module:** Implement `analysis.metrics.calculate_portfolio_stats()` with Drawdown, Sharpe, Sortino, Profit Factor, Expectancy, etc.
    - [ ] **Task:** Integrate the new stats calculation at the end of `run_backtest`.
    - [ ] **API:** Expose the new stats in the `BacktestRunSerializer`.
- **Hooks for Future Phases:**
    - **Compare & Export:** The standardized, flat key-value stats will make comparison views and CSV exports trivial.

### Phase 3: Realistic Execution & Fill Model
- **Status:** ⚪️ Pending
- **Goal:** Increase simulation realism by modeling slippage, commissions, and spreads.
- **Tasks:**
    - [ ] **DB:** Create a structured `ExecutionConfig` model (instead of loose JSON) and link it to `BacktestConfig`.
    - [ ] **Simulation:** Implement logic to apply spread, slippage, and commissions to trades.
    - [ ] **Logging:** Log `intended_price` vs. `fill_price` in the `simulated_trades_log`.
- **Hooks for Future Phases:**
    - **Commission Units & Precision:** The `ExecutionConfig` model will include `commission_units` (Enum) and use `DecimalField` for precision, even if the initial implementation is simple. This avoids schema changes later.

---

## Group 2: Architectural Refactoring for No-Code

This group refactors the core architecture to support a flexible, graph-based no-code system.

### Phase 4: The Indicator Contract
- **Status:** ⚪️ Pending
- **Goal:** Make every indicator a pure, predictable, and self-describing component.
- **Tasks:**
    - [ ] **Core App:** Create a `core` app for shared contracts to decouple `bots` and `indicators`.
    - [ ] **Contract:** Define a formal `IndicatorInterface` with `VERSION`, `OUTPUTS`, `PARAMS_SCHEMA`, and a pure `compute()` method.
    - [ ] **Refactor:** Migrate all existing indicators to the new contract.
    - [ ] **Registry:** The indicator registry must validate all indicators against the contract on startup.
- **Hooks for Future Phases:**
    - **Render vs. Compute Split:** The `PARAMS_SCHEMA` will support a `ui_only=True` flag to separate visual parameters from computational ones from the start.

### Phase 5: The Event-Driven Strategy Engine
- **Status:** ⚪️ Pending
- **Goal:** Refactor the simulation loop into a formal, extensible event-driven engine.
- **Tasks:**
    - [ ] **Engine:** Create a `BacktestEngine` class that emits events (`on_bar_close`, etc.).
    - [ ] **Interface:** Define a `StrategyInterface` in the `core` app that the engine uses.
    - [ ] **Adapter:** Create an adapter for legacy strategies to make them compatible with the new engine without modification.
    - [ ] **Task:** Refactor `run_backtest` to use the new engine.

---

## Group 3: Building the No-Code Layer

This group builds the user-facing no-code tools on top of the solid foundation.

### Phase 6: The Strategy Graph & Compiler
- **Status:** ⚪️ Pending
- **Goal:** Define the data structure for a no-code strategy and build the compiler that turns it into an executable object.
- **Tasks:**
    - [ ] **Schema:** Define a formal JSON Schema for the strategy graph.
    - [ ] **DB:** Add `strategy_graph` (JSONField) to the `BotVersion` model.
    - [ ] **Compiler:** Build the `GraphCompiler` to validate the graph (topo sort, type checks) and compile it into a `StrategyInterface`-compatible object.
    - [ ] **API:** Create an endpoint to save a graph to a `BotVersion`.
- **Hooks for Future Phases:**
    - **Validation & Explain:** The compiler will be the natural place to add static validation. The engine will be designed to collect a `debug_trace` of node values at each step, which will be saved for the "Explain" feature.

### Phase 7: The No-Code Canvas UI
- **Status:** ⚪️ Pending
- **Goal:** Build the front-end visual tool for creating strategies.
- **Tasks:**
    - [ ] **Frontend:** Implement a canvas UI (e.g., using React Flow).
    - [ ] **Nodes:** Dynamically populate the node palette from the indicator and action registries.
    - [ ] **Integration:** Connect the canvas to the backend to save graphs and launch backtests.

---

## Group 4: Post-MVP Enhancements

These phases can be implemented after the core no-code functionality is live.

### Phase 8: Validation, Explainability & Debugging
- **Status:** ⚪️ Pending
- **Goal:** Build user trust and simplify debugging of no-code strategies.
- **Tasks:**
    - [ ] **Static Validation:** Enhance the `GraphCompiler` to perform deep validation (parameter bounds, time-frame alignment, warm-up periods).
    - [ ] **Explain API:** Create an `/explain` endpoint that retrieves the `debug_trace` for a specific bar time from a `BacktestRun`.
    - [ ] **UI:** Visualize the "explain" data on the canvas, highlighting the path of logic that led to a decision.

### Phase 9: Comparison & Exporting
- **Status:** ⚪️ Pending
- **Goal:** Improve user workflow for analysis and sharing.
- **Tasks:**
    - [ ] **Clone API:** Create a `POST /backtests/<id>/clone/` endpoint.
    - [ ] **Compare API:** Create a `GET /backtests/compare/?ids=[id1,id2]` endpoint.
    - [ ] **Export:** Add functionality to download run artifacts (`equity.csv`, `trades.csv`, `stats.json`).
    - [ ] **UI:** Build the frontend views for comparing runs.
