# Bots Application Documentation

## 1. Introduction
The Bots application is a core component of the trading platform, designed to enable users to define, backtest, and execute automated trading strategies. It provides a robust framework for integrating custom trading logic, managing different versions of strategies, and analyzing their performance both historically and in live market conditions.

## 2. Technical Overview (High-Level)

### Architecture
The Bots app is built on a Django framework, leveraging its ORM for database interactions. Asynchronous tasks, such as backtesting and live trading loops, are handled by Celery, ensuring that long-running operations do not block the main application. Historical market data (OHLCV and Footprint) is stored efficiently in Parquet files and processed using Pandas DataFrames. TimescaleDB is utilized for storing detailed backtest OHLCV and indicator data, optimizing time-series queries.

### Key Components

*   **`Bot`**: Represents a user-defined trading entity. It's a high-level container for different versions of a trading strategy. A Bot can be active or inactive and is associated with a user and optionally an `Account`.
*   **`BotVersion`**: A specific, immutable configuration of a trading strategy and its associated indicators. Each `Bot` can have multiple `BotVersion`s, allowing for iterative development and testing of strategies. It stores the `strategy_name`, `strategy_params` (JSON), and `indicator_configs` (JSON list).
*   **`BacktestConfig`**: Defines the parameters for a historical simulation (backtest) of a `BotVersion`. This includes `timeframe`, `risk_json`, `slippage_ms`, and `slippage_r`.
*   **`BacktestRun`**: Represents a single execution of a backtest based on a `BacktestConfig`. It stores the results of the simulation, including `equity_curve`, `stats` (KPIs), `simulated_trades_log`, and `status`.
*   **`BacktestOhlcvData` & `BacktestIndicatorData`**: Detailed time-series data stored for each `BacktestRun`, allowing for granular charting and analysis of historical price action and indicator values during the backtest. These are designed as TimescaleDB hypertables.
*   **`LiveRun`**: Represents an active or past execution of a `BotVersion` in live market conditions. It tracks the `status` (PENDING, RUNNING, STOPPING, STOPPED, ERROR), `pnl_r`, and `drawdown_r`.
*   **`BaseStrategy`**: An abstract Python class (`bots/base.py`) that all custom trading strategies must inherit from. It defines the interface for strategy parameters, required indicators, and the core `run_tick` logic.
*   **`BaseIndicator`**: An abstract Python class (`bots/base.py`) that all custom technical indicators must inherit from. It defines the interface for indicator parameters and the `calculate` method.
*   **`BotParameter`**: A dataclass (`bots/base.py`) used to define the metadata for parameters of strategies and indicators, including type, display name, description, default value, and optional min/max/step/options.
*   **`StrategyManager`**: A service class (`bots/services.py`) responsible for discovering, validating, and instantiating `BaseStrategy` and `BaseIndicator` implementations from the `STRATEGY_REGISTRY` and `INDICATOR_REGISTRY`. It ensures that provided parameters match the defined schema.
*   **`Celery Tasks`**:
    *   `live_loop` (`bots/tasks.py`): The asynchronous task responsible for executing a `LiveRun`. It continuously fetches market data, feeds it to the instantiated strategy, and processes trade signals.
    *   `run_backtest` (`bots/tasks.py`): The asynchronous task responsible for executing a `BacktestRun`. It loads historical data, simulates trade execution bar-by-bar, calculates P&L, and records performance metrics.
*   **`Data Processing`**: Utilities (`analysis/utils/data_processor.py`) for loading historical OHLCV and footprint data from Parquet files and resampling it to various timeframes required by strategies.

### Data Flow
1.  **User Interaction (Frontend/API)**: Users create `Bot`s and `BotVersion`s via the API (`bots/views.py`). They select a `strategy_name` and provide `strategy_params` and `indicator_configs`.
2.  **Validation**: `StrategyManager` validates the provided parameters against the definitions in the chosen strategy and indicator classes.
3.  **Task Triggering**:
    *   For backtesting, a `BacktestConfig` is created, and `LaunchBacktestAPIView` triggers the `run_backtest` Celery task.
    *   For live trading, a `LiveRun` is created, and `StartLiveRunAPIView` triggers the `live_loop` Celery task.
