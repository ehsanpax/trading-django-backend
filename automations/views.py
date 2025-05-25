# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from decimal import Decimal
from decimal import Decimal
from .serializers import AITradeRequestSerializer
from trades.views import ExecuteTradeView
from accounts.models import Account # Assuming Account model path
from trades.helpers import fetch_symbol_info_for_platform # Import the helper
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from trade_journal.models import TradeJournal, TradeJournalAttachment, Trade
import requests
from django.core.files.base import ContentFile

class ExecuteAITradeView(APIView):
    """Accepts AI trade payload, injects an account, forwards to ExecuteTradeView."""
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        print(f"Incoming Request Headers: {request.headers}") # Log headers
        print(f"Incoming Request Body: {request.data}") # Log body
        serializer = AITradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        print("Validated Payload ExecuteAITradeView:", payload)

        # account = select_next_account() # Removed: account_id now comes from payload
        trade_payload = {}
        trade_payload["account_id"] = str(payload.get("account_id"))
        trade_payload["symbol"] = payload.get("symbol")
        trade_payload["direction"] = payload.get("direction", "BUY").upper() # Default handled by serializer if not present
        trade_payload["order_type"] = payload.get("order_type", "MARKET").upper()
        
        entry_price = Decimal(str(payload.get("entry_price")))
        stop_loss_price = Decimal(str(payload.get("stop_loss_price")))
        take_profit_price = Decimal(str(payload.get("take_profit_price"))) # This is already the absolute TP price
        
        direction = payload.get("direction", "BUY").upper()
        symbol = payload.get("symbol")
        account_id = payload.get("account_id")

        try:
            account = Account.objects.get(id=account_id)
        except Account.DoesNotExist:
            return Response({"error": f"Account {account_id} not found."}, status=status.HTTP_400_BAD_REQUEST)

        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if not symbol_info or "error" in symbol_info:
            error_message = symbol_info.get("error") if symbol_info else "Unknown error fetching symbol info"
            return Response({"error": f"Could not fetch symbol info for {symbol}: {error_message}"}, status=status.HTTP_400_BAD_REQUEST)

        pip_size_str = symbol_info.get("pip_size")
        if pip_size_str is None:
            return Response({"error": f"Pip size not found in symbol info for {symbol}."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            pip_size = Decimal(str(pip_size_str))
        except Exception:
             return Response({"error": f"Invalid pip size format '{pip_size_str}' for {symbol}."}, status=status.HTTP_400_BAD_REQUEST)

        if pip_size == Decimal("0"):
             return Response({"error": f"Pip size for symbol {symbol} is zero, cannot calculate SL distance."}, status=status.HTTP_400_BAD_REQUEST)

        # Calculate SL price difference
        if direction == "BUY":
            sl_price_diff = entry_price - stop_loss_price
        else: # SELL
            sl_price_diff = stop_loss_price - entry_price
        
        # Ensure SL price difference is positive for distance calculation
        sl_price_diff = abs(sl_price_diff)

        stop_loss_distance_pips = int(round(sl_price_diff / pip_size))
        
        trade_payload["limit_price"] = float(entry_price) # This is the entry price for the order
        trade_payload["stop_loss_distance"] = stop_loss_distance_pips # Integer pips/points
        trade_payload["take_profit"] = float(take_profit_price) # Absolute price, directly from payload
        
        trade_payload["risk_percent"] = payload.get("risk_percent", 0.3) # Default handled by serializer
        trade_payload["projected_profit"] = payload.get("projected_profit", 0.0) # Default handled by serializer
        trade_payload["projected_loss"] = payload.get("projected_loss", 0.0) # Default handled by serializer
        trade_payload["rr_ratio"] = payload.get("rr_ratio") # Default handled by serializer
        trade_payload["reason"] = payload.get("note", "") # Default handled by serializer


        factory = APIRequestFactory()
        forward_request = factory.post('/trades/execute/', trade_payload, format='json')
        # carry over authentication
        force_authenticate(forward_request, user=request.user)

        execution_view = ExecuteTradeView.as_view()
        response = execution_view(forward_request, *args, **kwargs)

        print("Response from ExecuteTradeView:", response.data, response.status_code)

        trade_id = response.data.get("trade_id")
        if not trade_id:
            return Response({"error": "Trade ID not found in response"}, status=status.HTTP_400_BAD_REQUEST)
        trade_journal = TradeJournal.objects.create(
            trade=Trade.objects.get(id=trade_id),
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
                    file=ContentFile(file.content, name=attachment.split("/")[-1])
                )
        
        return Response(response.data, status=response.status_code)
