from __future__ import annotations
from typing import Any, Dict
from urllib.parse import urlencode

import requests
from django.conf import settings

from .base import TradingProvider


class CTraderProvider(TradingProvider):
    """Delegates to the internal Django proxies that call the cTrader microservice."""

    def _base(self) -> str:
        # Django-hosted API base (public), not the microservice URL
        return settings.API_BASE_URL.rstrip("/") if hasattr(settings, "API_BASE_URL") else "/api"

    def ensure_connected(self, account_id: str) -> Dict[str, Any]:
        url = f"{self._base()}/ctrader/connect/"
        try:
            resp = requests.post(url, json={"account_id": account_id}, timeout=15)
            return resp.json() if resp.content else {"status": resp.status_code}
        except requests.RequestException as e:
            return {"error": str(e)}

    def stream_portfolio_url(self, account_id: str) -> str:
        qs = urlencode({"account_id": account_id})
        return f"{self._base()}/ctrader/stream/portfolio?{qs}"

    def get_positions_snapshot(self, account_id: str) -> Dict[str, Any]:
        # Optional snapshot: reuse existing AllOpenPositions or a new proxy if needed
        # Prefer a dedicated cTrader snapshot endpoint if exposed; fallback to platform-agnostic view
        try:
            # If you have a platform-agnostic snapshot view: /trades/open/live/{account_id}
            url = f"{self._base()}/trades/open/live/{account_id}"
            resp = requests.get(url, timeout=15)
            return resp.json() if resp.content else {"status": resp.status_code}
        except requests.RequestException as e:
            return {"error": str(e)}

    def get_trader(self, account_id: str) -> Dict[str, Any]:
        # If/when you expose a proxy for trader summary, call it here
        try:
            url = f"{self._base()}/ctrader/account/{account_id}/trader"
            resp = requests.get(url, timeout=15)
            return resp.json() if resp.content else {"status": resp.status_code}
        except requests.RequestException as e:
            return {"error": str(e)}
