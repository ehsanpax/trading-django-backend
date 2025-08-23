# trades/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets  # Added viewsets
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decimal import Decimal
import uuid, requests
from uuid import uuid4
from django.conf import settings
from django.db.models import Q  # For OR queries
from accounts.services import get_account_details
from rest_framework_simplejwt.authentication import JWTAuthentication

# Import models from your accounts app (or wherever they reside)
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from trading.models import Trade, Order, ProfitTarget, Watchlist  # Added Watchlist
from accounts.views import FetchAccountDetailsView

# DRF permissions
from rest_framework.permissions import IsAuthenticated, IsAdminUser  # Added IsAdminUser
from rest_framework.decorators import action  # Added missing import for action
from .helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform

# Import risk management functions (assumed refactored for Django)
from risk.management import validate_trade_request, fetch_risk_settings
from asgiref.sync import async_to_sync

# Import the MT5APIClient
from trading_platform.mt5_api_client import MT5APIClient
from risk.models import RiskManagement
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from risk.management import (
    validate_trade_request,  # existing function that calculates final lot size, etc.
    perform_risk_checks,  # our new guard rail checks
)
from .targets import derive_target_price
from .services import (  # Grouped imports for services
    TradeService,
    close_trade_globally,
    partially_close_trade,
    update_trade_protection_levels,
    update_trade_stop_loss_globally,
    get_pending_orders,
    cancel_pending_order,
)
from .tasks import synchronize_account_trades
from .serializers import (
    OrderSerializer,
    ExecuteTradeInputSerializer,
    ExecuteTradeOutputSerializer,
    UpdateStopLossSerializer,
    PartialCloseTradeInputSerializer,  # Added PartialCloseTradeInputSerializer
    TradeSerializer,  # Make sure TradeSerializer is imported if used by UpdateTradeView
    WatchlistSerializer,  # Added WatchlistSerializer
)
from rest_framework.generics import GenericAPIView

# from .services import update_trade_stop_loss_globally # This is now part of grouped imports
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
# New: TradingService for platform-agnostic symbol info
from connectors.trading_service import TradingService

# ----- Trade / Order Execution --------------------------------------------

import logging

logger = logging.getLogger(__name__)


class ExecuteTradeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ExecuteTradeInputSerializer
    response_serializer_class = ExecuteTradeOutputSerializer

    def post(self, request, *args, **kwargs):
        logger.info(f"Received trade execution request: {request.data}")
        # 1️⃣ validate input
        in_ser = self.get_serializer(data=request.data)
        in_ser.is_valid(raise_exception=True)

        # 2️⃣ run service
        svc = TradeService(request.user, in_ser.validated_data)
        account, final_lot, sl, tp = svc.validate()
        resp = svc.execute_on_broker(account, final_lot, sl, tp)
        order, trade = svc.persist(account, resp, final_lot, sl, tp)

        # 3️⃣ build and return output
        out = svc.build_response(order, trade)
        out_ser = self.response_serializer_class(data=out)
        out_ser.is_valid(raise_exception=True)  # ensures consistent output
        return Response(out_ser.data, status=status.HTTP_200_OK)


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


