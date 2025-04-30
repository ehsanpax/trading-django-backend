# trading/utils/targets.py

from decimal import Decimal
from trading.models import Trade
#from indicators.services import fetch_atr  # wherever you store ATR data

def derive_target_price(
    entry_price: Decimal,
    cfg: dict,
    direction: str
) -> Decimal:
    tp_type = cfg["tp_type"]
    sign = Decimal(1) if direction.upper() == "BUY" else Decimal(-1)

    if tp_type == "RR":
        risk_dist = abs(entry_price - cfg["stop_loss_price"])
        # BUY → add, SELL → subtract
        return entry_price + sign * (risk_dist * Decimal(str(cfg["rr"])))

    #elif tp_type == "ATR":
        atr_value = Decimal(str(fetch_atr(cfg["symbol"], cfg["timeframe"])))
        return entry_price + sign * (atr_value * Decimal(str(cfg["atr"])))

    elif tp_type == "PRICE":
        # PRICE is an absolute override; direction doesn't matter
        return Decimal(str(cfg["price"]))

    else:
        raise ValueError(f"Unknown tp_type: {tp_type}")