4.  **Data Loading**: Within the Celery tasks, `analysis/utils/data_processor.py` loads historical OHLCV/footprint data from Parquet files for backtesting, or connects to live data feeds for live trading.
5.  **Strategy Execution**: The loaded data is fed bar-by-bar (or tick-by-tick for live) to an instantiated `BaseStrategy` object. The strategy's `run_tick` method processes the data, calculates indicators (using `BaseIndicator` implementations), and generates trade signals (OPEN_TRADE, CLOSE_TRADE, etc.).
6.  **Result Storage**:
    *   **Backtesting**: `BacktestRun` records are updated with `equity_curve`, `stats`, and `simulated_trades_log`. Detailed OHLCV and indicator data points are saved to `BacktestOhlcvData` and `BacktestIndicatorData` models for charting.
    *   **Live Trading**: `LiveRun` records are updated with status, P&L, and drawdown. Trade execution is handled by external connectors (not detailed here, but implied by `account_id` and `instrument_spec`).

## 3. User Guide: How the Flow Works

### 3.1 Creating a Bot
1.  **Create a new Bot**: A `Bot` is a conceptual container for your trading idea. You give it a name and associate it with your user account.
2.  **Create a Bot Version**: Once a `Bot` exists, you create `BotVersion`s for it. Each version specifies:
    *   **Strategy**: Choose from a list of available strategies (e.g., "EMA Crossover V1").
    *   **Strategy Parameters**: Configure the chosen strategy using its defined parameters (e.g., `fast_ema_period`, `slow_ema_period`). The system will guide you on required types and ranges.
    *   **Indicator Configurations**: Specify which indicators the strategy will use and their parameters (e.g., `[{'name': 'RSI', 'params': {'length': 14}}]`).
    *   **Notes**: Add any descriptive notes for this specific version.
    This allows you to experiment with different settings without losing previous configurations.

### 3.2 Backtesting a Bot
Backtesting allows you to simulate your bot's performance on historical data.
1.  **Create a Backtest Configuration**: For a specific `BotVersion`, define:
    *   **Timeframe**: The chart timeframe for the backtest (e.g., M1, H1, D1).
    *   **Risk Settings**: Custom risk parameters for the simulation.
    *   **Slippage**: Simulated slippage in milliseconds or R-units.
    *   **Label**: A descriptive name for this backtest configuration.
2.  **Launch a Backtest**: Provide the `BacktestConfig` ID, the `instrument_symbol` (e.g., "XAUUSD"), and the `data_window_start` and `data_window_end` dates. The system will queue the backtest for execution.
3.  **View Backtest Results**: Once completed, you can retrieve the `BacktestRun` results, which include:
    *   **Equity Curve**: A time-series of your simulated account balance.
    *   **Key Performance Indicators (KPIs)**: Total trades, net P&L, winning/losing trades, etc.
    *   **Simulated Trades Log**: A detailed log of all simulated entry and exit points.
    *   **Chart Data**: OHLCV data, indicator overlays, and trade markers visualized on a chart.

### 3.3 Running a Bot Live
Live runs execute your bot's strategy in real-time markets.
1.  **Start a Live Run**: Select a `BotVersion` and an `instrument_symbol`. Ensure the associated `Bot` is active and linked to a valid trading `Account`. The system will queue the live run.
2.  **Monitor Live Run Status**: Track the `LiveRun`'s status (PENDING, RUNNING, STOPPING, STOPPED, ERROR) and real-time P&L and drawdown.
3.  **Stop a Live Run**: You can explicitly stop a running bot at any time.

## 4. Standards for Creating New Bots/Strategies and Indicators

### 4.1 General Principles
*   **Modularity**: Strategies and indicators should be self-contained and focused on a single responsibility.
*   **Reusability**: Design indicators to be reusable across multiple strategies.
*   **Parameterization**: All configurable aspects of strategies and indicators must be exposed as `BotParameter`s. Avoid hardcoding values.
*   **Clear Naming**: Use descriptive `NAME` and `DISPLAY_NAME` attributes for strategies and indicators.
*   **Immutability**: `BotVersion`s are designed to be immutable once created to ensure consistent backtest and live run results.

