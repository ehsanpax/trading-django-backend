import os
from urllib.parse import urlencode, urlunparse

# It's good practice to get the API key from environment variables or Django settings
# For now, let's assume it might be passed or retrieved from settings.
# CHART_IMG_API_KEY = os.environ.get('CHART_IMG_API_KEY') 
# or from django.conf import settings; CHART_IMG_API_KEY = settings.CHART_IMG_API_KEY

API_BASE_URL = "https://api.chart-img.com/v2/tradingview/advanced-chart"

def build_chart_img_payload(symbol, timeframe, indicator_settings):
    """
    Constructs the JSON payload for the chart-img.com API.
    """
    # indicator_settings = config.indicator_settings # No longer from config object directly
    studies = []

    # EMA
    if indicator_settings.get("emas", {}).get("enabled"):
        ema_config = indicator_settings["emas"]
        for period in ema_config.get("periods", []):
            studies.append({
                "name": "Moving Average Exponential",
                "input": {
                    "length": period,
                    "source": ema_config.get("source", "close"),
                    # Assuming offset, smoothingLine, smoothingLength are not needed for standard EMA
                },
                # Add "override" for colors/styles if needed later
            })

    # DMI
    if indicator_settings.get("dmi", {}).get("enabled"):
        dmi_config = indicator_settings["dmi"]
        studies.append({
            "name": "Directional Movement",
            "input": {
                "in_0": dmi_config.get("di_length", 14),    # DI Length
                "in_1": dmi_config.get("adx_smoothing", 14) # ADX Smoothing
            },
            "override": { # Ensure all components are visible by default
                "+DI.visible": True,
                "-DI.visible": True,
                "ADX.visible": True,
            }
        })

    # Stochastic RSI
    if indicator_settings.get("stoch_rsi", {}).get("enabled"):
        stoch_rsi_config = indicator_settings["stoch_rsi"]
        studies.append({
            "name": "Stochastic RSI",
            "input": {
                "in_0": stoch_rsi_config.get("rsi_length", 14),
                "in_1": stoch_rsi_config.get("stoch_length", 14),
                "in_2": stoch_rsi_config.get("k_smooth", 3),
                "in_3": stoch_rsi_config.get("d_smooth", 3)
            },
            "override": { # Ensure K and D lines are visible
                "%K.visible": True,
                "%D.visible": True,
            }
        })

    payload = {
        "symbol": symbol,
        "interval": timeframe,
        "studies": studies,
        "width": 800,  # Adjusted to meet 800x600 limit
        "height": 600, # Adjusted to meet 800x600 limit
        "theme": "dark" # Default theme, can be configurable
        # Add other parameters like timezone, style, etc. if needed
    }
    return payload
