# risk/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.exceptions import NotFound, PermissionDenied
from django.shortcuts import get_object_or_404
from datetime import timedelta
from django.utils import timezone

from .serializers import RiskManagementSerializer, LotSizeRequestSerializer
from .management import calculate_position_size
from accounts.models import Account
from .models import RiskManagement


class CalculateLotSizeView(APIView):
    """
    Calculates lot size based on provided equity, risk percent, and stop-loss distance.
    Expected JSON:
    {
        "account_id": "some-uuid",
        "equity": 10000.0,
        "risk_percent": 0.5,
        "stop_loss_distance": 50,
        "symbol": "EURUSD",       // optional
        "trade_direction": "BUY"   // optional
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LotSizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        account = get_object_or_404(
            Account,
            id=data.get("account_id"),
            user=request.user
        )

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
                db=None
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


class RiskManagementDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RiskManagementSerializer

    def get_object(self):
        account_id = self.kwargs.get("account_id")
        account = get_object_or_404(
            Account,
            id=account_id,
            user=self.request.user
        )

        defaults = {
            "max_daily_loss": 5,
            "max_trade_risk": 1,
            "max_open_positions": 3,
            "enforce_cooldowns": True,
            "consecutive_loss_limit": 3,
            "cooldown_period": timedelta(minutes=30),
            "max_lot_size": 2,
            "max_open_trades_same_symbol": 1,
            # new defaults
            "risk_percent": 0.30,
            "default_tp_profile": None,
        }
        risk_settings, created = RiskManagement.objects.get_or_create(
            account=account,
            defaults=defaults
        )
        return risk_settings

    def get(self, request, account_id=None):
        instance = self.get_object()
        serializer = self.serializer_class(instance)
        return Response(serializer.data)

    def put(self, request, account_id=None):
        return self._update(request, partial=False)

    def patch(self, request, account_id=None):
        return self._update(request, partial=True)

    def _update(self, request, partial):
        instance = self.get_object()
        now = timezone.now()
        # enforce monthly update limit (e.g. 30 days)
        if now - instance.last_updated < timedelta(days=0.05):
            return Response(
                {"detail": "Risk settings can only be updated once every 30 days."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.serializer_class(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)

        # ensure default_tp_profile, if set, belongs to this user
        default_profile = serializer.validated_data.get('default_tp_profile')
        if default_profile and default_profile.user != request.user:
            raise PermissionDenied("Cannot assign a profile that you do not own.")

        serializer.save()
        return Response(serializer.data)
