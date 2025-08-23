# Sectioned No‑Code Bot Builder – Backend Flow and Components

This document explains how a bot created with the Sectioned (no‑code) builder runs through the backend, which components are involved, and how they are glued together.

## What is the Sectioned builder?
A Sectioned strategy is defined entirely by a JSON spec with four logical sections (entry/exit for long/short), plus optional filters and risk. In the backend this strategy is implemented by `SectionedStrategy` and is selected with `strategy_name = "SECTIONED_SPEC"`.

Key files:
- `bots/sectioned_adapter.py` – SectionedStrategy adapter and spec evaluation
- `bots/base.py` – BaseStrategy API, indicator calculation, action helpers
- `bots/services.py` – StrategyManager, creates strategy instances and launches runs
- `bots/tasks.py` – Celery tasks for backtests and live runs
- `bots/engine.py` – Event‑driven backtest engine and execution model
- `bots/gates.py` – Filter and risk gate helpers, fill/slippage model
- `bots/views.py` – REST endpoints to create versions, configs, and runs
- `bots/models.py` – Bot/BotVersion/BacktestConfig/BacktestRun/LiveRun and data tables

## Data model and how to create a Sectioned bot
1. Create a `Bot` (container): `POST /bots/`.
2. Create a `BotVersion` with `strategy_name = "SECTIONED_SPEC"` and put the spec into `strategy_params.sectioned_spec`. Optional `strategy_params.filters` and `strategy_params.risk` can be provided too.
   - Model: `bots.models.BotVersion(strategy_name, strategy_params, indicator_configs=[])`.
3. Create a `BacktestConfig` for that version: timeframe, risk overrides, execution config (slippage/spread/commission).
4. Launch a `BacktestRun` for a symbol and date window, or create a `LiveRun` for execution.

Spec shape (simplified):
- `entry_long`, `entry_short`, `exit_long`, `exit_short` – logical trees using operators and operands. Each comparison node has `op`, `lhs`, `rhs` where operands can be:
  - indicator: `{ "type": "indicator", "name": "ema", "params": {"length": 20}, "output": "ema" }`
  - literal: `{ "type": "literal", "value": 100 }`
  - column: `"close"` etc.
- `filters` – trading session/day filters (consumed by engine gates)
- `risk` – position sizing inputs and SL/TP config, e.g. `{ "risk_pct": 0.01, "sl": {"type": "atr", "mult": 1.5} }`

Example minimal `strategy_params` payload:
```json
{
  "sectioned_spec": {
    "entry_long": {"op": "crosses_above", "lhs": {"type": "indicator", "name": "ema", "params": {"length": 9}}, "rhs": {"type": "indicator", "name": "ema", "params": {"length": 21}}},
    "entry_short": {"op": "crosses_below", "lhs": {"type": "indicator", "name": "ema", "params": {"length": 9}}, "rhs": {"type": "indicator", "name": "ema", "params": {"length": 21}}},
    "exit_long": {"op": "crosses_below", "lhs": {"type": "indicator", "name": "ema", "params": {"length": 9}}, "rhs": {"type": "indicator", "name": "ema", "params": {"length": 21}}},
    "exit_short": {"op": "crosses_above", "lhs": {"type": "indicator", "name": "ema", "params": {"length": 9}}, "rhs": {"type": "indicator", "name": "ema", "params": {"length": 21}}},
    "filters": {"allowed_days_of_week": [0,1,2,3,4]},
    "risk": {"risk_pct": 0.01, "sl": {"type": "atr", "mult": 1.5}, "take_profit_pips": 200}
  }
}
```

## Runtime glue and execution flow

1. Strategy instantiation
   - `StrategyManager.instantiate_strategy()` returns `SectionedStrategy` when `strategy_name == "SECTIONED_SPEC"`.
   - The SectionedStrategy loads `strategy_params.sectioned_spec` into a `SectionedStrategySpec` and reads `risk`/`filters`.

2. Discover required indicators
   - `SectionedStrategy.required_indicators()` walks all spec trees to collect indicator usages (and adds ATR if risk SL type is ATR).
   - For each indicator it merges PARAMS defaults from `core.registry.indicator_registry` (via `PARAMS_SCHEMA`) with explicit params.
   - Duplicates are removed. The final list becomes `self.REQUIRED_INDICATORS` for indicator calculation.

3. Indicator calculation
   - Before the engine runs, `BaseStrategy._calculate_indicators(df)` computes every indicator in `REQUIRED_INDICATORS`.
   - Column naming: `{indicator_name}_{output_name}_{sorted_param_key_value_pairs}`. Example: `ema_ema_length_21_source_close`.
   - SectionedStrategy also precomputes `indicator_column_names` so the backtest task can persist indicator time‑series.

4. Backtest engine
   - `bots/tasks.py:run_backtest` loads historical data with a warm‑up buffer, resamples, and adds a `tick` column.
   - It instantiates the SectionedStrategy, computes indicators into the DataFrame, trims warm‑up, and initializes `BacktestEngine` with:
     - Execution model: slippage/spread/commission from `ExecutionConfig`
     - Risk/filters: merged from `strategy_params.sectioned_spec.risk` overridden by `BacktestConfig.risk_json`
   - The strategy is wrapped in `LegacyStrategyAdapter`, which calls `legacy_strategy.run_tick(window, engine.equity)` on each bar.