# ----- Update Take Profit -----
class UpdateTakeProfitView(APIView):  # Renamed from UpdateTradeView
    """
    Updates an open trade's take profit.
    Expected JSON:
    {
        "take_profit": <float>
    }
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, trade_id_str: str):
        try:
            valid_trade_id = uuid.UUID(trade_id_str)
        except ValueError:
            raise ValidationError("Invalid trade ID format.")

        # This view now ONLY handles take_profit updates.
        raw_tp = request.data.get("take_profit")

        if raw_tp is None:
            raise ValidationError("'take_profit' must be provided.")

        try:
            new_tp = Decimal(str(raw_tp))
        except Exception:
            raise ValidationError("'take_profit' must be a valid decimal number.")

        # Call update_trade_protection_levels, passing None for new_stop_loss
        # as this view no longer handles SL.
        result = update_trade_protection_levels(
            user=request.user,
            trade_id=valid_trade_id,
            new_stop_loss=None,  # Explicitly pass None for SL
            new_take_profit=new_tp,
        )
        # Fetch the updated trade to include in the response
        updated_trade = Trade.objects.get(id=valid_trade_id)
        serializer = TradeSerializer(updated_trade)

        return Response(
            {
                "message": result.get("message", "Trade updated successfully."),
                "trade": serializer.data,
                "platform_response": result.get("platform_response"),
            },
            status=status.HTTP_200_OK,
        )


# ----- Close Trade -----
class CloseTradeView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, trade_id):
        # Ensure trade_id is a valid UUID
        try:
            valid_trade_id = uuid.UUID(trade_id)
        except ValueError:
            raise ValidationError("Invalid trade ID format.")

        client_reason = (request.data or {}).get("close_reason")
        client_subreason = (request.data or {}).get("close_subreason")
        try:
            result = close_trade_globally(request.user, valid_trade_id, client_close_reason=client_reason, client_close_subreason=client_subreason)
        except Exception as e:
            # Surface broker/validation errors as 400 for client clarity
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # If the helper returned an error key, convert to 400
        if isinstance(result, dict) and result.get("error"):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


# ----- Retrieve Symbol Info -----
class TradeSymbolInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        # 1️⃣ Ensure the account belongs to the user
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Fetch via TradingService to keep callers platform-agnostic
        ts = TradingService(account)
        try:
            symbol_info = ts.get_symbol_info_sync(symbol)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(symbol_info, dict) and symbol_info.get("error"):
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
            return Response(
                {"detail": price_data["error"]}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(price_data, status=status.HTTP_200_OK)


class OpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        account = get_object_or_404(Account, id=account_id, user=request.user)

        if account.platform == "MT5":
            # Use TradingService sync snapshot only
            try:
                from connectors.trading_service import TradingService
                ts = TradingService(account)
                acc = ts.get_account_info_sync()
                positions = ts.get_open_positions_sync()
                logger.info("trades.open_positions path=ts mode=sync account_id=%s", account_id)
                # Map standardized PositionInfo to dict expected by existing response shape
                live_positions = []
                for p in positions or []:
                    try:
                        live_positions.append({
                            "ticket": getattr(p, "position_id", None),
                            "symbol": getattr(p, "symbol", None),
                            "direction": getattr(p, "direction", None),
                            "volume": getattr(p, "volume", None),
                            "price_open": getattr(p, "open_price", None),
                            "price_current": getattr(p, "current_price", None),
                            "stop_loss": getattr(p, "stop_loss", None),
                            "profit_target": getattr(p, "take_profit", None),
                            "profit": getattr(p, "profit", None),
                            "swap": getattr(p, "swap", None),
                            "commission": getattr(p, "commission", None),
                        })
                    except Exception:
                        pass
            except Exception:
                logger.exception("TradingService snapshot failed for open positions on account %s.", account_id)
                return Response({"error": "Open positions unavailable via TradingService."}, status=status.HTTP_502_BAD_GATEWAY)

            # Merge with DB like before
            db_trades = Trade.objects.filter(account=account, trade_status="open")
            db_trades_dict = {trade.position_id: trade for trade in db_trades if trade.position_id}

            final_positions = []
            for pos in live_positions:
                if not isinstance(pos, dict):
                    continue
                ticket = pos.get("ticket")
                db_trade = db_trades_dict.get(ticket)
                if db_trade:
                    trade_data = TradeSerializer(db_trade).data
                    trade_data.update({
                        "profit": pos.get("profit"),
                        "swap": pos.get("swap"),
                        "stop_loss": pos.get("stop_loss") or pos.get("sl"),
                        "profit_target": pos.get("profit_target") or pos.get("tp"),
                        "source": "platform_synced_with_db",
                    })
                    final_positions.append(trade_data)
                else:
                    pos["source"] = "platform_only"
                    final_positions.append(pos)

            return Response({"db_trades": [], "open_positions": final_positions}, status=status.HTTP_200_OK)

        elif account.platform == "cTrader":
            # Use TradingService snapshot for cTrader as well to ensure lots-based volumes
            try:
                from connectors.trading_service import TradingService
                ts = TradingService(account)
                positions = ts.get_open_positions_sync()
                logger.info("trades.open_positions path=ts mode=sync platform=cTrader account_id=%s", account_id)
                live_positions = []
                for p in positions or []:
                    try:
                        live_positions.append({
                            "ticket": getattr(p, "position_id", None),
                            "symbol": getattr(p, "symbol", None),
                            "direction": getattr(p, "direction", None),
                            "volume": getattr(p, "volume", None),  # already in lots
                            "price_open": getattr(p, "open_price", None),
                            "price_current": getattr(p, "current_price", None),
                            "stop_loss": getattr(p, "stop_loss", None),
                            "profit_target": getattr(p, "take_profit", None),
                            "profit": getattr(p, "profit", None),
                            "swap": getattr(p, "swap", None),
                            "commission": getattr(p, "commission", None),
                        })
                    except Exception:
                        pass
            except Exception:
                logger.exception("TradingService snapshot failed for open positions on account %s.", account_id)
                return Response({"error": "Open positions unavailable via TradingService."}, status=status.HTTP_502_BAD_GATEWAY)

            # Merge with DB like MT5 path
            db_trades = Trade.objects.filter(account=account, trade_status="open")
            db_trades_dict = {trade.position_id: trade for trade in db_trades if trade.position_id}

            final_positions = []
            for pos in live_positions:
                if not isinstance(pos, dict):
                    continue
                ticket = pos.get("ticket")
                db_trade = db_trades_dict.get(ticket)
                if db_trade:
                    trade_data = TradeSerializer(db_trade).data
                    trade_data.update({
                        "profit": pos.get("profit"),
                        "swap": pos.get("swap"),
                        "stop_loss": pos.get("stop_loss") or pos.get("sl"),
                        "profit_target": pos.get("profit_target") or pos.get("tp"),
                        "source": "platform_synced_with_db",
                    })
                    final_positions.append(trade_data)
                else:
                    pos["source"] = "platform_only"
                    final_positions.append(pos)

            return Response({"db_trades": [], "open_positions": final_positions}, status=status.HTTP_200_OK)
        else:
            # Unsupported platform, just return DB trades from our database
            db_trades = Trade.objects.filter(account=account, trade_status="open")
            serializer = TradeSerializer(db_trades, many=True)
            return Response(
                {"open_positions": serializer.data}, status=status.HTTP_200_OK
            )

        return Response(
            {"open_positions": final_open_positions}, status=status.HTTP_200_OK
        )


class AllOpenPositionsLiveView(APIView):
    """
    Retrieves live open positions across the user's accounts.
    Uses TradingService for platform-agnostic access. Falls back to cTrader microservice only when needed.
    """

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_accounts = Account.objects.filter(user=request.user)
        final_all_open_positions = []
        db_trade_index = {}

        # Optional account filter: UUID or name
        account_id = self.request.query_params.get("account", None)
        if account_id:
            try:
                acct_uuid = uuid.UUID(account_id, version=4)
                user_accounts = user_accounts.filter(id=acct_uuid)
            except Exception:
                user_accounts = user_accounts.filter(name__iexact=str(account_id))

        # 1) Seed with DB trades
        db_trades = Trade.objects.filter(account__in=user_accounts, trade_status="open")
        from .serializers import TradeSerializer
        serialized_db_trades = TradeSerializer(db_trades, many=True).data
        for i, trade_data in enumerate(serialized_db_trades):
            trade_data["source"] = "database"
            trade_data.pop("reason", None)
            final_all_open_positions.append(trade_data)
            key = (trade_data.get("account"), trade_data.get("order_id"))
            if key[0] and key[1] is not None:
                db_trade_index[key] = i

        # 2) Merge platform snapshots per account
        for account in user_accounts:
            positions = None
            try:
                from connectors.trading_service import TradingService
                ts = TradingService(account)
                positions = ts.get_open_positions_sync()
                logger.info("trades.all_open_positions path=ts mode=sync account_id=%s", account.id)
            except Exception:
                logger.exception("TradingService positions snapshot failed for account %s", account.id)

            # Temporary cTrader fallback
            if positions is None and (account.platform or "").lower() == "ctrader":
                try:
                    ctrader_account = CTraderAccount.objects.get(account=account)
                except CTraderAccount.DoesNotExist:
                    continue
                payload = {
                    "access_token": ctrader_account.access_token,
                    "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                }
                base_url = settings.CTRADER_API_BASE_URL
                positions_url = f"{base_url.rstrip('/')}/ctrader/positions/open"
                try:
                    pos_resp = requests.post(positions_url, json=payload, timeout=10)
                    pos_resp.raise_for_status()
                    pos_data_response = pos_resp.json()
                    if "error" in pos_data_response:
                        logger.error(
                            "cTrader positions endpoint error for account %s: %s",
                            account.id,
                            pos_data_response.get("error"),
                        )
                        continue
                    # Normalize into lightweight objects with expected attributes
                    positions = []
                    for pos in pos_data_response.get("positions", []):
                        positions.append(type("Pos", (), {
                            "position_id": pos.get("id") or pos.get("positionId"),
                            "symbol": pos.get("symbol"),
                            "direction": pos.get("side"),
                            "volume": pos.get("volume"),
                            "open_price": pos.get("open_price"),
                            "current_price": pos.get("current_price") or pos.get("market_price"),
                            "stop_loss": pos.get("stop_loss"),
                            "take_profit": pos.get("take_profit"),
                            "profit": pos.get("profit"),
                            "swap": pos.get("swap"),
                            "commission": pos.get("commission"),
                        })())
                except requests.RequestException:
                    logger.exception("Error calling cTrader positions endpoint for account %s", account.id)
                    continue

            if not positions:
                continue

            for p in positions:
                ticket = getattr(p, "position_id", None)
                acct_id_str = str(account.id)
                key = (acct_id_str, ticket)
                pos_dict = {
                    "trade_id": None,
                    "order_id": ticket,
                    "ticket": ticket,
                    "symbol": getattr(p, "symbol", None),
                    "volume": getattr(p, "volume", None),
                    "price_open": getattr(p, "open_price", None),
                    "profit": getattr(p, "profit", None),
                    "time": 0,
                    "direction": getattr(p, "direction", None),
                    "stop_loss": getattr(p, "stop_loss", None),
                    "profit_target": getattr(p, "take_profit", None),
                    "swap": getattr(p, "swap", None),
                    "commission": getattr(p, "commission", None),
                    "account_id": acct_id_str,
                    "account": acct_id_str,
                    "source": "platform_only",
                }

                if key in db_trade_index:
                    idx = db_trade_index[key]
                    merged = {**final_all_open_positions[idx], **pos_dict}
                    merged["trade_id"] = final_all_open_positions[idx].get("id")
                    merged["source"] = "platform_synced_with_db"
                    final_all_open_positions[idx] = merged
                else:
                    final_all_open_positions.append(pos_dict)

        return Response({"open_positions": final_all_open_positions}, status=status.HTTP_200_OK)


class PendingOrdersView(APIView):
    """
    GET /trades/pending-orders/{account_id}/
    Returns all pending (limit/stop) orders for the given account from the trading platform.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        account = get_object_or_404(Account, id=account_id, user=request.user)
        pending_orders_data = get_pending_orders(account)
        return Response({"pending_orders": pending_orders_data}, status=status.HTTP_200_OK)


