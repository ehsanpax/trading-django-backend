from dataclasses import dataclass
import datetime
from typing import Optional, List

@dataclass
class BaseDataclass:
    message_type: str = "success"
    message: str = None


@dataclass
class TradeOutputData(BaseDataclass):
    order_id: str = None
    deal_id: str = None
    volume: float = None
    direction: str = None
    price: float = None



@dataclass
class PositionOutputData(BaseDataclass):
    trade_id: str = None
    ticket: str = None
    symbol: str = None
    volume: float = None
    price_open: float = None
    sl: float = None
    tp: float = None
    profit: float = None
    comment: str = None
    time: datetime.datetime = None


@dataclass
class AccountInfoOutputData(BaseDataclass):
    balance: float = None
    equity: float = None
    margin: float = None
    free_margin: float = None
    leverage: float = None


@dataclass
class CurrentPriceOutputData(BaseDataclass):
    symbol: str = None
    bid: float = None
    ask: float = None


@dataclass
class SymbolInfoOutputData(BaseDataclass):
    symbol: str = None
    pip_size: float = None
    tick_size: float = None
    contract_size: float = None

@dataclass
class MessageOutputData(BaseDataclass):
    close_price: Optional[float] = None

@dataclass
class TradeDealProfitOutputData(BaseDataclass):
    profit: float


@dataclass
class PositionsOutputData(BaseDataclass):
    positions: List[PositionOutputData]