5. Per‑bar simulation loop
   - For each bar:
     - SL/TP checks on open positions
     - Filters gate: `gates.evaluate_filters()` against the current timestamp/row
     - Strategy actions: SectionedStrategy evaluates entry/exit conditions via `_evaluate_condition()` recursively and returns actions
     - Engine processes actions:
       - Entries respect filters and `gates.risk_allows_entry()`; exits bypass filters
       - Fill price via `gates.apply_fill_model()` (spread + slippage)
       - Positions/equity updated; trades appended
   - At end, remaining positions are closed.

6. Position sizing and SL/TP (Sectioned)
   - If `risk.sl.type == "atr"`, SL offset = `ATR * mult` (ATR length assumed 14 unless provided by the indicator default schema). If `%` SL, uses a price percentage.
   - If `risk.risk_pct` is set and SL is present, dynamic sizing computes quantity as: risk_amount / risk_per_lot, using instrument `tick_size`, `tick_value`, `contract_size`.
   - If dynamic sizing is not possible, falls back to `risk.fixed_lot_size`.

7. Persistence and charting
   - `BacktestOhlcvData` – stores OHLCV for the backtest period.
   - `BacktestIndicatorData` – stores each indicator column from `indicator_column_names` (deduped, NaNs dropped).
   - Results saved in `BacktestRun.equity_curve`, `stats`, and `simulated_trades_log`.
   - `BacktestChartDataAPIView` returns OHLCV, grouped indicator series (pane type inferred from registry), and trade markers.

8. Live runs
   - `StartLiveRunAPIView` creates a `LiveRun` and triggers `tasks.live_loop` which instantiates the same strategy. The loop is currently a placeholder to be extended for real feeds and order routing.

## How the SectionedStrategy evaluates conditions
- Operators supported: `AND`, `OR`, `>`, `<`, `crosses_above`, `crosses_below` (common aliases supported).
- Operands: literal numbers, column names (e.g., `"close"`), or an indicator descriptor.
- Robust indicator lookup: tries both `{name}_{output}_{params}` and `{name}_default_{params}`. PARAMS defaults are merged before lookup to match computation.

## Filters and risk gates in the engine
- Filters: days of week and session windows; entries only. Exits always pass.
- Risk gates: max open positions, daily loss guard (compared to the day’s starting equity). Entries only.

## Extending the system
- Add indicators/operators/actions in `core.registry`; ensure each indicator exposes `PARAMS_SCHEMA`, `OUTPUTS`, and an optional `PANE_TYPE`.
- Add new SL/TP or sizing logic by extending `SectionedStrategy._create_trade_action`.
- Improve warm‑up/min bars by implementing `SectionedStrategy.get_min_bars_needed()` from required indicators’ history.

## Gotchas and conventions
- Column naming must match exactly; the helper builds names using sorted params and lower‑case indicator/output names.
- If using ATR in risk, ensure ATR is discoverable (defaults currently assume length 14 if not specified elsewhere).
- Exits bypass filters by design; be aware when defining global filters.
- Backtest warm‑up uses a fixed 200‑bar heuristic based on timeframe; long‑lookback indicators may require more.



## Suggestions to extend flexibility

1. Operators
- crosses_within_n_bars, stays_above_n/stays_below_n
- between/in_range, >=, <=, == with tolerances
- slope/roc/percent_change/distance
- bars_since(condition), count_true_in_lookback

2. Temporal references
- Operand shift: add support for operand.shift (bars ago)
- Rolling transforms on operands: SMA/EMA over an operand (e.g., smooth MACD)
- Windowed predicates: any/all of [last n] bars

3. Multi-timeframe
- Allow operand.timeframe (e.g., H1 EMA in an M5 strategy). Engine loads/resamples HTF data and aligns - - - - columns with a suffix (ema_ema_length_21@H1).
- Sequences and state
- Event chains (A then B within n bars), cool-down bars after entry, max trades/day
- Flags (set on event, clear on other event) to model regimes

4. Risk/position management
- Trailing SL (ATR/percent/structural), break-even rules
- Multi-target TPs and partial exits (emit REDUCE_POSITION)
- Pyramiding/scale-in with caps; per-side risk limits
- Risk SL ATR params in risk.sl.params to override default length

5. Filters
- Volatility filter (ATR threshold), liquidity/spread filter
- News/calendar blackout windows
- Session calendars and holidays

6. Spec ergonomics
- JSON Schema for sectioned_spec with enums, defaults, ranges
- Indicator output picker in UI; templates/snippets for common patterns (MACD cross, Stoch cross, RSI - - - - divergence prebuilt)
- Reason codes and debug traces for condition evaluation (log why a signal did/didn’t fire)

7. Performance/safety
- Compute min bars from required indicators
- Cache indicator series across versions/timeframes
- Guardrail on graph/spec complexity and cycle checks