class AllPendingOrdersView(APIView):
    """
    GET /trades/all-pending-orders/
    Returns all pending (limit/stop) orders for all of the user's accounts from the trading platforms.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)
        account_id = self.request.query_params.get("account_id", None)
        if account_id:
            try:
                account_id = uuid.UUID(account_id, version=4)
                accounts = Account.objects.filter(id=account_id, user=request.user)
            except Exception:
                accounts = Account.objects.filter(name__iexact=str(account_id), user=request.user)
        pending_orders = []
        for account in accounts:
            pending_orders.extend(get_pending_orders(account))
        return Response({"pending_orders": pending_orders}, status=status.HTTP_200_OK)


class CancelPendingOrderView(APIView):
    """
    DELETE /trades/pending-orders/<uuid:order_id>/cancel/
    Cancels a pending order.
    """
    authentication_classes = [TokenAuthentication, JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, order_id: str):
        result = cancel_pending_order(user=request.user, order_id=order_id)
        return Response(result, status=status.HTTP_200_OK)


class UpdateStopLossAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = UpdateStopLossSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        result = update_trade_stop_loss_globally(
            user=request.user,
            trade_id=validated_data["trade_id"],
            sl_update_type=validated_data["sl_update_type"],
            value=validated_data.get("value"),
            specific_price=validated_data.get("specific_price"),
        )
        return Response(result, status=status.HTTP_200_OK)


class PartialCloseTradeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trade_id_str: str):
        try:
            valid_trade_id = uuid.UUID(trade_id_str)
        except ValueError:
            raise ValidationError("Invalid trade ID format.")

        serializer = PartialCloseTradeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        volume_to_close = serializer.validated_data["volume_to_close"]
        result = partially_close_trade(
            user=request.user, trade_id=valid_trade_id, volume_to_close=volume_to_close
        )
        return Response(result, status=status.HTTP_200_OK)


class SynchronizeAccountTradesView(APIView):
    """
    Triggers the synchronization of trades for a specific account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, account_id):
        try:
            account = Account.objects.get(id=account_id, user=request.user)
        except Account.DoesNotExist:
            return Response(
                {"error": "Account not found or you do not have permission to access it."},
                status=status.HTTP_404_NOT_FOUND,
            )
        synchronize_account_trades.delay(account_id=account.id)
        return Response(
            {"message": f"Synchronization task for account {account.id} has been queued."},
            status=status.HTTP_202_ACCEPTED,
        )


class WatchlistViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows watchlists to be viewed or edited.
    - Users can add/remove/get their own watchlist items.
    - Admin users can mark watchlist items as global.
    - The list endpoint returns watchlists for the logged-in user plus global ones.
    """
    serializer_class = WatchlistSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        This view should return a list of all the watchlists
        for the currently authenticated user plus global watchlists.
        """
        user = self.request.user
        return Watchlist.objects.filter(Q(user=user) | Q(is_global=True)).distinct()

    def perform_create(self, serializer):
        """
        Save the watchlist item.
        The serializer's create method handles setting the user or making it global.
        """
        serializer.save(
            user=(self.request.user if not serializer.validated_data.get("is_global") else None)
        )

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        Allow admin users to perform any action on global watchlists.
        Regular users can only modify their own non-global watchlists.
        """
        if self.action in ["update", "partial_update", "destroy"]:
            pass
        elif self.action == "create":
            pass
        return super().get_permissions()

    def perform_update(self, serializer):
        instance = serializer.instance
        if instance.is_global and not self.request.user.is_staff:
            raise PermissionDenied("Only admins can modify global watchlist items.")
        if not instance.is_global and instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to modify this watchlist item.")

        is_becoming_global = serializer.validated_data.get("is_global", instance.is_global)
        if is_becoming_global and not instance.is_global and not self.request.user.is_staff:
            raise PermissionDenied("Only admins can make watchlist items global.")

        if is_becoming_global and self.request.user.is_staff:
            serializer.save(user=None)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        """
        Ensure only owners or admins (for global items) can delete.
        """
        if instance.is_global and not self.request.user.is_staff:
            raise PermissionDenied("Only admins can delete global watchlist items.")
        if not instance.is_global and instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to delete this watchlist item.")
        instance.delete()

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def make_global(self, request, pk=None):
        watchlist_item = self.get_object()
        if not watchlist_item.is_global:
            watchlist_item.is_global = True
            watchlist_item.user = None
            watchlist_item.save(update_fields=["is_global", "user"])
            return Response({"status": "watchlist item set to global"}, status=status.HTTP_200_OK)
        return Response({"status": "watchlist item is already global"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def remove_global(self, request, pk=None):
        watchlist_item = self.get_object()
        if watchlist_item.is_global:
            watchlist_item.is_global = False
            watchlist_item.save(update_fields=["is_global"])
            return Response({"status": "watchlist item removed from global"}, status=status.HTTP_200_OK)
        return Response({"status": "watchlist item is not global"}, status=status.HTTP_400_BAD_REQUEST)
