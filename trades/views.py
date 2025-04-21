# trades/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
import uuid, requests
from django.conf import settings
from accounts.services import get_account_details
# Import models from your accounts app (or wherever they reside)
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from trading.models import Trade
from accounts.views import FetchAccountDetailsView
# DRF permissions
from rest_framework.permissions import IsAuthenticated
from .helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
# Import risk management functions (assumed refactored for Django)
from risk.management import validate_trade_request, fetch_risk_settings
from asgiref.sync import async_to_sync
# Import the MT5Connector service from the mt5 app
from mt5.services import MT5Connector
from risk.models import RiskManagement
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from risk.management import (
    validate_trade_request,  # existing function that calculates final lot size, etc.
    perform_risk_checks      # our new guard rail checks
)
# ----- Trade Execution -----
class ExecuteTradeView(APIView):
    """
    Executes a trade with risk validation.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        data = request.data
        account_id = data.get("account_id")
        symbol = data.get("symbol")
        direction = data.get("direction")
        lot_size_input = data.get("lot_size")
        entry_price = data.get("entry_price")
        stop_loss_distance = data.get("stop_loss_distance")
        take_profit = data.get("take_profit")
        take_profit_distance = data.get("take_profit_distance")
        risk_percent = data.get("risk_percent", 0.5)
        projected_profit = data.get("projected_profit", 0.0)
        projected_loss = data.get("projected_loss", 0.0)
        rr_ratio = data.get("rr_ratio")
        reason = data.get("reason")
        trader = data.get("trader", "")
    
        account = get_object_or_404(Account, id=account_id)
        if account.user != request.user:
            return Response({"detail": "Unauthorized to trade on this account"}, status=status.HTTP_403_FORBIDDEN)
    
        account_info = get_account_details(account_id, request.user)
        if "error" in account_info:
            return Response({"detail": account_info["error"]}, status=status.HTTP_400_BAD_REQUEST)
    # 1️⃣ Fetch risk settings
        try:
            risk_settings = RiskManagement.objects.get(account=account)
        except RiskManagement.DoesNotExist:
            return Response({"detail": "No risk settings found for this account"}, status=status.HTTP_400_BAD_REQUEST)
        
        risk_settings = fetch_risk_settings(account_id)
        validation_response = validate_trade_request(
            account_id=account_id,
            user=request.user,
            symbol=symbol,
            trade_direction=direction,
            stop_loss_distance=stop_loss_distance,
            take_profit_price=take_profit,
            risk_percent=risk_percent
        )
        if "error" in validation_response:
            return Response({"detail": validation_response["error"]}, status=status.HTTP_400_BAD_REQUEST)
    
        final_lot_size = validation_response.get("lot_size")
        stop_loss_price = validation_response.get("stop_loss_price")
        take_profit_price = validation_response.get("take_profit_price")

         # 3️⃣ Perform new guard-rail checks
        risk_check_result = perform_risk_checks(risk_settings, final_lot_size, symbol,Decimal(risk_percent))
        if "error" in risk_check_result:
            return Response({"detail": risk_check_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

        execution_result = None
        position_info = {}
        order_ticket = None
        deal_ticket = None
    
        if account.platform == "MT5":
            try:
                mt5_account = MT5Account.objects.get(account=account)
            except MT5Account.DoesNotExist:
                return Response({"detail": "No linked MT5 account found"}, status=status.HTTP_400_BAD_REQUEST)
    
            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)
    
            trade_result = connector.place_trade(
                symbol=symbol,
                lot_size=final_lot_size,
                direction=direction,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price
            )
            if "error" in trade_result:
                return Response({"detail": trade_result["error"]}, status=status.HTTP_400_BAD_REQUEST)
    
            # Capture the order ticket and the opening deal ticket.
            order_ticket = trade_result.get("order_id")
            deal_ticket = trade_result.get("deal")  # Assuming place_trade returns result.deal as "deal"
            if not deal_ticket:
                # Fallback: If not present, use the order ticket.
                deal_ticket = order_ticket
    
            execution_result = trade_result
            execution_result["order_ticket"] = order_ticket
            execution_result["deal_ticket"] = deal_ticket
            position_info = connector.get_position_by_ticket(order_ticket)
    
        elif account.platform == "cTrader":
            try:
                ctrader_account = CTraderAccount.objects.get(account=account)
            except CTraderAccount.DoesNotExist:
                return Response({"detail": "No linked cTrader account found."}, status=status.HTTP_400_BAD_REQUEST)
            
            # Build the payload using details from the account and trade inputs.
            payload = {
                "access_token": ctrader_account.access_token,
                "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                "symbol": symbol,
                "order_type": "MARKET",  # For LIMIT orders, include "limit_price" in payload
                "trade_side": direction.upper(),
                "volume": final_lot_size,
                "stop_loss": stop_loss_distance,
                "take_profit": take_profit_distance
            }
            print("cTrader Payload:", payload)
            base_url = settings.CTRADER_API_BASE_URL  # e.g., "http://localhost:8080"
            order_url = f"{base_url}/ctrader/order/place"
            
            try:
                order_resp = requests.post(order_url, json=payload, timeout=10)
            except requests.RequestException as e:
                return Response({"detail": f"Error calling cTrader order placement endpoint: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            
            if order_resp.status_code != 200:
                return Response({"detail": f"cTrader order placement failed with status: {order_resp.status_code}"}, status=status.HTTP_400_BAD_REQUEST)
            
            order_data = order_resp.json()
            if "error" in order_data:
                return Response({"detail": order_data["error"]}, status=status.HTTP_400_BAD_REQUEST)
            
            order_ticket = order_data.get("orderId")
            deal_ticket = order_data.get("deal") or order_ticket
    
            execution_result = order_data
            # Build a minimal position_info dictionary based on the order placement response.
            position_info = {
                "ticket": order_data.get("positionId"),
                "price_open": order_data.get("entry_price"),
                "volume": order_data.get("lot_size"),
                "sl": stop_loss_price,
                "tp": take_profit_price,
            }
        else:
            return Response({"detail": "Unsupported trading platform"}, status=status.HTTP_400_BAD_REQUEST)
        
        position_ticket = position_info.get("ticket")
        new_trade = Trade.objects.create(
            account=account,
            instrument=symbol,
            direction=direction,
            lot_size=Decimal(position_info.get("volume", final_lot_size)),
            remaining_size=Decimal(position_info.get("volume", final_lot_size)),
            entry_price=Decimal(position_info.get("price_open", take_profit)),
            stop_loss=Decimal(position_info.get("sl", stop_loss_price)),
            profit_target=Decimal(position_info.get("tp", take_profit_price)),
            risk_percent=Decimal(risk_percent),
            trade_status="open",
            projected_profit=Decimal(projected_profit),
            projected_loss=Decimal(projected_loss),
            rr_ratio=rr_ratio,
            order_id=order_ticket,  # Save original order ticket
            deal_id=deal_ticket,     # Save opening deal ticket
            position_id=position_ticket,
            reason=reason,
            trader=trader
        )
    
        return Response({
            "message": "Trade executed successfully",
            "trade_id": str(new_trade.id),
            "platform": account.platform,
            "order_ticket": order_ticket,
            "deal_ticket": deal_ticket,
            "real_fill_data": position_info,
        }, status=status.HTTP_200_OK)

# ----- Retrieve Open Trades -----
class OpenTradesView(APIView):
    """
    Retrieves all open trades for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)
        trades = Trade.objects.filter(account__in=accounts, trade_status="open")
        from .serializers import TradeSerializer
        serializer = TradeSerializer(trades, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# ----- Update Trade -----
class UpdateTradeView(APIView):
    """
    Updates an open trade's stop loss or take profit.
    Expected JSON:
    {
        "stop_loss": <float>,
        "take_profit": <float>
    }
    """
    permission_classes = [IsAuthenticated]

    def put(self, request, trade_id):
        trade = get_object_or_404(Trade, id=trade_id)
        if trade.account.user != request.user:
            return Response({"detail": "Unauthorized to modify this trade"}, status=status.HTTP_403_FORBIDDEN)

        trade.stop_loss = request.data.get("stop_loss")
        trade.profit_target = request.data.get("take_profit")
        trade.save()
        from .serializers import TradeSerializer
        serializer = TradeSerializer(trade)
        return Response({"message": "Trade updated successfully", "trade": serializer.data}, status=status.HTTP_200_OK)

# ----- Close Trade -----
class CloseTradeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, trade_id):
        trade = get_object_or_404(Trade, id=trade_id)

        if trade.account.user != request.user:
            return Response({"detail": "Unauthorized to close this trade"}, status=status.HTTP_403_FORBIDDEN)

        if trade.trade_status != "open":
            return Response({"detail": "Trade is already closed"}, status=status.HTTP_400_BAD_REQUEST)

        profit = None

        if trade.account.platform == "MT5":
            try:
                mt5_account = trade.account.mt5_account
            except MT5Account.DoesNotExist:
                return Response({"detail": "No linked MT5 account found."}, status=status.HTTP_400_BAD_REQUEST)

            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

            # Capture the current profit, commission, and swap BEFORE closing
            position_data = connector.get_position_by_ticket(trade.order_id)
            if position_data:
                profit = (
                    position_data.get("profit", 0)
                    + position_data.get("commission", 0)
                    + position_data.get("swap", 0)
                )
                print(f"Captured P&L before closing: {profit}")
            else:
                print("No position data found; defaulting profit to 0")
                profit = 0

            # Now close the trade in MT5
            close_result = connector.close_trade(
                ticket=trade.order_id,
                volume=float(trade.remaining_size),
                symbol=trade.instrument
            )

            if "error" in close_result:
                return Response({"detail": close_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

        elif trade.account.platform == "cTrader":
            return Response({"detail": "cTrader close not implemented yet."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"detail": "Unsupported trading platform."}, status=status.HTTP_400_BAD_REQUEST)

        # Update the trade record with the captured profit
        trade.trade_status = "closed"
        trade.closed_at = timezone.now()
        if profit is not None:
            trade.actual_profit_loss = Decimal(profit)
        trade.save()

        return Response({
            "message": "Trade closed successfully",
            "trade_id": str(trade.id),
            "actual_profit_loss": float(trade.actual_profit_loss or 0)
        }, status=status.HTTP_200_OK)


# ----- Retrieve Symbol Info -----
class TradeSymbolInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        # 1️⃣ Ensure the account belongs to the user
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Call the helper
        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if "error" in symbol_info:
            return Response({"detail": symbol_info["error"]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(symbol_info, status=status.HTTP_200_OK)

# ----- Retrieve Market Price -----
class MarketPriceView(APIView):
    """
    GET /trades/market-price/<account_id>/<symbol>/
    Retrieves real-time market prices (bid/ask) for a given symbol.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        account = get_object_or_404(Account, id=account_id, user=request.user)

        price_data = fetch_live_price_for_platform(account, symbol)
        if "error" in price_data:
            return Response({"detail": price_data["error"]}, status=status.HTTP_400_BAD_REQUEST)

        return Response(price_data, status=status.HTTP_200_OK)
    
class OpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        account = get_object_or_404(Account, id=account_id, user=request.user)

        if account.platform == "MT5":
            try:
                mt5_account = account.mt5_account
            except MT5Account.DoesNotExist:
                return Response({"detail": "No linked MT5 account found."}, status=status.HTTP_400_BAD_REQUEST)

            connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
            login_result = connector.connect(mt5_account.encrypted_password)
            if "error" in login_result:
                return Response({"detail": login_result["error"]}, status=status.HTTP_400_BAD_REQUEST)

            mt5_positions = connector.get_open_positions()
            if "error" in mt5_positions:
                return Response({"detail": mt5_positions["error"]}, status=status.HTTP_400_BAD_REQUEST)

            # Enhance MT5 positions with UUIDs
            enriched_positions = []
            for pos in mt5_positions["open_positions"]:
                ticket = pos["ticket"]
                try:
                    trade = Trade.objects.get(order_id=ticket)
                    pos["trade_id"] = str(trade.id)
                except Trade.DoesNotExist:
                    pos["trade_id"] = None
                enriched_positions.append(pos)

            return Response({"open_positions": enriched_positions}, status=status.HTTP_200_OK)

        elif account.platform == "cTrader":
                    try:
                        ctrader_account = CTraderAccount.objects.get(account=account)
                    except CTraderAccount.DoesNotExist:
                        return Response({"detail": "No linked cTrader account found."}, status=400)

                    payload = {
                        "access_token": ctrader_account.access_token,
                        "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                    }
                    base_url = settings.CTRADER_API_BASE_URL  # e.g. "http://localhost:8080"
                    positions_url = f"{base_url}/ctrader/positions"

                    try:
                        pos_resp = requests.post(positions_url, json=payload, timeout=10)
                    except requests.RequestException as e:
                        return Response({"detail": f"Error calling cTrader positions endpoint: {str(e)}"}, status=400)

                    if pos_resp.status_code != 200:
                        return Response({"detail": f"cTrader positions endpoint returned status: {pos_resp.status_code}"}, status=400)

                    pos_data = pos_resp.json()
                    if "error" in pos_data:
                        return Response({"detail": pos_data["error"]}, status=400)

                    raw_positions = pos_data.get("positions", [])
                    transformed_positions = []
                    for pos in raw_positions:
                        # Ticket from positionId (converted to int)
                        try:
                            ticket = int(pos.get("positionId"))
                        except (ValueError, TypeError):
                            ticket = None

                        trade_data = pos.get("tradeData", {})
                        # Convert volume from string (in micro units) to lots.
                        try:
                            volume = float(trade_data.get("volume", "0")) / 100
                        except (ValueError, TypeError):
                            volume = 0.0

                        # Determine the trade side/direction.
                        direction = trade_data.get("tradeSide", "").upper()

                        # Use 'price_open' if available; otherwise, fallback to 'price'.
                        price_open = pos.get("price_open", pos.get("price", 0))
                        try:
                            price_open = float(price_open)
                        except (ValueError, TypeError):
                            price_open = 0.0

                        # Use unrealized_pnl as profit.
                        try:
                            profit = float(pos.get("unrealized_pnl", 0))
                        except (ValueError, TypeError):
                            profit = 0.0

                        # Use openTimestamp if available, else utcLastUpdateTimestamp; convert from ms to s.
                        timestamp_raw = trade_data.get("openTimestamp") or pos.get("utcLastUpdateTimestamp")
                        try:
                            time_val = int(float(timestamp_raw) / 1000)
                        except (ValueError, TypeError):
                            time_val = 0

                        # Use the 'symbol' field directly as provided.
                        symbol_str = pos.get("symbol")
                        if not symbol_str:
                            # Fallback if, for some reason, symbol is not provided.
                            symbol_id = trade_data.get("symbolId")
                            symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                        transformed_positions.append({
                            "trade_id": None,      # Not assigned until linked to a trade.
                            "ticket": ticket,
                            "symbol": symbol_str,
                            "volume": volume,
                            "price_open": price_open,
                            "profit": profit,
                            "time": time_val,
                            "direction": direction,
                        })

                    return Response({"open_positions": transformed_positions}, status=200)

        return Response({"detail": "Unsupported trading platform."}, status=400)