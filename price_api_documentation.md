
# Price Data API Documentation

This document provides the documentation for the `/api/price/chart/data/` endpoint.

## Endpoint

`POST /api/price/chart/data/`

## Request Body

The request body must be a JSON object with the following structure:

```json
{
  "account_id": "your_account_id",
  "symbol": "EURUSD",
  "resolution": "H1",
  "count": 200,
  "start_time": "2023-01-01T00:00:00Z",
  "end_time": "2023-01-10T00:00:00Z",
  "indicators": [
    {
      "name": "IndicatorName",
      "params": {
        "param1": "value1",
        "param2": "value2"
      }
    }
  ]
}
```

**Fields:**

- `account_id` (string, required): The ID of the account.
- `symbol` (string, required): The symbol to fetch data for (e.g., "EURUSD").
- `resolution` (string, required): The timeframe resolution (e.g., "M1", "H1", "D1").
- `count` (integer, optional): The number of candles to retrieve.
- `start_time` (string, optional): The start time for the data range in ISO 8601 format.
- `end_time` (string, optional): The end time for the data range in ISO 8601 format.
- `indicators` (array, optional): A list of indicators to calculate.

**Note:** You must provide either `count` or both `start_time` and `end_time`.

## Response Body

The API returns a JSON object containing the OHLCV data and the calculated indicator data.

```json
{
  "candles": [
    {
      "time": "2023-01-01T00:00:00Z",
      "open": 1.06,
      "high": 1.065,
      "low": 1.055,
      "close": 1.062,
      "volume": 1000,
      "IndicatorName_param1_param2": 45.5
    }
  ]
}
```

## Available Indicators

Below is a list of all available indicators and their parameters.

### Average True Range (`ATR`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `length` | int | The period for the Average True Range calculation. | `14` |

### Exponential Moving Average (`EMA`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `length` | int | The period for the Exponential Moving Average. | `20` |
| `source` | enum | The data column to use for EMA calculation (e.g., 'close', 'open', 'high', 'low'). | `close` |

### Relative Strength Index (`RSI`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `length` | int | Number of periods to use for RSI calculation. | `14` |
| `source` | enum | The data column to use for calculation (e.g., 'close', 'open', 'high', 'low', 'volume'). | `close` |

### Moving Average Convergence Divergence (`MACD`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `fast_period` | int | The period for the fast Exponential Moving Average (EMA). | `12` |
| `slow_period` | int | The period for the slow Exponential Moving Average (EMA). | `26` |
| `signal_period` | int | The period for the Signal Line EMA. | `9` |
| `source` | enum | The data column to use for calculation (e.g., 'close', 'open', 'high', 'low', 'volume'). | `close` |

### Chaikin Money Flow (`CMF`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `length` | int | Number of periods to use for CMF calculation. | `20` |

### Stochastic Momentum Index (`SMI`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `k_length` | int | The number of periods for the %K calculation. | `10` |
| `d_length` | int | The number of periods for the %D (signal line) calculation. | `3` |
| `smoothing_length` | int | The number of periods for the initial smoothing of the SMI. | `3` |
| `source` | enum | The data column to use for SMI calculation (e.g., 'close', 'open', 'high', 'low'). | `close` |

### Stochastic Relative Strength Index (`StochasticRSI`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `rsi_length` | int | Number of periods to use for the initial RSI calculation. | `14` |
| `stoch_length` | int | Number of periods to use for the Stochastic calculation on RSI. | `14` |
| `k_period` | int | Smoothing period for %K line. | `3` |
| `d_period` | int | Smoothing period for %D line (signal line). | `3` |
| `source` | enum | The data column to use for initial RSI calculation (e.g., 'close'). | `close` |

### On-Balance Volume (`OBV`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `source_close` | enum | The data column to use for close price (e.g., 'close'). | `close` |
| `source_volume` | enum | The data column to use for volume (e.g., 'volume'). | `volume` |

### Directional Movement Index (`DMI`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `length` | int | Number of periods to use for DI and ADX calculation. | `14` |

### Daily Levels (`daily_levels`)

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `show_high` | bool | Show the high of the day line. | `True` |
| `high_color` | str | Color for the day's high line. | `green` |
| `high_style` | enum | Line style for the day's high. | `solid` |
| `high_width` | int | Line width for the day's high. | `1` |
| `show_low` | bool | Show the low of the day line. | `True` |
| `low_color` | str | Color for the day's low line. | `red` |
| `low_style` | enum | Line style for the day's low. | `solid` |
| `low_width` | int | Line width for the day's low. | `1` |
| `show_open` | bool | Show the day's open line. | `True` |
| `open_color` | str | Color for the day's open line. | `blue` |
| `open_style` | enum | Line style for the day's open. | `dotted` |
| `open_width` | int | Line width for the day's open. | `1` |
| `show_prev_high` | bool | Show the previous day's high line. | `True` |
| `prev_high_color` | str | Color for the previous day's high line. | `lightgreen` |
| `prev_high_style` | enum | Line style for the previous day's high. | `dashed` |
| `prev_high_width` | int | Line width for the previous day's high. | `1` |
| `show_prev_low` | bool | Show the previous day's low line. | `True` |
| `prev_low_color` | str | Color for the previous day's low line. | `lightcoral` |
| `prev_low_style` | enum | Line style for the previous day's low. | `dashed` |
| `prev_low_width` | int | Line width for the previous day's low. | `1` |

