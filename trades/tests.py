from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from unittest.mock import patch
from uuid import uuid4
from decimal import Decimal

from accounts.models import Account
from bots.models import Bot, BotVersion, LiveRun
from trading.models import Trade, Order
from trades.services import TradeService


class FakeConnector:
    def place_trade(self, symbol, lot_size, direction, stop_loss, take_profit, order_type="MARKET", limit_price=None):
        return {
            "status": "filled",
            "order_id": 111111,
            "opened_position_ticket": 111111,
        }

    def get_position_by_ticket(self, ticket):
        return {}


def _payload(account, live_run_id, correlation_id):
    return {
        "account_id": str(account.id),
        "symbol": "EURUSD",
        "direction": "BUY",
        "order_type": "MARKET",
        "limit_price": None,
        "stop_loss_distance": 100,  # pips (validated function just echoes)
        "take_profit": 1.23456,
        "risk_percent": 0.5,
        "reason": "test",
        "rr_ratio": 2.0,
        "projected_profit": 10.0,
        "projected_loss": 5.0,
        "live_run_id": str(live_run_id) if live_run_id else None,
        "bot_version_id": None,
        "correlation_id": str(correlation_id) if correlation_id else None,
    }


class ConcurrencyGuardsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u", password="p")
        self.account = Account.objects.create(user=self.user, name="acc", platform="MT5")
        self.bot = Bot.objects.create(name="b1")
        self.bot_version = BotVersion.objects.create(bot=self.bot, strategy_name="s")
        self.live_run = LiveRun.objects.create(bot_version=self.bot_version, instrument_symbol="EURUSD")

    @patch("trades.services.perform_risk_checks", return_value={})
    @patch("trades.services.fetch_risk_settings", return_value={})
    @patch("trades.services.validate_trade_request", return_value={
        "lot_size": 0.10,
        "stop_loss_price": 1.00000,
        "take_profit_price": 1.20000,
    })
    @patch("trades.services.get_platform_connector", return_value=FakeConnector())
    def test_idempotency_short_circuits_broker_and_persist(self, *_):
        # Pre-create an open trade with same (live_run, correlation_id)
        corr = uuid4()
        existing = Trade.objects.create(
            account=self.account,
            instrument="EURUSD",
            direction="BUY",
            lot_size=Decimal("0.10"),
            remaining_size=Decimal("0.10"),
            entry_price=Decimal("1.10000"),
            stop_loss=Decimal("1.00000"),
            profit_target=Decimal("1.20000"),
            risk_percent=Decimal("0.50"),
            projected_profit=Decimal("10"),
            projected_loss=Decimal("5"),
            rr_ratio=Decimal("2.0"),
            trade_status="open",
            order_id=999999,
            live_run_id=self.live_run.id,
            correlation_id=corr,
        )
        # And an existing order linked to it
        Order.objects.create(
            account=self.account,
            instrument="EURUSD",
            direction="BUY",
            order_type="MARKET",
            volume=Decimal("0.10"),
            stop_loss=Decimal("1.00000"),
            take_profit=Decimal("1.20000"),
            broker_order_id=existing.order_id,
            status=Order.Status.FILLED,
            trade=existing,
        )

        svc = TradeService(self.user, _payload(self.account, self.live_run.id, corr))
        account, lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account, lot, sl, tp)
        self.assertTrue(resp.get("idempotent"))
        order, trade = svc.persist(account, resp, lot, sl, tp)
        self.assertIsNotNone(order)
        self.assertIsNotNone(trade)
        self.assertEqual(trade.id, existing.id)
        self.assertEqual(order.broker_order_id, existing.order_id)

    @patch("trades.services.perform_risk_checks", return_value={})
    @patch("trades.services.fetch_risk_settings", return_value={})
    @patch("trades.services.validate_trade_request", return_value={
        "lot_size": 0.10,
        "stop_loss_price": 1.00000,
        "take_profit_price": 1.20000,
    })
    @patch("trades.services.get_platform_connector", return_value=FakeConnector())
    def test_lock_gate_skips_when_not_acquired(self, *_):
        corr = uuid4()
        payload = _payload(self.account, self.live_run.id, corr)

        class FakeLock:
            def __init__(self, *a, **k):
                self.acquired = False
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("trades.services.RedisLock", FakeLock):
            svc = TradeService(self.user, payload)
            account, lot, sl, tp = svc.validate()
            resp = svc.execute_on_broker(account, lot, sl, tp)
            self.assertEqual(resp.get("status"), "skipped")
            self.assertEqual(resp.get("error"), "LOCK_NOT_ACQUIRED")
            order, trade = svc.persist(account, resp, lot, sl, tp)
            self.assertIsNone(order)
            self.assertIsNone(trade)

    @override_settings(MIN_ENTRY_COOLDOWN_SEC=2)
    @patch("trades.services.perform_risk_checks", return_value={})
    @patch("trades.services.fetch_risk_settings", return_value={})
    @patch("trades.services.validate_trade_request", return_value={
        "lot_size": 0.10,
        "stop_loss_price": 1.00000,
        "take_profit_price": 1.20000,
    })
    @patch("trades.services.get_platform_connector", return_value=FakeConnector())
    def test_cooldown_gate_skips_on_second_attempt(self, *_):
        corr1 = uuid4()
        payload = _payload(self.account, self.live_run.id, corr1)

        class FakeLockOK:
            def __init__(self, *a, **k):
                self.acquired = True
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False

        # First call: no cooldown active, should succeed and mark cooldown
        with patch("trades.services.RedisLock", FakeLockOK), \
             patch("trades.services.is_in_cooldown", return_value=False) as _chk, \
             patch("trades.services.mark_cooldown") as mark_cd:
            svc = TradeService(self.user, payload)
            account, lot, sl, tp = svc.validate()
            resp = svc.execute_on_broker(account, lot, sl, tp)
            self.assertNotEqual(resp.get("status"), "skipped")
            # ensure we attempted to mark cooldown
            mark_cd.assert_called()

        # Second call immediately with a new correlation id (avoid idempotency), cooldown active
        corr2 = uuid4()
        payload2 = _payload(self.account, self.live_run.id, corr2)
        with patch("trades.services.RedisLock", FakeLockOK), \
             patch("trades.services.is_in_cooldown", return_value=True):
            svc2 = TradeService(self.user, payload2)
            account, lot, sl, tp = svc2.validate()
            resp2 = svc2.execute_on_broker(account, lot, sl, tp)
            self.assertEqual(resp2.get("status"), "skipped")
            self.assertEqual(resp2.get("error"), "COOLDOWN_ACTIVE")
