from .dataclasses import (
    TradeOutputData, 
    PostitionOutputData, 
    AccountInfoOutputData, 
    CurrentPriceOutputData, 
    SymbolInfoOutputData, 
    MessageOutputData,
    TradeDealProfitOutputData,
    PositionsOutputData
)
from typing import List

class BaseServiceClient:
    """
    Handles connection, login, and trade execution for MT5.
    """
    def __init__(self, account_id: int):
        self.account_id = account_id


    def connect(self, password: str) -> MessageOutputData:
        pass

    def place_trade(self, symbol: str, lot_size: float, direction: str, stop_loss: float, take_profit: float) -> TradeOutputData:
        pass

    def get_position_by_ticket(self, ticket: int) -> PostitionOutputData:
        pass

    def get_account_info(self) -> AccountInfoOutputData:
        pass

    def get_open_positions(self) -> PositionsOutputData:
        pass

    def get_live_price(self, symbol: str) -> CurrentPriceOutputData:
        pass

    def get_symbol_info(self, symbol: str) -> SymbolInfoOutputData:
        pass

    def close_trade(self, ticket: int, volume: float, symbol: str) -> MessageOutputData:
        pass
    
    def get_closed_deal_profit(self, ticket: int, max_retries=5, delay=2) -> TradeDealProfitOutputData:
        pass

    def get_latest_deal_ticket(self, order_ticket: int, max_retries=10, delay=1) -> str:
        pass
    
    def get_closed_trade_profit(self, order_ticket: int, max_retries=10, delay=2) -> TradeDealProfitOutputData:
        pass

