import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

import fakeredis

from accounts.models import Account
from bots.models import Bot, BotVersion, LiveRun
from trading.models import Trade, Order
from trades.services import TradeService
from utils import concurrency as concurrency_utils


class FakeConnector:
    def place_trade(self, symbol, lot_size, direction, stop_loss, take_profit, order_type="MARKET", limit_price=None):
        return {
            "status": "filled",
            "order_id": 111111,
            "opened_position_ticket": 111111,
        }

    def get_position_by_ticket(self, ticket):
        return {}


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="u", password="p")


@pytest.fixture
def account(user):
    return Account.objects.create(user=user, name="acc", platform="MT5")


@pytest.fixture
def live_run(db):
    bot = Bot.objects.create(name="b1")
    bv = BotVersion.objects.create(bot=bot, strategy_name="s")
    return LiveRun.objects.create(bot_version=bv, instrument_symbol="EURUSD")


@pytest.fixture
def payload_factory(account, live_run):
    def _build(correlation_id=None):
        return {
            "account_id": str(account.id),
            "symbol": "EURUSD",
            "direction": "BUY",
            "order_type": "MARKET",
            "limit_price": None,
            "stop_loss_distance": 100,
            "take_profit": 1.23456,
            "risk_percent": 0.5,
            "reason": "test",
            "rr_ratio": 2.0,
            "projected_profit": 10.0,
            "projected_loss": 5.0,
            "live_run_id": str(live_run.id),
            "bot_version_id": None,
            "correlation_id": str(correlation_id) if correlation_id else str(uuid.uuid4()),
        }
    return _build


@pytest.fixture
def fake_redis(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(concurrency_utils, "_redis_client", r)
    monkeypatch.setattr(concurrency_utils, "get_redis_client", lambda: r)
    return r


@pytest.mark.django_db
def test_idempotency_short_circuits_broker_and_persist(user, account, live_run, payload_factory):
    corr = uuid.uuid4()
    existing = Trade.objects.create(
        account=account,
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
        live_run_id=live_run.id,
        correlation_id=corr,
    )
    Order.objects.create(
        account=account,
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

    svc = TradeService(user, payload_factory(corr))
    with patch("trades.services.perform_risk_checks", return_value={}), \
         patch("trades.services.fetch_risk_settings", return_value={}), \
         patch("trades.services.validate_trade_request", return_value={
             "lot_size": 0.10,
             "stop_loss_price": 1.00000,
             "take_profit_price": 1.20000,
         }), \
         patch("trades.services.get_platform_connector", return_value=FakeConnector()):
        account_obj, lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account_obj, lot, sl, tp)
        assert resp.get("idempotent")
        order, trade = svc.persist(account_obj, resp, lot, sl, tp)
        assert order is not None
        assert trade is not None
        assert trade.id == existing.id
        assert order.broker_order_id == existing.order_id


@pytest.mark.django_db
def test_lock_gate_skips_when_not_acquired(user, account, live_run, payload_factory, fake_redis):
    class FakeLock:
        def __init__(self, *a, **k):
            self.acquired = False
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("trades.services.RedisLock", FakeLock), \
         patch("trades.services.perform_risk_checks", return_value={}), \
         patch("trades.services.fetch_risk_settings", return_value={}), \
         patch("trades.services.validate_trade_request", return_value={
             "lot_size": 0.10,
             "stop_loss_price": 1.00000,
             "take_profit_price": 1.20000,
         }), \
         patch("trades.services.get_platform_connector", return_value=FakeConnector()):
        svc = TradeService(user, payload_factory())
        account_obj, lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account_obj, lot, sl, tp)
        assert resp.get("status") == "skipped"
        assert resp.get("error") == "LOCK_NOT_ACQUIRED"
        order, trade = svc.persist(account_obj, resp, lot, sl, tp)
        assert order is None and trade is None


@pytest.mark.django_db
@override_settings(MIN_ENTRY_COOLDOWN_SEC=2)
def test_cooldown_gate_skips_on_second_attempt(user, account, live_run, payload_factory, fake_redis):
    class FakeLockOK:
        def __init__(self, *a, **k):
            self.acquired = True
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    with patch("trades.services.RedisLock", FakeLockOK), \
         patch("trades.services.perform_risk_checks", return_value={}), \
         patch("trades.services.fetch_risk_settings", return_value={}), \
         patch("trades.services.validate_trade_request", return_value={
             "lot_size": 0.10,
             "stop_loss_price": 1.00000,
             "take_profit_price": 1.20000,
         }), \
         patch("trades.services.get_platform_connector", return_value=FakeConnector()):
        # First call: no cooldown, should pass and mark cooldown
        svc = TradeService(user, payload_factory())
        account_obj, lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account_obj, lot, sl, tp)
        assert resp.get("status") != "skipped"

    # Second call immediately with different correlation to avoid idempotency
    with patch("trades.services.RedisLock", FakeLockOK), \
         patch("trades.services.perform_risk_checks", return_value={}), \
         patch("trades.services.fetch_risk_settings", return_value={}), \
         patch("trades.services.validate_trade_request", return_value={
             "lot_size": 0.10,
             "stop_loss_price": 1.00000,
             "take_profit_price": 1.20000,
         }), \
         patch("trades.services.get_platform_connector", return_value=FakeConnector()), \
         patch("trades.services.is_in_cooldown", return_value=True):
        svc2 = TradeService(user, payload_factory())
        account_obj, lot, sl, tp = svc2.validate()
        resp2 = svc2.execute_on_broker(account_obj, lot, sl, tp)
        assert resp2.get("status") == "skipped"
        assert resp2.get("error") == "COOLDOWN_ACTIVE"
