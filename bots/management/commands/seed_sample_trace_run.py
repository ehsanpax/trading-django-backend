from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Account
from bots.models import Bot, BotVersion, BacktestConfig, BacktestRun, BacktestDecisionTrace, ExecutionConfig

User = get_user_model()

class Command(BaseCommand):
    help = "Seed a sample BacktestRun with a few decision trace rows for frontend testing."

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='demo')
        parser.add_argument('--symbol', type=str, default='EURUSD')
        parser.add_argument('--timeframe', type=str, default='M1')
        parser.add_argument('--bar_index', type=int, default=5)

    def handle(self, *args, **opts):
        username = opts['username']
        symbol = opts['symbol']
        timeframe = opts['timeframe']
        bar_index = opts['bar_index']

        user, _ = User.objects.get_or_create(username=username, defaults={'email': f'{username}@example.com'})
        user.set_password('pass')
        user.save()

        account, _ = Account.objects.get_or_create(user=user, platform='MT5', name='Demo', defaults={'active': True})
        bot, _ = Bot.objects.get_or_create(name='DemoBot', created_by=user, defaults={'account': account, 'is_active': True})
        botver, _ = BotVersion.objects.get_or_create(bot=bot, strategy_name='graph_based_strategy', defaults={'strategy_params': {}, 'indicator_configs': []})
        exec_cfg, _ = ExecutionConfig.objects.get_or_create(name='exec-default')
        cfg, _ = BacktestConfig.objects.get_or_create(bot_version=botver, bot=bot, timeframe=timeframe, defaults={'risk_json': {}, 'execution_config': exec_cfg, 'label': 'DemoCfg'})
        run = BacktestRun.objects.create(config=cfg, instrument_symbol=symbol, data_window_start=timezone.now(), data_window_end=timezone.now(), status='completed')

        base_ts = timezone.now()
        BacktestDecisionTrace.objects.bulk_create([
            BacktestDecisionTrace(backtest_run=run, ts=base_ts, bar_index=bar_index, symbol=symbol, timeframe=timeframe, section='filter', kind='result', payload={'eligible': False, 'reason': 'outside_trading_session'}, idx=1),
            BacktestDecisionTrace(backtest_run=run, ts=base_ts, bar_index=bar_index, symbol=symbol, timeframe=timeframe, section='risk', kind='blocked', payload={'reason': 'max_open_positions'}, idx=2),
            BacktestDecisionTrace(backtest_run=run, ts=base_ts, bar_index=bar_index, symbol=symbol, timeframe=timeframe, section='fill', kind='entry', payload={'pos_id': 'p1'}, idx=3),
        ])

        self.stdout.write(self.style.SUCCESS(f"Seeded run_id={run.id} for user={user.username} bar_index={bar_index}"))
        self.stdout.write("Use DRF token for this user or login to obtain a token.")
