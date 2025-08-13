import pandas as pd
import logging

logger = logging.getLogger(__name__)

REQUIRED_INDICATORS = [
    {
        "name": "ATR",
        "params": { "length": 20 },
        "output_name": "atr20"
    },
    {
        "name": "ATR",
        "params": { "length": 120 },
        "output_name": "atr120"
    }
]

def run_analysis(df: pd.DataFrame, **params) -> dict:
    """
    Analyzes ATR compression and subsequent breakouts.
    """
    compression_threshold = params.get('compression_threshold', 0.6)
    forward_return_bars = params.get('forward_return_bars', 10)

    # Ensure required columns from indicator calculations exist
    if "atr20" not in df.columns or "atr120" not in df.columns:
        return {"error": "Required indicators (atr20, atr120) not found in DataFrame."}

    # Calculate normalized ATR
    df["atr_norm"] = df["atr20"] / df["atr120"]

    # Condition: compression < threshold
    cond = df["atr_norm"] < compression_threshold
    df["future_r"] = df["close"].shift(-forward_return_bars) / df["close"] - 1
    sample = df.loc[cond & df["future_r"].notna(), "future_r"]

    # Basic stats
    aligned_atr = (df["atr20"] / df["close"]).loc[sample.index]
    hit_rate = (sample.abs() > aligned_atr).mean() * 100
    expectancy = sample.mean() * 100

    # Format results for the frontend
    return {
        "analysis_display_name": "ATR Squeeze Breakout",
        "summary": f"Analysis of ATR compression below {compression_threshold}.",
        "parameters_used": params,
        "components": [
            {
                "type": "key_value_pairs",
                "title": "Statistics",
                "data": [
                    {"key": "Hit Rate", "value": f"{hit_rate:.2f}%"},
                    {"key": "Expectancy", "value": f"{expectancy:.4f}%"},
                    {"key": "Sample Size", "value": len(sample)}
                ]
            },
            {
                "type": "histogram",
                "title": f"{forward_return_bars}-Bar Forward Returns Distribution",
                "data": sample.to_list()
            }
        ]
    }
