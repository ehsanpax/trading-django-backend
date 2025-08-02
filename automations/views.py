# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate
import uuid
from decimal import Decimal
from django.db.models import Q
from .serializers import AITradeRequestSerializer
from trades.views import ExecuteTradeView
from accounts.models import Account  # Assuming Account model path
from trades.helpers import fetch_symbol_info_for_platform  # Import the helper
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from trade_journal.models import TradeJournal, TradeJournalAttachment, Trade, Order
import requests
from django.core.files.base import ContentFile
import uuid  # Import uuid for validating trade_id

# Import close_trade_globally
from trades.services import close_trade_globally, TradeService
from trades.serializers import ExecuteTradeOutputSerializer
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from trading.models import Trade  # Import Trade model for DoesNotExist exception
import uuid

class ExecuteAITradeView(APIView):
    """Accepts AI trade payload, injects an account, forwards to ExecuteTradeView."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        print(f"Incoming Request Headers: {request.headers}")  # Log headers
        print(f"Incoming Request Body: {request.data}")  # Log body
        serializer = AITradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        print("Validated Payload ExecuteAITradeView:", payload)
        uuid_account_id = None
        try:
            uuid_account_id = uuid.UUID(payload.get("account_id"), version=4)
        except (ValueError, TypeError):
            pass
        if uuid_account_id:
            account = Account.objects.filter(id=uuid_account_id, user=request.user).first()
        else:
            account = Account.objects.filter(simple_id=int(payload.get("account_id")), user=request.user).first()

        account_id = str(account.id) if account else None
        payload["account_id"] = account_id
        trade_payload = {}
        trade_payload["account_id"] = str(payload.get("account_id"))
        trade_payload["symbol"] = payload.get("symbol")
        trade_payload["direction"] = payload.get(
            "direction", "BUY"
        ).upper()  # Default handled by serializer if not present
        trade_payload["order_type"] = payload.get("order_type", "MARKET").upper()

        entry_price = Decimal(str(payload.get("entry_price")))
        stop_loss_price = Decimal(str(payload.get("stop_loss_price")))
        take_profit_price = Decimal(
            str(payload.get("take_profit_price"))
        )  # This is already the absolute TP price

        direction = payload.get("direction", "BUY").upper()
        symbol = payload.get("symbol")

        if not account:
            return Response(
                {
                    "error": f"Account {account_id} not found for user {request.user.username}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if not symbol_info or "error" in symbol_info:
            error_message = (
                symbol_info.get("error")
                if symbol_info
                else "Unknown error fetching symbol info"
            )
            return Response(
                {"error": f"Could not fetch symbol info for {symbol}: {error_message}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pip_size_str = symbol_info.get("pip_size")
        if pip_size_str is None:
            return Response(
                {"error": f"Pip size not found in symbol info for {symbol}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pip_size = Decimal(str(pip_size_str))
        except Exception:
            return Response(
                {"error": f"Invalid pip size format '{pip_size_str}' for {symbol}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if pip_size == Decimal("0"):
            return Response(
                {
                    "error": f"Pip size for symbol {symbol} is zero, cannot calculate SL distance."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Calculate SL price difference
        if direction == "BUY":
            sl_price_diff = entry_price - stop_loss_price
        else:  # SELL
            sl_price_diff = stop_loss_price - entry_price

        # Ensure SL price difference is positive for distance calculation
        sl_price_diff = abs(sl_price_diff)

        stop_loss_distance_pips = int(round(sl_price_diff / pip_size))

        trade_payload["limit_price"] = float(
            entry_price
        )  # This is the entry price for the order
        trade_payload["stop_loss_distance"] = (
            stop_loss_distance_pips  # Integer pips/points
        )
        trade_payload["take_profit"] = float(
            take_profit_price
        )  # Absolute price, directly from payload

        trade_payload["risk_percent"] = payload.get(
            "risk_percent", 0.3
        )  # Default handled by serializer
        trade_payload["projected_profit"] = payload.get(
            "projected_profit", 0.0
        )  # Default handled by serializer
        trade_payload["projected_loss"] = payload.get(
            "projected_loss", 0.0
        )  # Default handled by serializer
        trade_payload["rr_ratio"] = payload.get(
            "rr_ratio"
        )  # Default handled by serializer
        trade_payload["reason"] = payload.get(
            "note", ""
        )  # Default handled by serializer

        payload = {
            "account_id": trade_payload["account_id"],
            "symbol": trade_payload["symbol"],
            "direction": trade_payload["direction"],
            "order_type": trade_payload["order_type"],
            "limit_price": trade_payload["limit_price"],
            "stop_loss_distance": trade_payload["stop_loss_distance"],
            "take_profit": trade_payload["take_profit"],
            "risk_percent": trade_payload["risk_percent"],
            "reason": trade_payload["reason"],
            "rr_ratio": trade_payload["rr_ratio"],
            "projected_profit": trade_payload["projected_profit"],
            "projected_loss": trade_payload["projected_loss"],
        }
        # 2️⃣ run service
        svc = TradeService(request.user, payload)
        account, final_lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account, final_lot, sl, tp)
        order, trade = svc.persist(account, resp, final_lot, sl, tp)

        # 3️⃣ build and return output
        out = svc.build_response(order, trade)
        out_ser = ExecuteTradeOutputSerializer(data=out)
        out_ser.is_valid(raise_exception=True)  # ensures consistent output

        trade_id = out_ser.validated_data["trade_id"]
        trade = None
        try:
            trade_id = uuid.UUID(trade_id, version=4)
            trade = Trade.objects.filter(id=trade_id).first()
        except (ValueError, TypeError):
            trade_id = None

        order_id = out_ser.validated_data["order_id"]
        order = None
        try:
            order_id = uuid.UUID(order_id, version=4)
            order = Order.objects.filter(id=order_id).first()
        except (ValueError, TypeError):
            order_id = None

        trade_journal = TradeJournal.objects.create(
            trade=trade,
            order=order,
            action=payload.get("action", "Opened Position"),
            reason=payload.get("note", ""),
            strategy_tag=payload.get("strategy_tag", ""),
            emotional_state=payload.get("emotional_state", "Automated"),
            market_condition=payload.get("market_condition", ""),
        )
        if payload.get("attachments"):
            attachments = payload.get("attachments").split(",")
            for attachment in attachments:
                file = requests.get(attachment)
                TradeJournalAttachment.objects.create(
                    journal=trade_journal,
                    file=ContentFile(file.content, name=attachment.split("/")[-1]),
                )

        return Response(out_ser.data)


class CloseAIPositionView(APIView):
    """
    Accepts a trade ID and closes the position using the existing trades app function.
    """

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, trade_id: str, *args, **kwargs):

        try:
            result = close_trade_globally(request.user, trade_id)
            return Response(result, status=status.HTTP_200_OK)
        except Trade.DoesNotExist:
            return Response(
                {"detail": "Trade not found."}, status=status.HTTP_404_NOT_FOUND
            )
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            return Response(
                {"detail": e.detail if hasattr(e, "detail") else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except APIException as e:
            return Response(
                {"detail": e.detail if hasattr(e, "detail") else str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            print(f"Unexpected error in CloseAIPositionView: {e}")
            return Response(
                {"detail": "An unexpected error occurred while closing the trade."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