### 4.2 Creating a New Strategy
To create a new trading strategy, you must:
1.  **Create a new Python file** (e.g., `my_strategy.py`) within a designated strategies directory (e.g., `bots/strategies/`).
2.  **Inherit from `bots.base.BaseStrategy`**:
    ```python
    from bots.base import BaseStrategy, BotParameter
    from typing import List, Dict, Any
    import pandas as pd
    # Import necessary indicators or data processing utilities

    class MyCustomStrategy(BaseStrategy):
        NAME = "my_custom_strategy_v1"
        DISPLAY_NAME = "My Custom Strategy (Version 1)"
        DESCRIPTION = "A brief description of what this strategy does."

        PARAMETERS: List[BotParameter] = [
            BotParameter(
                name="period",
                parameter_type="int",
                display_name="Lookback Period",
                description="Number of bars to consider for calculation.",
                default_value=20,
                min_value=5,
                max_value=100,
                step=1
            ),
            BotParameter(
                name="trade_volume",
                parameter_type="float",
                display_name="Trade Volume (Lots)",
                description="Volume to trade per signal.",
                default_value=0.01,
                min_value=0.01,
                step=0.01
            ),
            BotParameter(
                name="signal_type",
                parameter_type="enum",
                display_name="Signal Type",
                description="Type of signal to generate.",
                default_value="CROSS",
                options=["CROSS", "OVERBOUGHT", "OVERSOLD"]
            )
        ]

        REQUIRED_INDICATORS: List[Dict[str, Any]] = [
            {"name": "EMA", "params": {"length": "period"}}, # 'period' refers to strategy parameter
            {"name": "RSI", "params": {"length": 14}}
        ]

        def __init__(self, instrument_symbol: str, account_id: str, instrument_spec: Any, strategy_params: Dict[str, Any], indicator_params: Dict[str, Any], risk_settings: Dict[str, Any]):
            super().__init__(instrument_symbol, account_id, instrument_spec, strategy_params, indicator_params, risk_settings)
            # Access strategy parameters: self.strategy_params['period']
            # Access indicator parameters: self.indicator_params (list of dicts)
            # Access risk settings: self.risk_settings

            # Example: Instantiate required indicators
            # self.ema_indicator = get_indicator_class("EMA")(length=self.strategy_params['period'])
            # self.rsi_indicator = get_indicator_class("RSI")(length=14)

        def run_tick(self, df_current_window: pd.DataFrame, account_equity: float) -> List[Dict[str, Any]]:
            """
            Executes the strategy logic for the current tick/bar.
            `df_current_window` contains historical OHLCV data up to the current bar,
            including any pre-calculated indicator columns.
            `account_equity` is the current simulated equity.
            Returns a list of trade actions (e.g., OPEN_TRADE).
            """
            # Example: Access current bar data
            current_bar = df_current_window.iloc[-1]
            # current_close = current_bar['close']

            # Example: Access indicator values (assuming they are pre-calculated in df_current_window)
            # current_ema = current_bar['EMA_period'] # If EMA was calculated and added as 'EMA_period' column
            # current_rsi = current_bar['RSI_14']

            actions = []
            # Implement your trading logic here
            # Example: if buy_condition:
            #     actions.append({
            #         "action": "OPEN_TRADE",
            #         "details": {
            #             "symbol": self.instrument_symbol,
            #             "direction": "BUY",
            #             "volume": self.strategy_params['trade_volume'],
            #             "price": current_bar['close'], # Or bid/ask
            #             "stop_loss": current_bar['close'] - 10 * self.tick_size,
            #             "take_profit": current_bar['close'] + 20 * self.tick_size,
            #             "comment": "My Strategy Buy"
            #         }
            #     })
            return actions

        def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
            """
            Calculates the minimum number of historical bars required for the strategy
            to operate, considering its own parameters and required indicators.
            """
            # Example: If strategy needs 'period' bars for its own logic, and indicators also need history.
            # Max of all required history + buffer
            max_indicator_history = 0
            # For each indicator in REQUIRED_INDICATORS, get its required_history
            # For example, if EMA(20) and RSI(14) are required, max_indicator_history would be 20.
            
            # This method should dynamically calculate based on self.strategy_params and self.REQUIRED_INDICATORS
            # For simplicity, let's assume it's based on the 'period' parameter for now.
            return self.strategy_params['period'] + buffer_bars

        def get_indicator_column_names(self) -> List[str]:
            """
            Returns a list of column names that this strategy expects to be added to the DataFrame
            by its required indicators. This helps the backtest engine save the correct data.
            """
            # Example: If EMA(20) adds 'EMA_20' and RSI(14) adds 'RSI_14'
            # This should be dynamically generated based on REQUIRED_INDICATORS and their params
            return [f"{ind['name']}_{ind['params']['length']}" for ind in self.REQUIRED_INDICATORS]

    ```
3.  **Register the Strategy**: In an appropriate initialization file (e.g., `bots/__init__.py` or a dedicated `strategies/__init__.py` if you have a sub-package), import your strategy and register it:
    ```python
    # In bots/__init__.py or similar
    from .strategies.my_strategy import MyCustomStrategy
    from .registry import register_strategy

    register_strategy(MyCustomStrategy.NAME, MyCustomStrategy)
    ```

