from connectors.trading_service import TradingService
from accounts.models import Account
import pprint

# Config
ACCOUNT_ID = 'dceebe48-495d-490a-8648-565daa594eeb'
SYMBOL = 'EURUSD'
TIMEFRAME = 'M1'


def main():
    acc = Account.objects.get(id=ACCOUNT_ID)
    ts = TradingService(acc)

    print('--- Historical candles (last 5) ---')
    candles = ts._run_sync(ts.get_historical_candles(SYMBOL, TIMEFRAME, count=5))
    pprint.pprint(candles)

    print('--- Subscribe/unsubscribe candles ---')
    cb = lambda c: None
    ts._run_sync(ts.subscribe_candles(SYMBOL, TIMEFRAME, cb))
    print('subscribed')
    ts._run_sync(ts.unsubscribe_candles(SYMBOL, TIMEFRAME, cb))
    print('unsubscribed')


if __name__ == '__main__':
    main()
