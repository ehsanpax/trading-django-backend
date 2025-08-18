import os # For listing strategy templates
from pathlib import Path # For constructing path to strategy templates
from django.conf import settings # To get BASE_DIR
import dataclasses # For inspecting dataclass fields
from datetime import datetime # Added for timestamp conversion

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.authtoken.models import Token
from .models import Bot, BotVersion, BacktestConfig, BacktestRun, LiveRun
from .serializers import (
    BotSerializer, BotVersionSerializer, BacktestConfigSerializer,
    BacktestRunSerializer, LiveRunSerializer, LaunchBacktestSerializer,
    BotVersionCreateSerializer, CreateLiveRunSerializer, # Updated serializer name
    BacktestChartDataSerializer, BacktestOhlcvDataSerializer,
    BacktestIndicatorDataSerializer, BacktestTradeMarkerSerializer,
    StrategyMetadataSerializer, IndicatorMetadataSerializer # New metadata serializers
)
from .models import BacktestOhlcvData, BacktestIndicatorData
from . import services
from .compiler import GraphCompiler
from accounts.models import Account
from bots.services import StrategyManager
from core.registry import indicator_registry, operator_registry, action_registry
from analysis.utils.data_processor import load_m1_data_from_parquet, resample_data
import pandas as pd
from decimal import Decimal

# Add logger to views
import logging
logger = logging.getLogger(__name__)
from rest_framework.exceptions import PermissionDenied
import json # Added for debug export
from rest_framework.throttling import ScopedRateThrottle
from bots.ai_strategy import generate_strategy_config, ProviderError, ValidationError as ProviderValidationError
import uuid

def validate_ohlcv_bars(bars, logger=None, label="OHLCV"):
    prev_time = None
    seen_times = set()
    problems = 0
    for idx, bar in enumerate(bars):
        cur_time = bar["time"]
        # Check strictly increasing
        if prev_time is not None and cur_time <= prev_time:
            if logger:
                logger.error(
                    f"{label}: Non-increasing time at idx={idx}: time={cur_time}, prev={prev_time}"
                )
            problems += 1
        # Check duplicate times
        if cur_time in seen_times:
            if logger:
                logger.error(
                    f"{label}: Duplicate time at idx={idx}: time={cur_time}"
                )
            problems += 1
        seen_times.add(cur_time)
        prev_time = cur_time
    if logger:
        logger.info(f"{label}: Validated {len(bars)} bars, {problems} problems found.")
        logger.info(f"{label}: First 30 times: {[bar['time'] for bar in bars[:30]]}")


class StrategyMetadataAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            metadata = StrategyManager.get_available_strategies_metadata()
            serializer = StrategyMetadataSerializer(metadata, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching strategy metadata: {e}", exc_info=True)
            return Response({"error": "Could not retrieve strategy metadata."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class IndicatorMetadataAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            metadata = StrategyManager.get_available_indicators_metadata()
            return Response(metadata, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching indicator metadata: {e}", exc_info=True)
            return Response({"error": "Could not retrieve indicator metadata."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NodeMetadataAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        indicators_meta = StrategyManager.get_available_indicators_metadata()
        nodes = {
            "indicators": indicators_meta,
            "operators": [
                {"name": name, "params": op.PARAMS_SCHEMA}
                for name, op in operator_registry.get_all_operators().items()
            ],
            "actions": [
                {"name": name, "params": ac.PARAMS_SCHEMA}
                for name, ac in action_registry.get_all_actions().items()
            ],
        }
        return Response(nodes, status=status.HTTP_200_OK)


class BotViewSet(viewsets.ModelViewSet):
    queryset = Bot.objects.all()
    serializer_class = BotSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Bot.objects.all()
        return Bot.objects.filter(created_by=user)

    def perform_create(self, serializer):
        bot_instance = serializer.save()
        if bot_instance:
            try:
                logger.info(f"Bot {bot_instance.id} created. Attempting to create default BotVersion.")
                # The create_default_bot_version no longer relies on bot.strategy_template
                services.create_default_bot_version(bot_instance)
            except Exception as e:
                logger.error(f"Failed to create default BotVersion for new Bot {bot_instance.id} during Bot creation: {e}", exc_info=True)

class BotVersionViewSet(viewsets.ModelViewSet):
    queryset = BotVersion.objects.all()
    serializer_class = BotVersionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            qs = BotVersion.objects.select_related('bot').all()
        else:
            qs = BotVersion.objects.select_related('bot').filter(bot__created_by=user)

        bot_id = self.request.query_params.get('bot_id')
        if bot_id:
            qs = qs.filter(bot_id=bot_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = BotVersionCreateSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                bot = get_object_or_404(Bot, id=data['bot_id'])
                if not (request.user.is_staff or request.user.is_superuser or bot.created_by == request.user):
                    return Response({"detail": "You do not have permission to create a version for this bot."},
                                    status=status.HTTP_403_FORBIDDEN)

                bot_version = services.create_bot_version(
                    bot=bot,
                    version_name=data.get('version_name'),
                    strategy_name=data['strategy_name'],
                    strategy_params=data['strategy_params'],
                    indicator_configs=data['indicator_configs'],
                    notes=data.get('notes')
                )
                response_serializer = BotVersionSerializer(bot_version)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            except Bot.DoesNotExist:
                return Response({"detail": "Bot not found."}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve: # Catch Django's ValidationError for serializer validation errors
                logger.error(f"Validation error creating BotVersion: {ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}", exc_info=True)
                return Response({"detail": ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error creating BotVersion: {e}", exc_info=True)
                return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='from-graph')
    def create_from_graph(self, request, *args, **kwargs):
        # Simplified serializer for graph-based creation
        bot_id = request.data.get('bot_id')
        version_name = request.data.get('version_name')
        strategy_graph = request.data.get('strategy_graph')
        notes = request.data.get('notes')

        if not bot_id or not strategy_graph:
            return Response({"detail": "bot_id and strategy_graph are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            bot = get_object_or_404(Bot, id=bot_id)
            if not (request.user.is_staff or request.user.is_superuser or bot.created_by == request.user):
                return Response({"detail": "You do not have permission to create a version for this bot."},
                                status=status.HTTP_403_FORBIDDEN)

            # Validate the graph with the compiler
            compiler = GraphCompiler(strategy_graph)
            compiler.validate()

            bot_version = BotVersion.objects.create(
                bot=bot,
                version_name=version_name,
                strategy_graph=strategy_graph,
                notes=notes,
                # Set other fields to default/empty if they don't apply
                strategy_name="graph_based_strategy",
                strategy_params={},
                indicator_configs=[]
            )
            response_serializer = BotVersionSerializer(bot_version)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except Bot.DoesNotExist:
            return Response({"detail": "Bot not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as ve:
            return Response({"detail": f"Invalid strategy graph: {ve}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating BotVersion from graph: {e}", exc_info=True)
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='strategy-graph')
    def strategy_graph(self, request, pk=None):
        bot_version = self.get_object()
        graph_data = {}
        if bot_version.strategy_graph:
            graph_data = bot_version.strategy_graph
        # Fallback for older versions that might use strategy_params
        elif bot_version.strategy_params:
            graph_data = bot_version.strategy_params
        
        response_data = {
            'version_name': bot_version.version_name,
            'strategy_graph': graph_data
        }
        return Response(response_data, status=status.HTTP_200_OK)


class BacktestConfigViewSet(viewsets.ModelViewSet):
    queryset = BacktestConfig.objects.all()
    serializer_class = BacktestConfigSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = BacktestConfig.objects.select_related('bot_version__bot').all()
        if not (user.is_staff or user.is_superuser):
            qs = qs.filter(bot_version__bot__created_by=user)

        bot_version_id = self.request.query_params.get('bot_version_id')
        if bot_version_id:
            qs = qs.filter(bot_version_id=bot_version_id)
        return qs

    def perform_create(self, serializer):
        bot_version = serializer.validated_data.get('bot_version')
        user = self.request.user
        if not (user.is_staff or user.is_superuser or bot_version.bot.created_by == user):
            raise PermissionDenied("You do not have permission for this bot version.")
        serializer.save()


class BacktestRunViewSet(viewsets.ModelViewSet):
    queryset = BacktestRun.objects.all()
    serializer_class = BacktestRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = BacktestRun.objects.select_related('config__bot_version__bot').all()
        if not (user.is_staff or user.is_superuser):
            qs = qs.filter(config__bot_version__bot__created_by=user)

        config_id = self.request.query_params.get('config_id')
        if config_id:
            qs = qs.filter(config_id=config_id)
        bot_version_id = self.request.query_params.get('bot_version_id')
        if bot_version_id:
            qs = qs.filter(config__bot_version_id=bot_version_id)
        return qs

class LiveRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LiveRun.objects.all()
    serializer_class = LiveRunSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = LiveRun.objects.select_related('bot_version__bot').all()
        if not (user.is_staff or user.is_superuser):
            qs = qs.filter(bot_version__bot__created_by=user)

        bot_version_id = self.request.query_params.get('bot_version_id')
        if bot_version_id:
            qs = qs.filter(bot_version_id=bot_version_id)
        return qs

# --- Action-specific API Views ---

class LaunchBacktestAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LaunchBacktestSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                config = get_object_or_404(BacktestConfig, id=data['config_id'])
                if not (request.user.is_staff or request.user.is_superuser or config.bot_version.bot.created_by == request.user):
                    return Response({"detail": "You do not have permission for this backtest configuration."},
                                    status=status.HTTP_403_FORBIDDEN)

                # Create the BacktestRun instance first
                backtest_run = BacktestRun.objects.create(
                    config=config,
                    instrument_symbol=data['instrument_symbol'],
                    data_window_start=data['data_window_start'],
                    data_window_end=data['data_window_end'],
                    status='PENDING'
                )

                # Then, launch the backtest with the new backtest_run_id
                services.launch_backtest(
                    backtest_run_id=backtest_run.id,
                    random_seed=data.get('random_seed')
                )
                
                response_serializer = BacktestRunSerializer(backtest_run)
                return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)
            except BacktestConfig.DoesNotExist as e:
                 return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve:
                logger.error(f"Validation error launching backtest: {ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}", exc_info=True)
                return Response({"detail": ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error launching backtest: {e}", exc_info=True)
                return Response({"detail": "An error occurred while launching the backtest."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StartLiveRunAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = CreateLiveRunSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                bot_version = get_object_or_404(BotVersion, id=data['bot_version_id'])
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                    return Response({"detail": "You do not have permission to start a live run for this bot version."}, status=status.HTTP_403_FORBIDDEN)

                account = get_object_or_404(Account, id=data['account_id'], user=request.user)

                live_run = LiveRun.objects.create(
                    bot_version=bot_version,
                    instrument_symbol=data['instrument_symbol'],
                    account=account,
                    timeframe=data.get('timeframe') or 'M1',
                    decision_mode=data.get('decision_mode') or 'CANDLE',
                    status='PENDING'
                )

                services.start_bot_live_run(live_run_id=live_run.id)
                live_run.refresh_from_db()
                response_serializer = LiveRunSerializer(live_run)
                return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)
            except BotVersion.DoesNotExist as e:
                return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve:
                logger.error(f"Validation error starting live run: {ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}", exc_info=True)
                return Response({"detail": ve.message_dict if hasattr(ve, 'message_dict') else str(ve)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error starting live run: {e}", exc_info=True)
                return Response({"detail": "An error occurred while starting the live run."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StopLiveRunAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, live_run_id, *args, **kwargs):
        try:
            live_run = get_object_or_404(LiveRun, id=live_run_id)
            if not (request.user.is_staff or request.user.is_superuser or live_run.bot_version.bot.created_by == request.user):
                return Response({"detail": "You do not have permission to stop this live run."},
                                status=status.HTTP_403_FORBIDDEN)

            updated_live_run = services.stop_bot_live_run(live_run_id)
            response_serializer = LiveRunSerializer(updated_live_run)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except LiveRun.DoesNotExist as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error stopping live run {live_run_id}: {e}", exc_info=True)
            return Response({"detail": "An error occurred while stopping the live run."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BacktestChartDataAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, backtest_run_id, *args, **kwargs):
        logger.info(f"Fetching chart data for BacktestRun ID: {backtest_run_id}")
        backtest_run = get_object_or_404(BacktestRun, id=backtest_run_id)

        user = request.user
        if not (user.is_staff or user.is_superuser or backtest_run.config.bot_version.bot.created_by == user):
            raise PermissionDenied("You do not have permission to access chart data for this backtest run.")

        try:
            # Fetch OHLCV data from the database
            ohlcv_queryset = BacktestOhlcvData.objects.filter(backtest_run=backtest_run).order_by('timestamp')
            ohlcv_data_lwc = [
                {
                    "time": int(o.timestamp.timestamp()),
                    "open": float(o.open),
                    "high": float(o.high),
                    "low": float(o.low),
                    "close": float(o.close),
                }
                for o in ohlcv_queryset
            ]

            # Fetch Indicator data from the database
            indicator_queryset = BacktestIndicatorData.objects.filter(backtest_run=backtest_run).order_by('indicator_name', 'timestamp')

            # Group indicator series by (base indicator + params), aggregate outputs under each group
            indicators_registry_map = indicator_registry.get_all_indicators()
            registered_names_by_len = sorted(indicators_registry_map.keys(), key=len, reverse=True)

            grouped_indicators: dict[str, dict] = {}

            for record in indicator_queryset:
                full_name = record.indicator_name  # e.g. "dmi_plus_di_length_14" or "stochastic_rsi_stoch_rsi_k_length_14"

                # 1) Detect base indicator name using the longest registered prefix
                base_name = None
                remainder = None
                for reg_name in registered_names_by_len:
                    prefix = f"{reg_name}_"
                    if full_name.startswith(prefix):
                        base_name = reg_name
                        remainder = full_name[len(prefix):]
                        break
                if base_name is None:
                    # Fallback: take the first token as base
                    parts = full_name.split('_')
                    base_name = parts[0]
                    remainder = full_name[len(base_name) + 1:] if len(parts) > 1 else ''

                # 2) Resolve indicator class and metadata
                try:
                    indicator_cls = indicator_registry.get_indicator(base_name)
                    pane_type = getattr(indicator_cls, 'PANE_TYPE', 'OVERLAY')
                    possible_outputs = getattr(indicator_cls, 'OUTPUTS', []) or []
                except Exception:
                    indicator_cls = None
                    pane_type = 'OVERLAY'
                    possible_outputs = []

                # 3) Detect output name from remainder using OUTPUTS list (handles underscores in output names)
                output_name = None
                params_part = ''
                if remainder:
                    for out in sorted(possible_outputs, key=len, reverse=True):
                        if remainder == out or remainder.startswith(out + '_'):
                            output_name = out
                            params_part = remainder[len(out):]
                            if params_part.startswith('_'):
                                params_part = params_part[1:]
                            break
                    if output_name is None:
                        # Fallback to the first token
                        tok = remainder.split('_')[0]
                        output_name = tok
                        params_part = remainder[len(tok):]
                        if params_part.startswith('_'):
                            params_part = params_part[1:]
                else:
                    # No remainder: treat as single-output where output equals base
                    output_name = base_name
                    params_part = ''

                # 4) Build a stable group key: base + params (exclude output)
                group_key = f"{base_name}_{params_part}" if params_part else base_name

                # 5) Add data point
                point = {"time": int(record.timestamp.timestamp()), "value": float(record.value)}
                grp = grouped_indicators.setdefault(group_key, {"pane_type": pane_type, "outputs": {}})
                grp["outputs"].setdefault(output_name, []).append(point)

            # 6) Sort each output series by time
            for grp in grouped_indicators.values():
                for out_name, series_points in grp["outputs"].items():
                    series_points.sort(key=lambda k: k['time'])

            indicator_data_grouped = grouped_indicators

            # Fetch and serialize Trade Markers from the backtest run's JSON log
            raw_trades_log = backtest_run.simulated_trades_log or []
            processed_trade_markers = []
            for t in raw_trades_log:
                try:
                    entry_dt = datetime.fromisoformat(t['entry_timestamp'].replace('Z', '+00:00'))
                    entry_time_s = int(entry_dt.timestamp())

                    exit_time_s = None
                    if t.get('exit_timestamp'):
                        exit_dt = datetime.fromisoformat(t['exit_timestamp'].replace('Z', '+00:00'))
                        exit_time_s = int(exit_dt.timestamp())

                    processed_trade_markers.append({
                        "entry_timestamp": entry_time_s,
                        "entry_price": float(t['entry_price']),
                        "direction": t['direction'],
                        "exit_timestamp": exit_time_s,
                        "exit_price": float(t.get('exit_price')),
                        "pnl": float(t.get('pnl')),
                    })
                except (ValueError, KeyError, TypeError) as e:
                    logger.error(f"Error processing trade marker: {t} - {e}", exc_info=True)
                    continue

            trade_markers_serialized = BacktestTradeMarkerSerializer(processed_trade_markers, many=True).data

            # Prepare the final response data
            chart_data = {
                "ohlcv_data": ohlcv_data_lwc,
                "indicator_data": indicator_data_grouped,
                "trade_markers": trade_markers_serialized,
                "backtest_run_id": str(backtest_run.id),
                "instrument_symbol": backtest_run.instrument_symbol,
                "original_timeframe": backtest_run.config.timeframe,
                "data_window_start": backtest_run.data_window_start.isoformat(),
                "data_window_end": backtest_run.data_window_end.isoformat()
            }

            return Response(chart_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching chart data for BacktestRun {backtest_run_id}: {e}", exc_info=True)
            return Response({"error": f"Could not retrieve chart data: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StrategyConfigGenerateAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'strategy_gen'

    def post(self, request, *args, **kwargs):
        from .serializers import StrategyConfigGenerateRequestSerializer, StrategyConfigGenerateResponseSerializer

        serializer = StrategyConfigGenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Optional ownership/permission check: only enforce if user is authenticated and bot_version looks like a UUID
        bot_version_id = data.get('bot_version')
        if request.user.is_authenticated and bot_version_id:
            try:
                uuid.UUID(str(bot_version_id))
                try:
                    bv = BotVersion.objects.select_related('bot').get(id=bot_version_id)
                    user = request.user
                    if not (user.is_staff or user.is_superuser or bv.bot.created_by == user):
                        return Response({"detail": "You do not have permission for this bot version."}, status=status.HTTP_403_FORBIDDEN)
                except BotVersion.DoesNotExist:
                    # Allow non-existent if external versions are used; comment out to enforce existence
                    pass
            except Exception:
                # Non-UUID identifiers allowed
                pass

        idem_key = request.headers.get('Idempotency-Key') or request.META.get('HTTP_IDEMPOTENCY_KEY')
        req_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        # Extract user token from Authorization header (Bearer <JWT>) if present
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        user_token = None
        if isinstance(auth_header, str) and auth_header.startswith('Bearer '):
            user_token = auth_header.split(' ', 1)[1].strip()

        try:
            result = generate_strategy_config(
                bot_version=bot_version_id,
                prompt=data['prompt'],
                user_id=(request.user.id if request.user.is_authenticated else 'anonymous'),
                idempotency_key=idem_key,
                options=data.get('options') or {},
                user_token=user_token,
            )
        except ProviderValidationError as e:
            payload = getattr(e, 'payload', None)
            # Log validation details for debugging
            try:
                payload_snippet = json.dumps(payload)[:1000] if isinstance(payload, dict) else str(payload)[:1000]
            except Exception:
                payload_snippet = str(payload)[:1000]
            logger.warning(f"[AI] validation error req_id={req_id} idem_key={idem_key} payload={payload_snippet}")
            if isinstance(payload, dict):
                return Response(payload, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            return Response({"detail": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ProviderError as e:
            msg = str(e)
            logger.error(f"[AI] provider error req_id={req_id} idem_key={idem_key} msg={msg}")
            if msg == 'timeout':
                return Response({"detail": "Provider timeout"}, status=status.HTTP_504_GATEWAY_TIMEOUT)
            if msg == 'circuit_open':
                return Response({"detail": "Service temporarily unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return Response({"detail": "Upstream provider error"}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            logger.exception(f"strategy-config generate failed: {e}")
            return Response({"detail": "Internal error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        resp = StrategyConfigGenerateResponseSerializer(result).data
        response = Response(resp, status=status.HTTP_200_OK)
        response["X-Request-ID"] = req_id
        if idem_key:
            response["Idempotency-Key"] = idem_key
        return response

class NodeSchemaAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        def to_jsonschema_param(prop_schema: dict) -> dict:
            if not isinstance(prop_schema, dict):
                return {}
            type_map = {
                'int': 'integer', 'integer': 'integer',
                'float': 'number', 'number': 'number',
                'str': 'string', 'string': 'string',
                'bool': 'boolean', 'boolean': 'boolean',
                'object': 'object', 'array': 'array',
            }
            js: dict = {}
            ptype = prop_schema.get('type')
            if ptype:
                js['type'] = type_map.get(ptype, ptype)
            # enums / options
            if isinstance(prop_schema.get('enum'), list):
                js['enum'] = prop_schema['enum']
            elif isinstance(prop_schema.get('options'), list):
                js['enum'] = prop_schema['options']
            # numeric/string constraints
            if 'min' in prop_schema and js.get('type') in ('number', 'integer'):
                js['minimum'] = prop_schema['min']
            if 'max' in prop_schema and js.get('type') in ('number', 'integer'):
                js['maximum'] = prop_schema['max']
            if 'min_length' in prop_schema and js.get('type') == 'string':
                js['minLength'] = prop_schema['min_length']
            if 'max_length' in prop_schema and js.get('type') == 'string':
                js['maxLength'] = prop_schema['max_length']
            if 'pattern' in prop_schema and js.get('type') == 'string':
                js['pattern'] = prop_schema['pattern']
            if 'description' in prop_schema:
                js['description'] = prop_schema['description']
            if 'default' in prop_schema:
                js['default'] = prop_schema['default']
            return js

        def build_params_object_schema(params_schema: dict) -> dict:
            props = {}
            required = []
            for pname, pspec in (params_schema or {}).items():
                props[pname] = to_jsonschema_param(pspec)
                # Treat params without defaults and not explicitly optional as required
                if not (isinstance(pspec, dict) and (pspec.get('optional') or 'default' in pspec)):
                    required.append(pname)
            schema = {"type": "object", "properties": props, "additionalProperties": False}
            if required:
                schema['required'] = required
            return schema

        # Build indicator rules
        indicators_map = indicator_registry.get_all_indicators()
        indicator_names = sorted(list(indicators_map.keys()))
        indicator_allOf = []
        for name, cls in indicators_map.items():
            params_schema = getattr(cls, 'PARAMS_SCHEMA', {}) or {}
            outputs = getattr(cls, 'OUTPUTS', []) or []
            pane_type = getattr(cls, 'PANE_TYPE', None)
            visual_schema = getattr(cls, 'VISUAL_SCHEMA', None)
            visual_defaults = getattr(cls, 'VISUAL_DEFAULTS', None)
            then_schema = {
                "properties": {
                    "name": {"const": name},
                    "params": build_params_object_schema(params_schema),
                },
                "required": ["name", "params"],
                # Non-standard extensions to help agents
                "x-outputs": outputs,
                "x-pane_type": pane_type,
                "x-visual_schema": visual_schema,
                "x-visual_defaults": visual_defaults,
            }
            indicator_allOf.append({
                "if": {"properties": {"name": {"const": name}}, "required": ["name"]},
                "then": then_schema,
            })

        # Build operator rules
        operators_map = operator_registry.get_all_operators()
        operator_names = sorted(list(operators_map.keys()))
        operator_allOf = []
        for name, cls in operators_map.items():
            params_schema = getattr(cls, 'PARAMS_SCHEMA', {}) or {}
            operator_allOf.append({
                "if": {"properties": {"name": {"const": name}}, "required": ["name"]},
                "then": {
                    "properties": {
                        "name": {"const": name},
                        "params": build_params_object_schema(params_schema),
                    },
                    "required": ["name", "params"],
                },
            })

        # Build action rules
        actions_map = action_registry.get_all_actions()
        action_names = sorted(list(actions_map.keys()))
        action_allOf = []
        for name, cls in actions_map.items():
            params_schema = getattr(cls, 'PARAMS_SCHEMA', {}) or {}
            action_allOf.append({
                "if": {"properties": {"name": {"const": name}}, "required": ["name"]},
                "then": {
                    "properties": {
                        "name": {"const": name},
                        "params": build_params_object_schema(params_schema),
                    },
                    "required": ["name", "params"],
                },
            })

        # --- New: Risk and Filters JSON Schemas ---
        # Risk schema supported by SectionedStrategy and engine gates
        risk_schema = {
            "type": "object",
            "properties": {
                "risk_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.01,
                    "description": "Fraction of account equity to risk per trade (e.g., 0.01 = 1%)."
                },
                "default_rr": {
                    "type": "number",
                    "minimum": 0,
                    "default": 2.0,
                    "description": "Default reward-to-risk multiple used to derive TP when tp is not provided."
                },
                "fixed_lot_size": {
                    "type": "number",
                    "minimum": 0,
                    "default": 1.0,
                    "description": "Fallback fixed position size when dynamic sizing cannot be computed."
                },
                "max_open_positions": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Maximum concurrent open positions allowed by the engine gate."
                },
                "daily_loss_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Max daily drawdown percentage after which entries are blocked (engine gate)."
                },
                "sl": {
                    "type": "object",
                    "description": "Stop-loss configuration.",
                    "properties": {
                        "type": {"type": "string", "enum": ["atr", "pct"], "default": "atr"},
                        "mult": {"type": "number", "default": 1.5, "description": "Multiplier applied to ATR for SL distance (when type=atr)."},
                        "length": {"type": "integer", "default": 14, "description": "ATR length (when type=atr)."},
                        "value": {"type": "number", "default": 0.01, "description": "Percent SL (e.g., 0.01 = 1%) when type=pct."}
                    },
                    "additionalProperties": False
                },
                "take_profit_pips": {
                    "type": "number",
                    "description": "Absolute TP distance in pips from entry (SectionedStrategy convenience). If omitted, TP can be derived from default_rr and SL."
                }
            },
            "additionalProperties": True
        }

        # Filters schema supported by evaluate_filters
        filters_schema = {
            "type": "object",
            "properties": {
                "allowed_days_of_week": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": "Allowed trading days (0=Mon .. 6=Sun)."
                },
                "allowed_sessions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {
                                "type": "string",
                                "pattern": "^([01]?\\d|2[0-3]):[0-5]\\d$",
                                "description": "Session start time in HH:MM (24h, UTC)."
                            },
                            "end": {
                                "type": "string",
                                "pattern": "^([01]?\\d|2[0-3]):[0-5]\\d$",
                                "description": "Session end time in HH:MM (24h, UTC)."
                            }
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False
                    },
                    "description": "Time windows during which entries are allowed."
                }
            },
            "additionalProperties": True
        }

        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{getattr(settings, 'BACKEND_URL', '')}/api/bots/nodes/schema/",
            "title": "No-Code Strategy Nodes Schema",
            "type": "object",
            "properties": {
                "indicators": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": indicator_names},
                            "params": {"type": "object"},
                        },
                        "required": ["name", "params"],
                        "allOf": indicator_allOf,
                        "additionalProperties": False,
                    },
                },
                "operators": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": operator_names},
                            "params": {"type": "object"},
                        },
                        "required": ["name", "params"],
                        "allOf": operator_allOf,
                        "additionalProperties": False,
                    },
                },
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": action_names},
                            "params": {"type": "object"},
                        },
                        "required": ["name", "params"],
                        "allOf": action_allOf,
                        "additionalProperties": False,
                    },
                },
                # New: add risk and filters sections
                "risk": risk_schema,
                "filters": filters_schema,
            },
            "required": ["indicators", "operators", "actions"],
            "additionalProperties": False,
            # Also include a non-standard catalog to help agents render docs without evaluating schema
            "x-catalog": {
                "indicators": [
                    {
                        "name": n,
                        "outputs": getattr(indicators_map[n], 'OUTPUTS', []) or [],
                        "pane_type": getattr(indicators_map[n], 'PANE_TYPE', None),
                        "visual_schema": getattr(indicators_map[n], 'VISUAL_SCHEMA', None),
                        "visual_defaults": getattr(indicators_map[n], 'VISUAL_DEFAULTS', None),
                    }
                    for n in indicator_names
                ],
                "operators": [{"name": n} for n in operator_names],
                "actions": [{"name": n} for n in action_names],
                # New: include hints for risk/filters
                "risk": {
                    "defaults": {"risk_pct": 0.01, "default_rr": 2.0, "sl": {"type": "atr", "mult": 1.5, "length": 14}},
                    "notes": [
                        "default_rr is used to derive TP from SL when tp is missing (also respected in backtests).",
                        "take_profit_pips provides a fixed TP distance alternative."
                    ]
                },
                "filters": {
                    "notes": [
                        "allowed_days_of_week uses 0=Mon..6=Sun",
                        "allowed_sessions times are interpreted in UTC"
                    ]
                },
            },
        }
        return Response(schema, status=status.HTTP_200_OK)
