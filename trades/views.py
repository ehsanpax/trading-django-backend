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

# Import models from your accounts app (or wherever they reside)
from accounts.models import Account, MT5Account, CTraderAccount
from connectors.ctrader_client import CTraderClient
from trading.models import Trade, Order, ProfitTarget, Watchlist  # Added Watchlist
from accounts.views import FetchAccountDetailsView

# DRF permissions
from rest_framework.permissions import IsAuthenticated, IsAdminUser  # Added IsAdminUser
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
from rest_framework.decorators import action  # For custom actions

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

        result = close_trade_globally(request.user, valid_trade_id)
        return Response(result, status=status.HTTP_200_OK)


# ----- Retrieve Symbol Info -----
class TradeSymbolInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id, symbol):
        # 1️⃣ Ensure the account belongs to the user
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Call the helper
        symbol_info = fetch_symbol_info_for_platform(account, symbol)
        if "error" in symbol_info:
            return Response(
                {"detail": symbol_info["error"]}, status=status.HTTP_400_BAD_REQUEST
            )

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
            try:
                mt5_account = account.mt5_account
            except MT5Account.DoesNotExist:
                return Response(
                    {"error": "No linked MT5 account found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Use the async_to_sync wrapper for the service call
            client_data = get_account_details(account_id, request.user)

            if "error" in client_data:
                return Response(
                    {"error": client_data["error"]}, status=status.HTTP_400_BAD_REQUEST
                )

            # Fetch DB trades synchronously
            db_trades = Trade.objects.filter(account=account, trade_status="open")
            db_trades_dict = {
                trade.position_id: trade for trade in db_trades if trade.position_id
            }

            live_positions = client_data.get("open_positions", [])

            final_positions = []
            for pos in live_positions:
                if not isinstance(pos, dict):
                    continue  # Skip if pos is not a dictionary
                ticket = pos.get("ticket")
                db_trade = db_trades_dict.get(ticket)

                if db_trade:
                    # Merge: Start with serialized DB trade, then update with live data
                    trade_data = TradeSerializer(db_trade).data
                    trade_data.update(
                        {
                            "profit": pos.get(
                                "profit"
                            ),  # Ensure the 'profit' key is present for the serializer's source
                            "swap": pos.get("swap"),
                            "stop_loss": pos.get("sl"),
                            "profit_target": pos.get("tp"),
                            "source": "platform_synced_with_db",
                        }
                    )
                    final_positions.append(trade_data)
                else:
                    # Platform-only trade
                    pos["source"] = "platform_only"
                    final_positions.append(pos)

            return Response(
                {"db_trades": [], "open_positions": final_positions},
                status=status.HTTP_200_OK,
            )

        elif account.platform == "cTrader":
            try:
                ctrader_account = CTraderAccount.objects.get(account=account)
            except CTraderAccount.DoesNotExist:
                return Response(
                    {"open_positions": final_open_positions}, status=status.HTTP_200_OK
                )

            payload = {
                "access_token": ctrader_account.access_token,
                "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
            }
            base_url = settings.CTRADER_API_BASE_URL
            positions_url = f"{base_url}/ctrader/positions"

            try:
                pos_resp = requests.post(positions_url, json=payload, timeout=10)
                pos_resp.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                pos_data_response = pos_resp.json()
                if "error" in pos_data_response:
                    logger.error(
                        f"cTrader positions endpoint error for account {account_id}: {pos_data_response['error']}"
                    )
                    return Response(
                        {"open_positions": final_open_positions},
                        status=status.HTTP_200_OK,
                    )
                platform_positions_raw = pos_data_response.get("positions", [])
            except requests.RequestException as e:
                logger.error(
                    f"Error calling cTrader positions endpoint for account {account_id}: {str(e)}"
                )
                return Response(
                    {"open_positions": final_open_positions}, status=status.HTTP_200_OK
                )

            # Process cTrader positions
            for pos in platform_positions_raw:
                try:
                    ticket = int(pos.get("positionId"))
                except (ValueError, TypeError):
                    ticket = None

                if ticket is not None and ticket not in db_trade_order_ids:
                    trade_data_ctrader = pos.get("tradeData", {})
                    try:
                        volume = float(trade_data_ctrader.get("volume", "0")) / 100
                    except (ValueError, TypeError):
                        volume = 0.0
                    direction = trade_data_ctrader.get("tradeSide", "").upper()
                    try:
                        price_open = float(pos.get("price_open", pos.get("price", 0)))
                    except (ValueError, TypeError):
                        price_open = 0.0
                    try:
                        profit = float(pos.get("unrealized_pnl", 0))
                    except (ValueError, TypeError):
                        profit = 0.0
                    timestamp_raw = trade_data_ctrader.get("openTimestamp") or pos.get(
                        "utcLastUpdateTimestamp"
                    )
                    try:
                        time_val = int(float(timestamp_raw) / 1000)
                    except (ValueError, TypeError):
                        time_val = 0
                    symbol_str = pos.get("symbol")
                    if not symbol_str:
                        symbol_id = trade_data_ctrader.get("symbolId")
                        symbol_str = f"Unknown-{symbol_id}" if symbol_id else "Unknown"

                    pos_data = {
                        "trade_id": None,
                        "order_id": ticket,
                        "ticket": ticket,
                        "symbol": symbol_str,
                        "volume": volume,
                        "price_open": price_open,
                        "profit": profit,
                        "time": time_val,
                        "direction": direction,
                        "stop_loss": pos.get("stopLoss"),  # Add stop loss from cTrader
                        "profit_target": pos.get(
                            "takeProfit"
                        ),  # Add take profit from cTrader
                        "swap": pos.get("swap"),  # Assuming cTrader API provides this
                        "commission": pos.get(
                            "commission"
                        ),  # Assuming cTrader API provides this
                        # Add other relevant fields from cTrader position if needed
                        "source": "platform_only",
                    }
                    final_open_positions.append(pos_data)
        else:
            # Unsupported platform, just return DB trades
            return Response(
                {"open_positions": final_open_positions}, status=status.HTTP_200_OK
            )

        return Response(
            {"open_positions": final_open_positions}, status=status.HTTP_200_OK
        )


class AllOpenPositionsLiveView(APIView):
    """
    Retrieves live open positions from the appropriate trading platform.
    """

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_accounts = Account.objects.filter(user=request.user)
        final_all_open_positions = []
        db_trade_order_ids = set()
        account_id = self.request.query_params.get("account", None)
        if account_id:
            user_accounts = user_accounts.filter(Q(id=account_id) | Q(simple_id=True))

        # 1. Fetch all open trades from the database for the user
        db_trades = Trade.objects.filter(account__in=user_accounts, trade_status="open")
        from .serializers import TradeSerializer  # Ensure TradeSerializer is imported

        serialized_db_trades = TradeSerializer(db_trades, many=True).data

        for trade_data in serialized_db_trades:
            trade_data["source"] = "database"
            trade_data.pop("reason", None)  # Remove 'reason' field if it exists
            if trade_data.get("order_id") is not None:
                db_trade_order_ids.add(trade_data["order_id"])
            final_all_open_positions.append(trade_data)

        # 2. Fetch live positions from platforms for each account
        for account in user_accounts:
            platform_positions_raw = []
            if account.platform == "MT5":
                try:
                    mt5_account = account.mt5_account
                except MT5Account.DoesNotExist:
                    continue  # Skip to next account

                client = MT5APIClient(
                    base_url=settings.MT5_API_BASE_URL,
                    account_id=mt5_account.account_number,
                    password=mt5_account.encrypted_password,
                    broker_server=mt5_account.broker_server,
                    internal_account_id=str(account.id),
                )

                mt5_positions_result = client.get_open_positions()
                if "error" in mt5_positions_result:
                    logger.error(
                        f"MT5 get_open_positions error for account {account.id}: {mt5_positions_result['error']}"
                    )
                    continue

                platform_positions_raw = mt5_positions_result.get("open_positions", [])

                # Create a dictionary of DB trades by their order_id for quick lookup
                # This is done outside the loop for efficiency if processing multiple accounts,
                # but for clarity, we can re-filter or assume db_trades_dict is pre-populated
                # with all user's trades if this view aggregates all accounts.
                # For this specific view (AllOpenPositionsLiveView), db_trades_dict is built from all user's trades.

                db_trades_user_dict = {
                    t_data["order_id"]: t_data
                    for t_data in serialized_db_trades
                    if t_data.get("order_id") is not None
                    and t_data.get("account") == str(account.id)
                }

                for mt5_pos_live in platform_positions_raw:  # Renamed
                    ticket = mt5_pos_live.get("ticket")

                    live_pos_data = {
                        "ticket": ticket,
                        "symbol": mt5_pos_live.get("symbol"),
                        "volume": mt5_pos_live.get("volume"),
                        "price_open": mt5_pos_live.get("price_open"),
                        "current_pl": mt5_pos_live.get("profit"),
                        "swap": mt5_pos_live.get("swap"),
                        "commission": mt5_pos_live.get("commission"),
                        "stop_loss": mt5_pos_live.get("sl"),
                        "profit_target": mt5_pos_live.get("tp"),
                        "time": mt5_pos_live.get("time"),
                        "direction": (
                            "BUY" if mt5_pos_live.get("direction") == "BUY" else "SELL"
                        ),
                        "comment": mt5_pos_live.get("comment"),
                        "magic": mt5_pos_live.get("magic"),
                        "account_id": str(account.id),
                        "source": "platform_live",
                    }

                    # Check if this live position matches a DB trade already in final_all_open_positions
                    # and update it, or add as new if it's platform_only.

                    found_and_updated = False
                    for i, existing_pos in enumerate(final_all_open_positions):
                        if existing_pos.get("order_id") == ticket and existing_pos.get(
                            "account"
                        ) == str(
                            account.id
                        ):  # Match by ticket and account
                            # This DB trade corresponds to the live MT5 position. Update it.
                            # Start with existing_pos (DB data), then update/override with live_pos_data
                            merged_data = {**existing_pos, **live_pos_data}
                            merged_data["trade_id"] = existing_pos.get(
                                "id"
                            )  # our internal UUID
                            merged_data["order_id"] = ticket
                            merged_data["source"] = "platform_synced_with_db"
                            merged_data["current_pl"] = mt5_pos_live.get("profit")
                            merged_data["stop_loss"] = mt5_pos_live.get("sl")
                            merged_data["profit_target"] = mt5_pos_live.get("tp")
                            final_all_open_positions[i] = merged_data
                            found_and_updated = True
                            break

                    if not found_and_updated:
                        # This live position was not found in the initial list of DB trades,
                        # so it's a platform-only position for this account.
                        live_pos_data["trade_id"] = None
                        live_pos_data["order_id"] = ticket
                        live_pos_data["source"] = "platform_only"
                        final_all_open_positions.append(live_pos_data)

            elif account.platform == "cTrader":
                try:
                    ctrader_account = CTraderAccount.objects.get(account=account)
                except CTraderAccount.DoesNotExist:
                    continue

                payload = {
                    "access_token": ctrader_account.access_token,
                    "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
                }
                base_url = settings.CTRADER_API_BASE_URL
                positions_url = f"{base_url}/ctrader/positions"

                try:
                    pos_resp = requests.post(positions_url, json=payload, timeout=10)
                    pos_resp.raise_for_status()
                    pos_data_response = pos_resp.json()
                    if "error" in pos_data_response:
                        logger.error(
                            f"cTrader positions endpoint error for account {account.id}: {pos_data_response['error']}"
                        )
                        continue
                    platform_positions_raw = pos_data_response.get("positions", [])
                except requests.RequestException as e:
                    logger.error(
                        f"Error calling cTrader positions endpoint for account {account.id}: {str(e)}"
                    )
                    continue

                for pos in platform_positions_raw:
                    try:
                        ticket = int(pos.get("positionId"))
                    except (ValueError, TypeError):
                        ticket = None

                    if ticket is not None and ticket not in db_trade_order_ids:
                        trade_data_ctrader = pos.get("tradeData", {})
                        try:
                            volume = float(trade_data_ctrader.get("volume", "0")) / 100
                        except (ValueError, TypeError):
                            volume = 0.0
                        direction = trade_data_ctrader.get("tradeSide", "").upper()
                        try:
                            price_open = float(
                                pos.get("price_open", pos.get("price", 0))
                            )
                        except (ValueError, TypeError):
                            price_open = 0.0
                        try:
                            profit = float(pos.get("unrealized_pnl", 0))
                        except (ValueError, TypeError):
                            profit = 0.0
                        timestamp_raw = trade_data_ctrader.get(
                            "openTimestamp"
                        ) or pos.get("utcLastUpdateTimestamp")
                        try:
                            time_val = int(float(timestamp_raw) / 1000)
                        except (ValueError, TypeError):
                            time_val = 0
                        symbol_str = pos.get("symbol")
                        if not symbol_str:
                            symbol_id = trade_data_ctrader.get("symbolId")
                            symbol_str = (
                                f"Unknown-{symbol_id}" if symbol_id else "Unknown"
                            )

                        pos_data = {
                            "trade_id": None,
                            "order_id": ticket,
                            "ticket": ticket,
                            "symbol": symbol_str,
                            "volume": volume,
                            "price_open": price_open,
                            "profit": profit,
                            "time": time_val,
                            "direction": direction,
                            "stop_loss": pos.get(
                                "stopLoss"
                            ),  # Add stop loss from cTrader
                            "profit_target": pos.get(
                                "takeProfit"
                            ),  # Add take profit from cTrader
                            "swap": pos.get("swap"),
                            "commission": pos.get("commission"),
                            "account_id": str(account.id),  # Add account_id for context
                            "source": "platform_only",
                        }
                        final_all_open_positions.append(pos_data)
            # No 'else' needed here as we just skip unsupported platforms for aggregation

        return Response(
            {"open_positions": final_all_open_positions}, status=status.HTTP_200_OK
        )


class PendingOrdersView(APIView):
    """
    GET /trades/pending-orders/{account_id}/
    Returns all pending (limit/stop) orders for the given account from the trading platform.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        # 1️⃣ Verify ownership
        account = get_object_or_404(Account, id=account_id, user=request.user)

        # 2️⃣ Fetch pending orders from the service
        pending_orders_data = get_pending_orders(account)
        return Response(
            {"pending_orders": pending_orders_data}, status=status.HTTP_200_OK
        )


class AllPendingOrdersView(APIView):
    """
    GET /trades/all-pending-orders/
    Returns all pending (limit/stop) orders for all of the user's accounts from the trading platforms.
    """

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        accounts = Account.objects.filter(user=request.user)
        all_pending_orders = []
        account_id = self.request.query_params.get("account", None)
        if account_id:
            accounts = accounts.filter(Q(id=account_id) | Q(simple_id=True))

        for account in accounts:
            try:
                pending_orders_data = get_pending_orders(account)
                # Add account info to each order for better context on the frontend
                for order in pending_orders_data:
                    order["account_id"] = str(account.id)
                    order["account_name"] = account.name
                all_pending_orders.extend(pending_orders_data)
            except APIException as e:
                # Log the error and continue to the next account
                logger.error(
                    f"Could not fetch pending orders for account {account.id}: {e}"
                )
                continue
            except NotImplementedError:
                # Skip platforms that are not implemented
                continue
            except Exception as e:
                logger.error(
                    f"Unexpected error fetching pending orders for account {account.id}: {e}"
                )
                continue

        return Response(
            {"pending_orders": all_pending_orders}, status=status.HTTP_200_OK
        )


class CancelPendingOrderView(APIView):
    """
    DELETE /trades/pending-orders/<uuid:order_id>/cancel/
    Cancels a pending order.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, order_id: uuid.UUID):
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


# ----- Partial Close Trade -----
class PartialCloseTradeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(
        self, request, trade_id_str: str
    ):  # Renamed trade_id to trade_id_str for clarity
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


# ----- Watchlist Views -----
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
        # Q objects are used to create complex queries, here for OR condition
        return Watchlist.objects.filter(Q(user=user) | Q(is_global=True)).distinct()

    def perform_create(self, serializer):
        """
        Save the watchlist item.
        The serializer's create method handles setting the user or making it global.
        """
        serializer.save(
            user=(
                self.request.user
                if not serializer.validated_data.get("is_global")
                else None
            )
        )

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        Allow admin users to perform any action on global watchlists.
        Regular users can only modify their own non-global watchlists.
        """
        if self.action in ["update", "partial_update", "destroy"]:
            # For modifying or deleting, if the item is global, only admin can.
            # If not global, user must own it.
            # This check will be more robustly handled by get_object or in perform_destroy/update
            pass  # Further checks in perform_update/destroy
        elif self.action == "create":
            # Serializer handles permission for creating global items
            pass
        return super().get_permissions()

    def perform_update(self, serializer):
        instance = serializer.instance
        if instance.is_global and not self.request.user.is_staff:
            raise PermissionDenied("Only admins can modify global watchlist items.")
        if not instance.is_global and instance.user != self.request.user:
            raise PermissionDenied(
                "You do not have permission to modify this watchlist item."
            )

        # Check if trying to make an item global
        is_becoming_global = serializer.validated_data.get(
            "is_global", instance.is_global
        )
        if (
            is_becoming_global
            and not instance.is_global
            and not self.request.user.is_staff
        ):
            raise PermissionDenied("Only admins can make watchlist items global.")

        # If an admin is making it global, user should be set to None
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
            # This check is also implicitly handled by get_object for detail views if queryset is filtered by user
            # However, explicit check here is good for clarity and safety.
            raise PermissionDenied(
                "You do not have permission to delete this watchlist item."
            )
        instance.delete()

    # Potentially a custom action for admin to make an item global if not done via standard update
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def make_global(self, request, pk=None):
        watchlist_item = self.get_object()
        if not watchlist_item.is_global:
            watchlist_item.is_global = True
            watchlist_item.user = None  # Global items are not user-specific
            watchlist_item.save(update_fields=["is_global", "user"])
            return Response(
                {"status": "watchlist item set to global"}, status=status.HTTP_200_OK
            )
        return Response(
            {"status": "watchlist item is already global"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def remove_global(self, request, pk=None):
        watchlist_item = self.get_object()
        if watchlist_item.is_global:
            # When removing global, it doesn't automatically assign to a user.
            # It might be better to just delete it or let admin re-assign.
            # For now, let's assume removing global means it's no longer global.
            # It will still be an orphan if no user is set.
            # Admin might need to assign it to a user or delete it.
            watchlist_item.is_global = False
            # watchlist_item.user = request.user # Or some other logic
            watchlist_item.save(update_fields=["is_global"])
            return Response(
                {"status": "watchlist item removed from global"},
                status=status.HTTP_200_OK,
            )
        return Response(
            {"status": "watchlist item is not global"},
            status=status.HTTP_400_BAD_REQUEST,
        )
