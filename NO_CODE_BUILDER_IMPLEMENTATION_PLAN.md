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
- **Status:** ✅ Completed
- **Goal:** Ensure any backtest can be perfectly reproduced.
- **Tasks:**
    - [x] **DB:** Add `runtime_fingerprint` (JSONB) and `random_seed` (Integer) to `BacktestRun` model.
    - [x] **Backend:** Create `collect_runtime_fingerprint()` service to capture code/lib versions and hashes.
    - [x] **Task:** Update `run_backtest` to save the fingerprint and use the `random_seed`.
    - [x] **API:** Update launch endpoint to accept `random_seed`.
- **Hooks for Future Phases:**
    - **Validation & Explain:** The `runtime_fingerprint` will be essential for debugging by knowing the exact code that ran.

### Phase 2: Advanced Portfolio Statistics
- **Status:** ✅ Completed
- **Goal:** Provide rich statistical analysis that traders expect.
- **Tasks:**
    - [x] **Analysis Module:** Implement `analysis.metrics.calculate_portfolio_stats()` with Drawdown, Sharpe, Sortino, Profit Factor, Expectancy, etc.
    - [x] **Task:** Integrate the new stats calculation at the end of `run_backtest`.
    - [x] **API:** Expose the new stats in the `BacktestRunSerializer`.
- **Hooks for Future Phases:**
    - **Compare & Export:** The standardized, flat key-value stats will make comparison views and CSV exports trivial.

### Phase 3: Realistic Execution & Fill Model
- **Status:** ✅ Completed
- **Goal:** Increase simulation realism by modeling slippage, commissions, and spreads.
- **Tasks:**
    - [x] **DB:** Create a structured `ExecutionConfig` model (instead of loose JSON) and link it to `BacktestConfig`.
    - [x] **Simulation:** Implement logic to apply spread, slippage, and commissions to trades.
    - [x] **Logging:** Log `intended_price` vs. `fill_price` in the `simulated_trades_log`.
- **Hooks for Future Phases:**
    - **Commission Units & Precision:** The `ExecutionConfig` model will include `commission_units` (Enum) and use `DecimalField` for precision, even if the initial implementation is simple. This avoids schema changes later.

---

## Group 2: Architectural Refactoring for No-Code

This group refactors the core architecture to support a flexible, graph-based no-code system.

### Phase 4: The Indicator Contract
- **Status:** ✅ Completed
- **Goal:** Make every indicator a pure, predictable, and self-describing component.
- **Tasks:**
    - [x] **Core App:** Create a `core` app for shared contracts to decouple `bots` and `indicators`.
    - [x] **Contract:** Define a formal `IndicatorInterface` with `VERSION`, `OUTPUTS`, `PARAMS_SCHEMA`, and a pure `compute()` method.
    - [x] **Refactor:** Migrate all existing indicators to the new contract.
    - [x] **Registry:** The indicator registry must validate all indicators against the contract on startup.
- **Hooks for Future Phases:**
    - **Render vs. Compute Split:** The `PARAMS_SCHEMA` will support a `ui_only=True` flag to separate visual parameters from computational ones from the start.

### Phase 5: The Event-Driven Strategy Engine
- **Status:** ✅ Completed
- **Goal:** Refactor the simulation loop into a formal, extensible event-driven engine.
- **Tasks:**
    - [x] **Engine:** Create a `BacktestEngine` class that emits events (`on_bar_close`, etc.).
    - [x] **Interface:** Define a `StrategyInterface` in the `core` app that the engine uses.
    - [x] **Adapter:** Create an adapter for legacy strategies to make them compatible with the new engine without modification.
    - [x] **Task:** Refactor `run_backtest` to use the new engine.

---

## Group 3: Building the No-Code Layer

This group builds the user-facing no-code tools on top of the solid foundation.

### Phase 6: The Strategy Graph & Compiler
- **Status:** ✅ Completed
- **Goal:** Define the data structure for a no-code strategy and build the compiler that turns it into an executable object.
- **Tasks:**
    - [x] **Schema:** Define a formal JSON Schema for the strategy graph.
    - [x] **DB:** Add `strategy_graph` (JSONField) to the `BotVersion` model.
    - [x] **Compiler:** Build the `GraphCompiler` to validate the graph (topo sort, type checks) and compile it into a `StrategyInterface`-compatible object.
    - [x] **API:** Create an endpoint to save a graph to a `BotVersion`.
