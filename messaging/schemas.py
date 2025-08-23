from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional
from datetime import datetime

EventType = Literal[
    "position.closed",
    "positions.snapshot",
    "account.info",
    "price.tick",
    "candle.update",
]

@dataclass
class EventEnvelope:
    event_id: str
    event_version: int
    source: Literal["mt5"]
    platform: Literal["MT5"]
    type: EventType
    account_id: str
    broker_login: Optional[str]
    occurred_at: str  # ISO8601
    sent_at: str      # ISO8601
    payload: Dict[str, Any]

# Payload shapes (hints)
# position.closed
# {
#   "position_id": str,
#   "symbol": str,
#   "direction": Literal["BUY","SELL"],
#   "volume": float,
#   "open_time": str,
#   "open_price": float,
#   "close_time": str,
#   "close_price": float,
#   "profit": float,
#   "commission": float,
#   "swap": float,
#   "broker_deal_id": Optional[str],
#   "reason": Optional[str]
# }
# positions.snapshot
# { "open_positions": [ {"ticket": str, "symbol": str, ... } ], "cursor": Optional[str] }
# account.info
# { ... raw account info ... }
# price.tick
# { "symbol": str, "bid": float, "ask": float, "time": str }
# candle.update
# { "symbol": str, "timeframe": str, "candle": {"time": int, "open": float, "high": float, "low": float, "close": float, "volume": int} }
