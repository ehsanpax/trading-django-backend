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
            serializer = IndicatorMetadataSerializer(metadata, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching indicator metadata: {e}", exc_info=True)
            return Response({"error": "Could not retrieve indicator metadata."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NodeMetadataAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        nodes = {
            "indicators": StrategyManager.get_available_indicators_metadata(),
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


class BacktestRunViewSet(viewsets.ReadOnlyModelViewSet):
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
        serializer = CreateLiveRunSerializer(data=request.data) # Use CreateLiveRunSerializer
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                bot_version = get_object_or_404(BotVersion, id=data['bot_version_id'])
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                     return Response({"detail": "You do not have permission to start a live run for this bot version."},
                                    status=status.HTTP_403_FORBIDDEN)

                # First, create the LiveRun object
                live_run = LiveRun.objects.create(
                    bot_version=bot_version,
                    instrument_symbol=data['instrument_symbol'],
                    status='PENDING' # Set initial status
                )

                # Then, trigger the service function with the created LiveRun's ID
                services.start_bot_live_run(live_run_id=live_run.id)
                
                # Re-fetch the run to get its updated status (e.g., PENDING)
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
                return Response({"detail": "An error occurred while starting the live run."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
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
            indicator_data_grouped = {}
            temp_indicator_groups = {}
            for record in indicator_queryset:
                if record.indicator_name not in temp_indicator_groups:
                    temp_indicator_groups[record.indicator_name] = []
                point = {"time": int(record.timestamp.timestamp()), "value": float(record.value)}
                temp_indicator_groups[record.indicator_name].append(point)

            for name, points in temp_indicator_groups.items():
                indicator_data_grouped[name] = {
                    "data": sorted(points, key=lambda k: k['time'])
                }

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
