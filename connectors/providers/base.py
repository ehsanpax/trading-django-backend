from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional


class TradingProvider(ABC):
    """Platform-agnostic provider interface matching MT5 client capabilities."""

    @abstractmethod
    def ensure_connected(self, account_id: str) -> Dict[str, Any]:
        """Ensure a live session for this account. Returns { connected: bool } or error."""
        raise NotImplementedError

    @abstractmethod
    def stream_portfolio_url(self, account_id: str) -> str:
        """Return a URL that the frontend can use for SSE portfolio streaming."""
        raise NotImplementedError

    @abstractmethod
    def get_positions_snapshot(self, account_id: str) -> Dict[str, Any]:
        """Return normalized open positions (snapshot) for the account."""
        raise NotImplementedError

    @abstractmethod
    def get_trader(self, account_id: str) -> Dict[str, Any]:
        """Return normalized trader/account summary (balance/equity/margin/leverage/currency)."""
        raise NotImplementedError

    # Execution stubs (optional to implement now)
    def close_position(self, account_id: str, ticket: str | int, reason: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def reduce_position(self, account_id: str, ticket: str | int, lots: float) -> Dict[str, Any]:
        raise NotImplementedError

    def modify_sltp(self, account_id: str, ticket: str | int, sl: Optional[float], tp: Optional[float]) -> Dict[str, Any]:
        raise NotImplementedError
