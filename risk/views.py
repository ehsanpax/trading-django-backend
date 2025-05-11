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

    def _get_account(self):
        account_id = self.kwargs.get("account_id")
        return get_object_or_404(
            Account,
            id=account_id,
            user=self.request.user
        )

    def get(self, request, account_id=None):
        try:
            rm = RiskManagement.objects.get(account=self._get_account())
            serializer = self.serializer_class(rm)
            return Response(serializer.data)
        except RiskManagement.DoesNotExist:
            blank = {field: None for field in self.serializer_class.Meta.fields}
            return Response(blank, status=status.HTTP_200_OK)

    def post(self, request, account_id=None):
        account = self._get_account()
        if RiskManagement.objects.filter(account=account).exists():
            return Response(
                {"detail": "Risk settings already exist. Use PUT/PATCH to update."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save(account=account)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, account_id=None):
        return self._upsert(request, partial=False)

    def patch(self, request, account_id=None):
        return self._upsert(request, partial=True)

    def _upsert(self, request, partial):
        account = self._get_account()
        data_keys = set(request.data.keys())

        try:
            instance = RiskManagement.objects.get(account=account)
            created = False
        except RiskManagement.DoesNotExist:
            instance = None
            created = True

        # If we’re updating an existing instance, enforce the 30-day rule…
        if instance and not created:
            # But if the only key in the payload is default_tp_profile_id,
            # we bypass the 30-day guard
            updatable_keys = data_keys - {'default_tp_profile_id'}
            if updatable_keys:
                # there are other fields besides default_tp_profile_id
                if timezone.now() - instance.last_updated < timedelta(days=30):
                    return Response(
                        {"detail": "Risk settings can only be updated once every 30 days."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        # Build serializer (instance may be None → create)
        serializer = self.serializer_class(
            instance,
            data=request.data,
            partial=partial,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        # Ownership check for default_tp_profile
        default_profile = serializer.validated_data.get('default_tp_profile')
        if default_profile and default_profile.user != request.user:
            raise PermissionDenied("Cannot assign a profile you do not own.")

        # Save & pick status code
        rm = serializer.save(account=account)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(self.serializer_class(rm).data, status=status_code)