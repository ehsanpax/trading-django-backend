from .choices import ServiceTypeChoices
from .service_client import BaseServiceClient
from .service_adapter_mapping import MAPPING
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

class ServiceAdapter:
    def __init__(self, account_id: str, service_type: str):
        self.account_id: str = account_id
        self.service_type: str = service_type
        self.client: BaseServiceClient = self.client_class(self.account_id)

    @property
    def client_class(self) -> BaseServiceClient:
        return MAPPING[self.service_type]
    
    def connect(self, password: str) -> MessageOutputData:
        return self.client.connect(password=password)

    def place_trade(self, symbol: str, lot_size: float, direction: str, stop_loss: float, take_profit: float) -> TradeOutputData:
        return self.client.place_trade(symbol=symbol, lot_size=lot_size, direction=direction, stop_loss=stop_loss, take_profit=take_profit)

    def get_position_by_ticket(self, ticket: int) -> PostitionOutputData:
        return self.client.get_position_by_ticket(ticket=ticket)

    def get_account_info(self) -> AccountInfoOutputData:
        return self.client.get_account_info()

    def get_open_positions(self) -> PositionsOutputData:
        return self.client.get_open_positions()

    def get_live_price(self, symbol: str) -> CurrentPriceOutputData:
        return self.client.get_live_price(symbol=symbol)

    def get_symbol_info(self, symbol: str) -> SymbolInfoOutputData:
        return self.client.get_symbol_info(symbol=symbol)

    def close_trade(self, ticket: int, volume: float, symbol: str) -> MessageOutputData:
        return self.client.close_trade(ticket=ticket, volume=volume, symbol=symbol)
    
    def get_closed_deal_profit(self, ticket: int, max_retries=5, delay=2) -> TradeDealProfitOutputData:
        return self.client.get_closed_deal_profit(ticket=ticket, max_retries=max_retries, delay=delay)

    def get_latest_deal_ticket(self, order_ticket: int, max_retries=10, delay=1) -> str:
        return self.client.get_latest_deal_ticket(order_ticket=order_ticket, max_retries=max_retries, delay=delay)
    
    def get_closed_trade_profit(self, order_ticket: int, max_retries=10, delay=2) -> TradeDealProfitOutputData:
        return self.client.get_closed_trade_profit(order_ticket=order_ticket, max_retries=max_retries, delay=delay)

    
        