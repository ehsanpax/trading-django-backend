# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from .serializers import AITradeRequestSerializer
from .services import select_next_account
from trades.views import ExecuteTradeView
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
        serializer = AITradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        print("Validated Payload ExecuteAITradeView:", payload)

        # account = select_next_account() # Removed: account_id now comes from payload
        trade_payload = {}
        trade_payload["account_id"] = str(payload.get("account_id"))
        trade_payload["symbol"] = payload.get("symbol")
        trade_payload["direction"] = payload.get("direction", "BUY").upper() # Default handled by serializer if not present
        trade_payload["order_type"] = payload.get("order_type", "MARKET").upper() # Default handled by serializer
        trade_payload["limit_price"] = float(payload.get("entry_price")) # entry_price is required in serializer
        # time_in_force is not in AITradeRequestSerializer, if needed by ExecuteTradeView, it should be added or handled
        # trade_payload["time_in_force"] = payload.get("time_in_force", "GTC").upper() 
        trade_payload["stop_loss_distance"] = float(payload.get("stop_loss_distance")) # required in serializer
        trade_payload["take_profit"] = float(payload.get("take_profit_distance")) # required in serializer
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
