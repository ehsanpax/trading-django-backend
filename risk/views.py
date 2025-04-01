# risk/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .serializers import RiskManagementSerializer
from .serializers import LotSizeRequestSerializer
from .management import calculate_position_size
from accounts.models import Account  # Adjust path as needed
from rest_framework import generics, permissions
from .models import RiskManagement
from rest_framework.exceptions import NotFound
from datetime import timedelta
from django.utils import timezone
class CalculateLotSizeView(APIView):
    """
    Calculates lot size based on provided equity, risk percent, and stop-loss distance.
    Expected JSON:
    {
        "account_id": "some-uuid",
        "equity": 10000.0,
        "risk_percent": 0.5,
        "stop_loss_distance": 50,
        "symbol": "EURUSD",         // optional (default "EURUSD")
        "trade_direction": "BUY"      // optional (default "BUY")
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LotSizeRequestSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            # Verify the account exists and belongs to the authenticated user
            account = get_object_or_404(Account, id=data.get("account_id"), user=request.user)
            
            # Validate equity
            if data.get("equity") <= 0:
                return Response({"detail": "Invalid account equity."}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                result = calculate_position_size(
                    account_id=data.get("account_id"),
                    symbol=data.get("symbol"),
                    account_equity=data.get("equity"),
                    risk_percent=data.get("risk_percent"),
                    stop_loss_distance=data.get("stop_loss_distance"),
                    trade_direction=data.get("trade_direction"),
                    db=None  # Pass None or the DB session if needed
                )
            except Exception as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
            if "error" in result:
                return Response({"detail": result["error"]}, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                "lot_size": result["lot_size"],
                "stop_loss_price": result["stop_loss_price"],
                "stop_loss_distance": result["stop_loss_distance"]
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    


class RiskManagementDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RiskManagementSerializer

    def get_object(self):
        account = self.request.user.accounts.first()
        if not account:
            raise NotFound("No account found for the current user.")
        risk_settings, created = RiskManagement.objects.get_or_create(
            account=account,
            defaults={
                "max_daily_loss": 5,
                "max_trade_risk": 1,
                "max_open_positions": 3,
                "enforce_cooldowns": True,
                "consecutive_loss_limit": 3,
                "cooldown_period": timedelta(minutes=30),
                "max_lot_size": 2,
                "max_open_trades_same_symbol": 1,
            }
        )
        return risk_settings

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        now = timezone.now()
        # Only allow update if at least 30 days have passed since the last update.
        if now - instance.last_updated < timedelta(days=0.1):
            return Response(
                {"detail": "Risk settings can only be updated once a month."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().update(request, *args, **kwargs)
