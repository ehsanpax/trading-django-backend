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
    start_time_str = request.GET.get('start_time')
    end_time_str = request.GET.get('end_time')

    if not all([account_id, symbol, resolution]):
        return JsonResponse({"error": "Missing required parameters: account_id, symbol, resolution"}, status=400)

    if count and (start_time_str or end_time_str):
        return JsonResponse({"error": "Cannot provide both 'count' and 'start_time'/'end_time'. Choose one."}, status=400)

    if not count and not (start_time_str and end_time_str):
        return JsonResponse({"error": "Either 'count' or both 'start_time' and 'end_time' must be provided."}, status=400)

    start_time = None
    end_time = None

    if start_time_str and end_time_str:
        try:
            start_time = datetime.fromisoformat(start_time_str).astimezone(timezone.utc)
            end_time = datetime.fromisoformat(end_time_str).astimezone(timezone.utc)
        except ValueError:
            return JsonResponse({"error": "Invalid datetime format. Use ISO 8601 format (e.g., YYYY-MM-DDTHH:MM:SSZ)."}, status=400)
    elif count:
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

    if start_time and end_time:
        result = client.get_historical_candles(
            symbol=symbol,
            timeframe=resolution,
            start_time=start_time,
            end_time=end_time
        )
    else:
        result = client.get_historical_candles(
            symbol=symbol,
            timeframe=resolution,
            count=count
        )

    if "error" in result:
        return JsonResponse(result, status=500)

    return JsonResponse(result)
