from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from accounts.models import Account
from .services import calculate_equity_curve
from .serializers import EquityDataPointSerializer
from rest_framework.permissions import IsAuthenticated
from datetime import datetime, timedelta

class EquityCurveView(APIView):
    """
    API view to retrieve equity curve data for a given account.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        account = get_object_or_404(Account, id=account_id, user=request.user)
        
        # Recalculate the equity curve each time the endpoint is hit.
        # For a production environment with many trades, this should be
        # moved to a background task (e.g., Celery).
        calculate_equity_curve(account)

        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        time_period = request.query_params.get('period', 'all')

        queryset = account.equity_data.all()

        if start_date_str and end_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str)
                end_date = datetime.fromisoformat(end_date_str)
                queryset = queryset.filter(date__range=(start_date, end_date))
            except ValueError:
                # Handle invalid date format
                pass
        elif time_period != 'all':
            now = datetime.now()
            if time_period == '1m':
                start_date = now - timedelta(days=30)
            elif time_period == '6m':
                start_date = now - timedelta(days=180)
            elif time_period == '1y':
                start_date = now - timedelta(days=365)
            else:
                start_date = None
            
            if start_date:
                queryset = queryset.filter(date__gte=start_date)

        serializer = EquityDataPointSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
