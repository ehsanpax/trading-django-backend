from django.http import JsonResponse
from datetime import datetime, timezone
from .services import PriceService
from indicators.services import IndicatorService
import pandas as pd
import json
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from accounts.models import Account
from django.db.models import Q
import uuid
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import status, permissions

class ListAccountsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]


class CandleViewset(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

    def get(self, request, *args, **kwargs):
        account_id = request.GET.get('account_id')
        symbol = request.GET.get('symbol')
        resolution = request.GET.get('resolution')
        count = request.GET.get('count')
        start_time_str = request.GET.get('start_time')
        end_time_str = request.GET.get('end_time')

        try:
            account_id = uuid.UUID(account_id, version=4)
            account = Account.objects.filter(id=account_id, user=request.user).first()
        except Exception:
            account = Account.objects.filter(name__iexact=str(account_id), user=request.user).first()        
        
        account_id = account.id

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

        price_service = PriceService()
        result = price_service.get_historical_data(
            account_id=account_id,
            symbol=symbol,
            timeframe=resolution,
            start_time=start_time,
            end_time=end_time,
            count=count
        )

        if "error" in result:
            return JsonResponse(result, status=500)

        return JsonResponse(result)


class ChartViewset(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication, JWTAuthentication]

    @csrf_exempt
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            account_id = data.get('account_id')
            symbol = data.get('symbol')
            resolution = data.get('resolution')
            count = data.get('count')
            start_time_str = data.get('start_time')
            end_time_str = data.get('end_time')
            indicators_config = data.get('indicators', [])
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
        try:
            account_id = uuid.UUID(account_id, version=4)
            account = Account.objects.filter(id=account_id, user=request.user).first()
        except Exception:
            account = Account.objects.filter(name__iexact=str(account_id), user=request.user).first()   
        
        account_id = account.id

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

        warm_up_period = 0
        if indicators_config:
            for config in indicators_config:
                params = config.get('params', {})
                if 'period' in params:
                    warm_up_period = max(warm_up_period, params['period'])
                elif 'length' in params:
                    warm_up_period = max(warm_up_period, params['length'])

        fetch_count = count + warm_up_period if count else None

        price_service = PriceService()
        ohlcv_data = price_service.get_historical_data(
            account_id=account_id,
            symbol=symbol,
            timeframe=resolution,
            start_time=start_time,
            end_time=end_time,
            count=fetch_count
        )

        if "error" in ohlcv_data:
            return JsonResponse(ohlcv_data, status=500)

        if not ohlcv_data.get('candles'):
            return JsonResponse({"candles": []})

        df = pd.DataFrame(ohlcv_data['candles'])
        df['time'] = pd.to_datetime(df['time'], unit='s')

        indicator_service = IndicatorService()
        for indicator_config in indicators_config:
            indicator_name = indicator_config.get('name')
            params = indicator_config.get('params', {})
            if indicator_name:
                try:
                    df = indicator_service.calculate_indicator(df, indicator_name, params)
                except ValueError as e:
                    return JsonResponse({"error": str(e)}, status=400)

        if count:
            df = df.tail(count)

        # Convert DataFrame back to list of dictionaries
        df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        result_candles = df.to_dict(orient='records')

        return JsonResponse({"candles": result_candles})
