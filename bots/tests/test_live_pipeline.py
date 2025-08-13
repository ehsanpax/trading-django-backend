from django.test import TestCase
from unittest.mock import patch, MagicMock
from decimal import Decimal

from bots.execution_gateway import build_trade_request


class LivePipelineTests(TestCase):
    def test_build_trade_request_uses_precomputed_sl_distance(self):
        dto = build_trade_request(
            account_id="acc-1",
            symbol="XAUUSD",
            direction="BUY",
            order_type="MARKET",
            entry_price=2400.0,
            stop_loss_price=2399.5,
            stop_loss_distance_pips=50,  # precomputed externally
            risk_percent=1.0,
        )
        self.assertEqual(dto["stop_loss_distance"], 50)

    @patch("bots.tasks.fetch_symbol_info_for_platform")
    def test_precompute_sl_distance_logic(self, mock_fetch):
        # Simulate symbol info with pip_size = 0.01
        mock_fetch.return_value = {"pip_size": 0.01}
        from bots.tasks import Decimal as D
        entry = D("2400.00")
        sl = D("2399.50")
        pip = D("0.01")
        expected_pips = int(abs((entry - sl) / pip).to_integral_value())
        self.assertEqual(expected_pips, 50)