- **Hooks for Future Phases:**
    - **Validation & Explain:** The compiler will be the natural place to add static validation. The engine will be designed to collect a `debug_trace` of node values at each step, which will be saved for the "Explain" feature.

### Phase 7: Sectioned UX Support & Engine Gates
- **Status:** 🟡 **In Progress**
- **Goal:** Support the "Entry / Exit / Filters / Risk" UX by creating a lightweight adapter and adding explicit gates to the backtest engine. This allows the frontend to be built against a working backend without waiting for the full graph compiler to be perfect.
- **Tasks:**
    - [x] **`bots/sectioned_adapter.py`:**
        - Create `SectionedStrategySpec` (Pydantic model) to validate the `entry`, `exit`, `filters`, and `risk` sections of the JSON input.
        - Implement `SectionedStrategy(BaseStrategy)` which takes the spec as input.
        - Implement a `required_indicators()` method on the adapter to scan the spec and declare necessary indicators.
        - Implement a pure `run_tick()` method that evaluates the pre-computed indicator data and emits actions.
    - [x] **`bots/base.py`:**
        - Update the `run_tick` docstring to officially list `OPEN_TRADE`, `CLOSE_POSITION`, `REDUCE_POSITION`, `MODIFY_SLTP`.
        - Add and document canonical action schemas (as dicts) in the docstring.
        - Implement `make_open_trade()`, `make_close_position()`, etc., helper functions that validate inputs and return the action dicts.
    - [x] **`bots/tasks.py` & `bots/gates.py`:**
        - Implement `evaluate_filters(...)`, `risk_allows_entry(...)`, and `apply_fill_model(...)` with the specified function signatures.
        - Refactor the main simulation loop to follow the precise order of operations:
            1. Update open positions (SL/TP).
            2. `evaluate_filters`.
            3. `strategy.run_tick`.
            4. Loop actions: apply risk/filter gates to entries, allow exits, apply fill model.
            5. Log outcomes.
        - Add logging hooks to record when an entry is blocked by a filter or risk guard.
    - [x] **`bots/services.py`:**
        - In `StrategyManager.instantiate_strategy`, add a condition for `strategy_name == "SECTIONED_SPEC"`.
        - When matched, import `SectionedStrategy` and instantiate it, passing the parsed `spec`, `risk`, and `filters` configurations from the `strategy_params`.
- **Hooks for Future Phases:**
    - **No-Code Canvas UI (Phase 8):** The frontend will generate a JSON spec that conforms to `SectionedStrategySpec`, providing an immediate, working backend for the visual builder.
    - **Explainability (Phase 9):** The explicit logging of blocked entries (`reason: "risk_max_open"`) provides the raw data needed for the "Explain" feature.

### Phase 8: The No-Code Canvas UI
- **Status:** ⚪️ Pending
- **Goal:** Build the front-end visual tool for creating strategies.
- **Tasks:**
    - [ ] **Frontend:** Implement a canvas UI (e.g., using React Flow).
    - [ ] **Nodes:** Dynamically populate the node palette from the indicator and action registries.
    - [ ] **Integration:** Connect the canvas to the backend to save graphs and launch backtests.

---

## Group 4: Post-MVP Enhancements

These phases can be implemented after the core no-code functionality is live.

### Phase 9: Validation, Explainability & Debugging
- **Status:** ⚪️ Pending
- **Goal:** Build user trust and simplify debugging of no-code strategies.
- **Tasks:**
    - [ ] **Static Validation:** Enhance the `GraphCompiler` to perform deep validation (parameter bounds, time-frame alignment, warm-up periods).
    - [ ] **Explain API:** Create an `/explain` endpoint that retrieves the `debug_trace` for a specific bar time from a `BacktestRun`.
    - [ ] **UI:** Visualize the "explain" data on the canvas, highlighting the path of logic that led to a decision.

### Phase 10: Comparison & Exporting
- **Status:** ⚪️ Pending
- **Goal:** Improve user workflow for analysis and sharing.
- **Tasks:**
    - [ ] **Clone API:** Create a `POST /backtests/<id>/clone/` endpoint.
    - [ ] **Compare API:** Create a `GET /backtests/compare/?ids=[id1,id2]` endpoint.
    - [ ] **Export:** Add functionality to download run artifacts (`equity.csv`, `trades.csv`, `stats.json`).
    - [ ] **UI:** Build the frontend views for comparing runs.



the original plan can be found here: https://chatgpt.com/share/68980939-0008-8005-9a9d-6d150146df3f

Do not attempt to make changes to the frontend directly, instead provide instructions to the user to pass onto the frontend team.
