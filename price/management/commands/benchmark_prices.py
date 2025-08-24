import os
import time
from django.core.management.base import BaseCommand, CommandError
from accounts.models import Account
from connectors.trading_service import TradingService

class Command(BaseCommand):
    help = "Benchmark live price retrieval via cache vs direct HTTP for an account+symbol"

    def add_arguments(self, parser):
        parser.add_argument('--account', required=True, help='Account UUID (internal)')
        parser.add_argument('--symbol', required=True, help='Symbol e.g. EURUSD')
        parser.add_argument('--runs', type=int, default=5, help='Number of runs per method')
        parser.add_argument('--fresh-throttle-ms', type=int, default=250, help='Sleep between runs to avoid coalescing')

    def handle(self, *args, **options):
        account_id = options['account']
        symbol = options['symbol']
        runs = int(options['runs'])
        gap_ms = int(options['fresh_throttle_ms'])

        acc = Account.objects.filter(id=account_id).first()
        if not acc:
            raise CommandError(f"Account not found: {account_id}")

        ts = TradingService(acc)

        def _bench(method: str):
            if method == 'cache':
                os.environ['PRICE_BYPASS_CACHE'] = '0'
            elif method == 'http':
                os.environ['PRICE_BYPASS_CACHE'] = '1'
            else:
                raise ValueError('method must be cache or http')
            os.environ['PRICE_TIMING_ENABLED'] = '0'  # avoid double-logging
            times = []
            for i in range(runs):
                t0 = time.perf_counter()
                try:
                    out = ts.get_live_price_sync(symbol)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Run {i+1} failed: {e}"))
                    continue
                dt = (time.perf_counter() - t0) * 1000.0
                times.append(dt)
                self.stdout.write(f"{method.upper()} run={i+1} ms={dt:.1f} bid={out.get('bid')} ask={out.get('ask')}")
                time.sleep(gap_ms / 1000.0)
            return times

        cache_times = _bench('cache')
        http_times = _bench('http')

        def stats(arr):
            if not arr:
                return 'n/a'
            arr = sorted(arr)
            n = len(arr)
            p50 = arr[n//2]
            p90 = arr[int(n*0.9)-1 if n>1 else 0]
            return f"n={n} avg={sum(arr)/n:.1f} ms p50={p50:.1f} ms p90={p90:.1f} ms min={arr[0]:.1f} ms max={arr[-1]:.1f} ms"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"CACHE   -> {stats(cache_times)}"))
        self.stdout.write(self.style.SUCCESS(f"HTTP    -> {stats(http_times)}"))
        self.stdout.write(self.style.NOTICE("Tip: keep UI or publisher running so cache has fresh ticks for a fair comparison."))
