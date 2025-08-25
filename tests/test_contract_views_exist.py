import importlib
import re
import pytest

# --- Contract tests to ensure critical views remain present ---

CRITICAL_VIEW_CLASSES = [
    "OpenPositionsLiveView",
    "AllOpenPositionsLiveView",
    "PendingOrdersView",
    "AllPendingOrdersView",
    "CancelPendingOrderView",
    "UpdateStopLossAPIView",
    "PartialCloseTradeView",
    "SynchronizeAccountTradesView",
    "WatchlistViewSet",
]


def test_trades_views_symbols_exist():
    mod = importlib.import_module("trades.views")
    missing = [name for name in CRITICAL_VIEW_CLASSES if not hasattr(mod, name)]
    assert not missing, f"Missing critical views in trades.views: {missing}"


# --- Minimal async tests for Channels normalization (id -> ticket) ---

@pytest.mark.asyncio
async def test_open_positions_update_normalizes_ticket(monkeypatch):
    from accounts.consumers import AccountConsumer

    received = {}

    async def fake_send_positions_update(self, normalized):
        received["payload"] = normalized

    consumer = AccountConsumer()
    # Patch only the downstream send to capture normalized output
    monkeypatch.setattr(AccountConsumer, "send_positions_update", fake_send_positions_update, raising=True)

    # Event with positions missing 'ticket' but having 'id'
    event = {
        "type": "open_positions_update",
        "open_positions": [
            {"id": 123, "symbol": "EURUSD"},
            {"ticket": 456, "symbol": "GBPUSD"},
        ],
    }

    await consumer.open_positions_update(event)

    payload = received.get("payload")
    assert isinstance(payload, list)
    assert payload[0].get("ticket") == 123
    assert payload[1].get("ticket") == 456


@pytest.mark.asyncio
async def test_pending_orders_update_normalizes_ticket(monkeypatch):
    from accounts.consumers import AccountConsumer

    received = {}

    async def fake_send_combined_update(self, pending_orders=None):
        received["payload"] = pending_orders

    consumer = AccountConsumer()
    monkeypatch.setattr(AccountConsumer, "send_combined_update", fake_send_combined_update, raising=True)

    event = {
        "type": "pending_orders_update",
        "pending_orders": [
            {"id": 789, "symbol": "XAUUSD"},
            {"ticket": 1011, "symbol": "USDJPY"},
        ],
    }

    await consumer.pending_orders_update(event)

    payload = received.get("payload")
    assert isinstance(payload, list)
    assert payload[0].get("ticket") == 789
    assert payload[1].get("ticket") == 1011
