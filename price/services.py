from django.conf import settings
from trading_platform.mt5_api_client import MT5APIClient
from accounts.models import Account, MT5Account
from connectors.trading_service import TradingService
from django.shortcuts import get_object_or_404
from datetime import datetime, timezone

class PriceService:
    def get_historical_data(self, account_id: str, symbol: str, timeframe: str, start_time: datetime = None, end_time: datetime = None, count: int = None):
        """
        Platform-aware historical OHLCV fetch. Uses MT5 API client for MT5 accounts,
        and TradingService connector path for cTrader accounts.
        Returns consistent payload: { 'candles': [ {time, open, high, low, close, volume} ] }
        """
        account = get_object_or_404(Account, id=account_id)
        # MT5 path
        if (account.platform or "").upper() == 'MT5':
            mt5_account = get_object_or_404(MT5Account, account=account)
            client = MT5APIClient(
                base_url=settings.MT5_API_BASE_URL,
                account_id=mt5_account.account_number,
                password=mt5_account.encrypted_password,
                broker_server=mt5_account.broker_server,
                internal_account_id=str(account.id)
            )
            if start_time and end_time:
                return client.get_historical_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_time=start_time,
                    end_time=end_time
                )
            else:
                return client.get_historical_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    count=count
                )
        # cTrader and others via TradingService
        ts = TradingService(account)
        candles = ts.get_historical_candles_sync(symbol, timeframe, count=count, start_time=start_time, end_time=end_time)
        # Normalize to MT5-like shape: time as epoch seconds
        norm = []
        for c in candles:
            # c['timestamp'] is ISO8601
            try:
                dt = datetime.fromisoformat(c['timestamp'].replace('Z', '+00:00'))
                epoch = int(dt.timestamp())
            except Exception:
                epoch = 0
            norm.append({
                'time': epoch,
                'open': c['open'],
                'high': c['high'],
                'low': c['low'],
                'close': c['close'],
                'volume': c['volume'],
            })
        return { 'candles': norm }
    def get_mt5_historical_data(self, account_id: int, symbol: str, timeframe: str, start_time: datetime = None, end_time: datetime = None, count: int = None):
        """
        Fetches historical OHLCV data from the MT5 API.
        """
        account = get_object_or_404(Account, id=account_id)
        mt5_account = get_object_or_404(MT5Account, account=account)

        client = MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id)
        )

        if start_time and end_time:
            return client.get_historical_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=start_time,
                end_time=end_time
            )
        else:
            return client.get_historical_candles(
                symbol=symbol,
                timeframe=timeframe,
                count=count
            )
