from django.test import TestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
from decimal import Decimal

from accounts.models import Account
from bots.execution import ExecutionAdapter


class ExecutionAdapterSmokeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="botuser", password="x")
        self.account = Account.objects.create(user=self.user, name="Test Acc", platform="cTrader", balance=10000, equity=10000)

    @patch("bots.execution.TradeService")
    @patch("bots.execution.fetch_live_price_for_platform")
    @patch("bots.execution.fetch_symbol_info_for_platform")
    def test_open_trade_smoke(self, mock_symbol_info, mock_live_price, MockTradeService):
        mock_symbol_info.return_value = {"pip_size": 0.0001}
        mock_live_price.return_value = {"bid": 1.1000, "ask": 1.1002}

        svc_instance = MockTradeService.return_value
        # validate() -> (account_obj, final_lot, sl_price, tp_price)
        svc_instance.validate.return_value = (self.account, Decimal("0.10"), Decimal("1.0990"), Decimal("1.1020"))
        svc_instance.execute_on_broker.return_value = {"ok": True, "broker_order_id": "X"}
        svc_instance.persist.return_value = (MagicMock(id=1), MagicMock(id=2))
        svc_instance.build_response.return_value = {"status": "ok", "trade_id": 2}

        adapter = ExecutionAdapter(
            user=self.user,
            default_symbol="EURUSD",
            default_rr=2.0,
            run_metadata={"source": "BOT", "live_run_id": "123", "bot_version_id": "456"},
        )

        res = adapter.open_trade(
            account=self.account,
            symbol="EURUSD",
            side="BUY",
            order_type="MARKET",
            sl=1.0990,
            tp=None,  # let adapter derive TP from RR
            risk_percent=0.5,
            reason="smoke",
        )

        # Result bubbled from TradeService.build_response
        self.assertEqual(res.get("status"), "ok")

        # Constructor called with (user, payload) and payload contains metadata
        self.assertTrue(MockTradeService.called)
        args, kwargs = MockTradeService.call_args
        self.assertEqual(args[0], self.user)
        payload = args[1]
        self.assertEqual(payload.get("account_id"), str(self.account.id))
        self.assertEqual(payload.get("symbol"), "EURUSD")
        self.assertEqual(payload.get("direction"), "BUY")
        self.assertEqual(payload.get("source"), "BOT")
        self.assertEqual(payload.get("live_run_id"), "123")
        self.assertEqual(payload.get("bot_version_id"), "456")

        # Validate core method calls hit TradeService pipeline
        svc_instance.validate.assert_called_once()
        svc_instance.execute_on_broker.assert_called_once()
        svc_instance.persist.assert_called_once()
        svc_instance.build_response.assert_called_once()