### 4.3 Creating a New Indicator
To create a new technical indicator, you must:
1.  **Create a new Python file** (e.g., `my_indicator.py`) within the `indicators/` directory.
2.  **Inherit from `bots.base.BaseIndicator`**:
    ```python
    from bots.base import BaseIndicator, BotParameter
    from typing import List, Any
    import pandas as pd
    # Import any necessary libraries for calculation (e.g., talib, numpy)

    class MyCustomIndicator(BaseIndicator):
        NAME = "my_custom_indicator_v1"
        DISPLAY_NAME = "My Custom Indicator (Version 1)"
        DESCRIPTION = "A brief description of what this indicator calculates."

        PARAMETERS: List[BotParameter] = [
            BotParameter(
                name="length",
                parameter_type="int",
                display_name="Calculation Length",
                description="Number of bars for indicator calculation.",
                default_value=14,
                min_value=1
            ),
            BotParameter(
                name="smoothing",
                parameter_type="float",
                display_name="Smoothing Factor",
                description="Smoothing factor for the indicator.",
                default_value=2.0,
                min_value=0.1
            )
        ]

        def calculate(self, data: pd.DataFrame, **params) -> pd.Series:
            """
            Calculates the indicator value(s) based on input data and parameters.
            `data` is a Pandas DataFrame containing OHLCV data.
            `params` will contain the values for parameters defined in PARAMETERS.
            Returns a Pandas Series where the index matches the DataFrame's index,
            and values are the calculated indicator values.
            """
            length = params['length']
            smoothing = params['smoothing']
            
            # Ensure 'close' column exists
            if 'close' not in data.columns:
                raise ValueError("Input DataFrame must contain a 'close' column.")

            # Implement your indicator calculation logic here
            # Example: Simple Moving Average
            # indicator_values = data['close'].rolling(window=length).mean()
            
            # Example: More complex calculation
            # indicator_values = some_library.calculate_my_indicator(data['close'], length, smoothing)

            # For multi-value indicators (e.g., MACD with line, signal, hist),
            # you might return a DataFrame with multiple columns, or multiple series.
            # The BacktestIndicatorData model expects single values per row,
            # so you might need to save each component separately (e.g., 'MACD_line', 'MACD_hist').
            
            # For simplicity, return a single Series for now.
            indicator_values = data['close'].rolling(window=length).mean() # Placeholder calculation
            return indicator_values

        def required_history(self, **params) -> int:
            """
            Returns the minimum number of historical bars/data points required
            to calculate this indicator with the given parameters.
            """
            length = params['length']
            return length # For a simple rolling mean, it's just the length

    ```
3.  **Register the Indicator**: In an appropriate initialization file (e.g., `indicators/__init__.py` or `bots/__init__.py`), import your indicator and register it:
    ```python
    # In indicators/__init__.py or similar
    from .my_indicator import MyCustomIndicator
    from bots.registry import register_indicator

    register_indicator(MyCustomIndicator.NAME, MyCustomIndicator)
    ```

### 4.4 Parameter Definition (`BotParameter`)
When defining `PARAMETERS` for strategies and indicators, use the `BotParameter` dataclass:

```python
from bots.base import BotParameter
from typing import List, Any, Literal, Optional

@dataclass
class BotParameter:
    name: str # Internal programmatic name (e.g., "fast_ema_period")
    parameter_type: Literal["int", "float", "str", "bool", "enum"] # Data type for validation
    display_name: str # User-friendly name (e.g., "Fast EMA Period")
    description: str # Explanation for the user
    default_value: Any # Default value if not provided
    min_value: Optional[Any] = None # Minimum allowed value (for int/float)
    max_value: Optional[Any] = None # Maximum allowed value (for int/float)
    step: Optional[Any] = None # Step increment for UI (for int/float)
    options: Optional[List[Any]] = None # List of allowed values (for enum)
```

### 4.5 Data Handling
*   **Pandas DataFrames**: Strategies and indicators primarily interact with market data provided as Pandas DataFrames. These DataFrames will have a `DatetimeIndex` and columns for OHLCV (`open`, `high`, `low`, `close`, `volume`).
*   **OHLCV Data**: Standard Open, High, Low, Close, Volume data.
*   **Footprint Data**: May include additional columns like `delta`, `buy_volume`, `sell_volume` for more advanced analysis. Strategies should be designed to gracefully handle the presence or absence of these columns if they are optional.
*   **Indicator Columns**: When indicators are calculated, their results are typically added as new columns to the DataFrame passed to the strategy (e.g., `df['EMA_20']`, `df['RSI_14']`). Strategies should reference these columns by their expected names.
