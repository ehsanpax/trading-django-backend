import os
from django.core.management.base import BaseCommand
from bots.registry import INDICATOR_REGISTRY

class Command(BaseCommand):
    help = 'Generates API documentation for the price data endpoint.'

    def handle(self, *args, **options):
        doc_content = self.generate_markdown(INDICATOR_REGISTRY)

        doc_path = 'price_api_documentation.md'
        with open(doc_path, 'w') as f:
            f.write(doc_content)

        self.stdout.write(self.style.SUCCESS(f'Successfully generated API documentation at {doc_path}'))

    def generate_markdown(self, indicators):
        md = """
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

"""
        for name, indicator_class in indicators.items():
            display_name = getattr(indicator_class, 'DISPLAY_NAME', name)
            parameters = getattr(indicator_class, 'PARAMETERS', [])
            md += f"### {display_name} (`{name}`)\n\n"
            if parameters:
                md += "| Parameter | Type | Description | Default |\n"
                md += "|-----------|------|-------------|---------|\n"
                for p in parameters:
                    md += f"| `{p.name}` | {p.parameter_type} | {p.description} | `{p.default_value}` |\n"
                md += "\n"
            else:
                md += "This indicator does not require any parameters.\n\n"

        return md
