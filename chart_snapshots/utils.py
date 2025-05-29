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
        ema_overrides_list = ema_config.get("overrides", [])
        for i, period in enumerate(ema_config.get("periods", [])):
            study = {
                "name": "Moving Average Exponential",
                "input": {
                    "length": period,
                    "source": ema_config.get("source", "close"),
                }
            }
            if i < len(ema_overrides_list) and isinstance(ema_overrides_list[i], dict):
                study["override"] = ema_overrides_list[i]
            studies.append(study)

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

    # RSI
    if indicator_settings.get("rsi", {}).get("enabled"):
        rsi_config = indicator_settings["rsi"]
        study_input = {"length": rsi_config.get("length", 14)}
        if rsi_config.get("smoothingLine") and rsi_config.get("smoothingLength"): # Add smoothing if specified
            study_input["smoothingLine"] = rsi_config["smoothingLine"]
            study_input["smoothingLength"] = rsi_config["smoothingLength"]
        studies.append({
            "name": "Relative Strength Index",
            "input": study_input,
            "override": rsi_config.get("overrides", {})
        })

    # MACD
    if indicator_settings.get("macd", {}).get("enabled"):
        macd_config = indicator_settings["macd"]
        studies.append({
            "name": "MACD",
            "input": {
                "in_0": macd_config.get("fast_length", 12),
                "in_1": macd_config.get("slow_length", 26),
                "in_2": macd_config.get("signal_length", 9),
                "in_3": macd_config.get("source", "close")
            },
            "override": macd_config.get("overrides", {})
        })

    # Chaikin Money Flow (CMF)
    if indicator_settings.get("cmf", {}).get("enabled"):
        cmf_config = indicator_settings["cmf"]
        studies.append({
            "name": "Chaikin Money Flow",
            "input": {
                "in_0": cmf_config.get("length", 20)
            },
            "override": cmf_config.get("overrides", {})
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
