# File: ta/services/analyzer.py
# ────────────────────────────────
"""Thin wrapper that fetches OHLCV, calls the LLM via n8n, and stores a row."""

from datetime import datetime, timezone, timedelta
from typing import Tuple

from ta.models import TAAnalysis
from ta.utils import fetch_ohlcv, save_chart_snapshot, sha256_bytes, calc_ttl

CURRENT_PROMPT_VER = 1


# --- LLM & n8n adapters -------------------------------------------------

def build_prompt(symbol: str, timeframe: str, ohlcv):
    return {
        "symbol": symbol,
        "tf": timeframe,
        "ohlcv_tail": ohlcv.tail(200).to_dict("records"),
    }


def call_llm(prompt: dict, image_path: str | None = None) -> dict:
    """Call your n8n workflow or OpenAI directly. Must return JSON like:
    {
        "summary": {
            "trend": "up",
            "confidence": 0.83,
            "signal": "buy",
            ... other stuff ...
        },
        "raw": "full LLM text reply here"
    }
    """
    raise NotImplementedError

# -----------------------------------------------------------------------

def analyze(symbol: str, timeframe: str) -> Tuple[TAAnalysis, bool]:
    ohlcv = fetch_ohlcv(symbol, timeframe)
    candle_ts = ohlcv.iloc[-1]["close_ts"]
    digest = sha256_bytes(ohlcv.tail(1).to_numpy().tobytes())

    existing = TAAnalysis.objects.filter(
        symbol=symbol, timeframe=timeframe, candle_close=candle_ts, data_hash=digest
    ).first()
    if existing:
        return existing, False

    # decide if we need vision
    should_send_image = True  # plug in your gate logic
    img_path = save_chart_snapshot(symbol, timeframe, ohlcv) if should_send_image else None

    prompt = build_prompt(symbol, timeframe, ohlcv)
    result = call_llm(prompt, image_path=img_path)

    summary = result["summary"]
    obj = TAAnalysis.objects.create(
        symbol=symbol,
        timeframe=timeframe,
        candle_close=candle_ts,
        trend=summary["trend"],
        confidence=summary["confidence"],
        signal=summary.get("signal", "none"),
        analysis=summary,
        data_hash=digest,
        version=CURRENT_PROMPT_VER,
        snapshot_url=img_path,
        expires_at=calc_ttl(timeframe),
    )
    return obj, True