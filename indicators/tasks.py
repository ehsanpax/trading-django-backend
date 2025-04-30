# indicators/tasks.py

# ── Shim to restore uppercase NaN for pandas-ta ───────────────────────────────
import numpy as _np
if not hasattr(_np, "NaN"):
    _np.NaN = _np.nan
# ───────────────────────────────────────────────────────────────────────────────

import pandas_ta as ta
from celery import shared_task
from django.conf import settings
from tvDatafeed import TvDatafeed
from trading.models import IndicatorData

@shared_task
def update_indicator_cache():
    tv = TvDatafeed()
    for symbol in settings.INDICATOR_SYMBOLS:
        exchange = settings.SYMBOL_EXCHANGE_MAP[symbol]
        for tf_name, tf_interval in settings.INDICATOR_TIMEFRAMES.items():
            df = tv.get_hist(symbol, exchange, tf_interval, n_bars=500)
            if df is None or df.empty:
                continue

            # now pandas_ta will work without ImportError
            rsi_val = df.ta.rsi(length=14).iloc[-1]
            atr_val = df.ta.atr(length=14).iloc[-1]

            for ind_type, val in [("RSI", rsi_val), ("ATR", atr_val)]:
                pk = f"{symbol}:{tf_name}:{ind_type}"
                IndicatorData.objects.update_or_create(
                    id=pk,
                    defaults={
                        "symbol": symbol,
                        "timeframe": tf_name,
                        "indicator_type": ind_type,
                        "value": float(val),
                    }
                )
