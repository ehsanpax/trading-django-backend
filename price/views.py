from django.http import JsonResponse
from django.conf import settings
from trading_platform.mt5_api_client import MT5APIClient
from datetime import datetime, timedelta, timezone
from accounts.models import Account, MT5Account
from django.shortcuts import get_object_or_404

def get_historical_candles(request):
    account_id = request.GET.get('account_id')
    symbol = request.GET.get('symbol')
    resolution = request.GET.get('resolution')
    count = request.GET.get('count')

    if not all([account_id, symbol, resolution, count]):
        return JsonResponse({"error": "Missing required parameters"}, status=400)

    try:
        count = int(count)
    except ValueError:
        return JsonResponse({"error": "Invalid count format"}, status=400)

    account = get_object_or_404(Account, id=account_id)
    mt5_account = get_object_or_404(MT5Account, account=account)

    client = MT5APIClient(
        base_url=settings.MT5_API_BASE_URL,
        account_id=mt5_account.account_number,
        password=mt5_account.encrypted_password,
        broker_server=mt5_account.broker_server,
        internal_account_id=str(account.id)
    )

    result = client.get_historical_candles(
        symbol=symbol,
        timeframe=resolution,
        count=count
    )

    if "error" in result:
        return JsonResponse(result, status=500)

    return JsonResponse(result)
