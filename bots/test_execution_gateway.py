from django.test import TestCase
from unittest.mock import patch, MagicMock
from rest_framework.exceptions import ValidationError
from decimal import Decimal

from bots.execution_gateway import build_trade_request, ExecutionGatewayLocal


class BuildTradeRequestTests(TestCase):
    def setUp(self):
        self.account_id = "11111111-1111-1111-1111-111111111111"

    @patch("bots.execution_gateway.fetch_symbol_info_for_platform")
    def test_sl_distance_from_prices_eurusd_buy(self, mock_fetch):
        mock_fetch.return_value = {"pip_size": 0.0001}
        payload = build_trade_request(
            account_id=self.account_id,
            symbol="EURUSD",
            direction="BUY",
            entry_price=1.2000,
            stop_loss_price=1.1980,
            take_profit_price=1.2050,
            risk_percent=1.0,
            metadata={"reason": "signal"},
        )
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["direction"], "BUY")
        self.assertEqual(payload["order_type"], "MARKET")
        self.assertEqual(payload["stop_loss_distance"], 20)
        self.assertEqual(float(payload["take_profit"]), 1.2050)
        self.assertEqual(int(payload["stop_loss_distance"]), 20)
        self.assertIn("_idempotency_key", payload)

    @patch("bots.execution_gateway.fetch_symbol_info_for_platform")
    def test_sl_distance_from_prices_usdjpy_sell(self, mock_fetch):
        # JPY pair pip size 0.01
        mock_fetch.return_value = {"pip_size": 0.01}
        payload = build_trade_request(
            account_id=self.account_id,
            symbol="USDJPY",
            direction="SELL",
            entry_price=150.10,
            stop_loss_price=150.60,
            risk_percent=0.5,
        )
        self.assertEqual(payload["stop_loss_distance"], 50)
        self.assertEqual(str(payload["risk_percent"]), str(Decimal("0.5")))

    @patch("bots.execution_gateway.fetch_symbol_info_for_platform")
    def test_sl_distance_from_prices_index(self, mock_fetch):
        # Index with pip size 1.0
        mock_fetch.return_value = {"pip_size": 1.0}
        payload = build_trade_request(
            account_id=self.account_id,
            symbol="US30",
            direction="BUY",
            entry_price=38750,
            stop_loss_price=38700,
            take_profit_price=38800,
            risk_percent=2.0,
        )
        self.assertEqual(payload["stop_loss_distance"], 50)
        self.assertEqual(float(payload["take_profit"]), 38800.0)

    def test_requires_sl_distance_or_prices(self):
        with self.assertRaises(ValidationError):
            build_trade_request(
                account_id=self.account_id,
                symbol="EURUSD",
                direction="BUY",
                risk_percent=1.0,
            )

    def test_uses_explicit_sl_distance_when_provided(self):
        payload = build_trade_request(
            account_id=self.account_id,
            symbol="EURUSD",
            direction="BUY",
            stop_loss_distance_pips=30,
            risk_percent=1.0,
        )
        self.assertEqual(payload["stop_loss_distance"], 30)


class ExecutionGatewayLocalTests(TestCase):
    @patch("bots.execution_gateway.TradeService")
    def test_execute_calls_trade_service_and_returns_response(self, MockTradeService):
        user = MagicMock()
        # Configure the mock TradeService instance
        svc_instance = MockTradeService.return_value
        svc_instance.validate.return_value = ("account", Decimal("0.10"), Decimal("1.1980"), Decimal("1.2050"))
        svc_instance.execute_on_broker.return_value = {"broker": "ok"}
        svc_instance.persist.return_value = ("order_obj", "trade_obj")
        svc_instance.build_response.return_value = {"status": "FILLED", "trade_id": "T1"}

        trade_request = {
            "account_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "EURUSD",
            "direction": "BUY",
            "order_type": "MARKET",
            "stop_loss_distance": 20,
            "take_profit": Decimal("1.2050"),
            "risk_percent": Decimal("1.0"),
            "_idempotency_key": "abc123",
        }

        gw = ExecutionGatewayLocal(user)
        out = gw.execute(trade_request)

        MockTradeService.assert_called_once_with(user, trade_request)
        svc_instance.validate.assert_called_once()
        svc_instance.execute_on_broker.assert_called_once()
        svc_instance.persist.assert_called_once()
        svc_instance.build_response.assert_called_once()
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["idempotency_key"], "abc123")
