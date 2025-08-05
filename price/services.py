from django.conf import settings
from trading_platform.mt5_api_client import MT5APIClient
from accounts.models import Account, MT5Account
from django.shortcuts import get_object_or_404
from datetime import datetime, timezone

class PriceService:
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
