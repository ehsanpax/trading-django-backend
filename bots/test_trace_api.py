from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Account
from bots.models import Bot, BotVersion, BacktestConfig, BacktestRun, BacktestDecisionTrace, ExecutionConfig

User = get_user_model()

class BacktestTraceApiTests(APITestCase):
    def setUp(self):
        # Users
        self.user = User.objects.create_user(username="u1", password="pass")
        self.other = User.objects.create_user(username="u2", password="pass")
        # Auth
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        # Account/Bot
        self.account = Account.objects.create(user=self.user, platform="MT5", name="A1", active=True)
        self.bot = Bot.objects.create(name="B1", account=self.account, created_by=self.user, is_active=True)
        self.botver = BotVersion.objects.create(bot=self.bot, strategy_name="graph_based_strategy", strategy_params={}, indicator_configs=[])
        self.exec_cfg = ExecutionConfig.objects.create(name="exec-default")
        self.cfg = BacktestConfig.objects.create(bot_version=self.botver, bot=self.bot, timeframe='M1', risk_json={}, execution_config=self.exec_cfg)
        self.run = BacktestRun.objects.create(config=self.cfg, instrument_symbol="EURUSD", data_window_start=timezone.now(), data_window_end=timezone.now(), status='completed')
        # Traces
        base_ts = timezone.now()
        BacktestDecisionTrace.objects.bulk_create([
            BacktestDecisionTrace(backtest_run=self.run, ts=base_ts, bar_index=5, symbol="EURUSD", timeframe="M1", section="filter", kind="result", payload={"eligible": False, "reason": "outside_trading_session"}, idx=1),
            BacktestDecisionTrace(backtest_run=self.run, ts=base_ts, bar_index=5, symbol="EURUSD", timeframe="M1", section="risk", kind="blocked", payload={"reason": "max_open_positions"}, idx=2),
            BacktestDecisionTrace(backtest_run=self.run, ts=base_ts, bar_index=5, symbol="EURUSD", timeframe="M1", section="fill", kind="entry", payload={"pos_id": "p1"}, idx=3),
        ])

    def test_trace_list_filters_and_pagination(self):
        url = reverse('bots:backtestrun-trace', kwargs={'pk': self.run.id})
        resp = self.client.get(url, {"bar_index": 5, "limit": 2, "offset": 0})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get("count"), 3)
        self.assertEqual(len(resp.data.get("items", [])), 2)
        # Ensure ordering by idx
        kinds = [it["kind"] for it in resp.data["items"]]
        self.assertEqual(kinds, ["result", "blocked"])  # idx=1 then idx=2

    def test_explain_summary(self):
        url = reverse('bots:backtestrun-explain', kwargs={'pk': self.run.id})
        resp = self.client.get(url, {"bar_index": 5})
        self.assertEqual(resp.status_code, 200)
        summary = resp.data.get("summary", {})
        # There is an entry fill and a risk block; fill entry takes precedence per heuristic
        self.assertEqual(summary.get("action"), "entry")

    def test_permissions(self):
        # other user should not be able to see this run due to queryset scoping; expect 404
        client2 = APIClient()
        client2.force_authenticate(self.other)
        url = reverse('bots:backtestrun-trace', kwargs={'pk': self.run.id})
        resp = client2.get(url, {"bar_index": 5})
        self.assertEqual(resp.status_code, 404)
