import os # For listing strategy templates
from pathlib import Path # For constructing path to strategy templates
from django.conf import settings # To get BASE_DIR
import dataclasses # For inspecting dataclass fields

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
    BotVersionCreateSerializer, StartLiveRunSerializer,
    BacktestChartDataSerializer, BacktestOhlcvDataSerializer, # Added
    BacktestIndicatorDataSerializer, BacktestTradeMarkerSerializer # Added
)
from .models import BacktestOhlcvData, BacktestIndicatorData # Added
from . import services
from accounts.models import Account # For assigning account to bot

# Add logger to views
import logging
logger = logging.getLogger(__name__)
from rest_framework.exceptions import PermissionDenied


class ListStrategyTemplatesAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated] 

    def get(self, request, *args, **kwargs):
        try:
            templates_dir = Path(settings.BASE_DIR) / 'bots' / 'strategy_templates'
            if not templates_dir.is_dir():
                logger.warning(f"Strategy templates directory not found: {templates_dir}")
                return Response({"error": "Strategy templates directory not found."}, status=status.HTTP_404_NOT_FOUND)

            templates = []
            for item in os.listdir(templates_dir):
                if item.endswith(".py") and item != "__init__.py":
                    templates.append({
                        "filename": item,
                        "display_name": item.replace(".py", "").replace("_", " ").title() 
                    })
            
            return Response(templates, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error listing strategy templates: {e}", exc_info=True)
            return Response({"error": "Could not list strategy templates."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class StrategyTemplateParametersAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_type_name(self, type_hint):
        """Helper to get a string representation of a type hint."""
        if hasattr(type_hint, '__name__'):
            return type_hint.__name__
        elif hasattr(type_hint, '_name') and type_hint._name: # For typing.Literal
            return f"Literal[{', '.join(map(repr, type_hint.__args__))}]"
        elif hasattr(type_hint, '__origin__'): # For Optional, Union, etc.
            origin_name = self.get_type_name(type_hint.__origin__)
            args_names = ", ".join(self.get_type_name(arg) for arg in type_hint.__args__)
            return f"{origin_name}[{args_names}]"
        return str(type_hint)

    def get(self, request, template_filename, *args, **kwargs):
        try:
            StrategyClass = services.load_strategy_template(template_filename)
            if not StrategyClass:
                return Response({"error": f"Strategy template {template_filename} could not be loaded."}, status=status.HTTP_404_NOT_FOUND)

            if not hasattr(StrategyClass, 'ParamsDataclass') or not dataclasses.is_dataclass(StrategyClass.ParamsDataclass):
                logger.warning(f"Strategy {template_filename} does not have a valid 'ParamsDataclass' attribute.")
                # Fallback to DEFAULT_PARAMS if ParamsDataclass is not available
                if hasattr(StrategyClass, 'DEFAULT_PARAMS'):
                    params_data = []
                    for name, default_value in StrategyClass.DEFAULT_PARAMS.items():
                        params_data.append({
                            "name": name,
                            "type": type(default_value).__name__,
                            "default": default_value,
                            "label": name.replace("_", " ").title(),
                            "help_text": "" # No help text available in this fallback
                        })
                    return Response(params_data, status=status.HTTP_200_OK)
                return Response({"error": f"Strategy {template_filename} does not define parameters in a discoverable way (no ParamsDataclass or DEFAULT_PARAMS)."}, status=status.HTTP_404_NOT_FOUND)

            ParamsDataclass = StrategyClass.ParamsDataclass
            default_param_values = StrategyClass.DEFAULT_PARAMS if hasattr(StrategyClass, 'DEFAULT_PARAMS') else {}
            
            parameters_info = []
            for field in dataclasses.fields(ParamsDataclass):
                param_info = {
                    "name": field.name,
                    "type": self.get_type_name(field.type),
                    "default": default_param_values.get(field.name, field.default if field.default != dataclasses.MISSING else None),
                    "label": field.name.replace("_", " ").title(), # Simple label generation
                    "help_text": field.metadata.get("help_text", "") # Assuming help_text in metadata
                }
                parameters_info.append(param_info)
            
            return Response(parameters_info, status=status.HTTP_200_OK)

        except FileNotFoundError:
            return Response({"error": f"Strategy template file '{template_filename}' not found."}, status=status.HTTP_404_NOT_FOUND)
        except ImportError as e:
            logger.error(f"Error importing or finding class in {template_filename}: {e}", exc_info=True)
            return Response({"error": f"Could not load strategy from {template_filename}: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Error getting parameters for {template_filename}: {e}", exc_info=True)
            return Response({"error": f"Could not retrieve parameters for {template_filename}."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

                strategy_code_input = data.get('strategy_file_content') # Field is now optional
                actual_strategy_code = None

                if not strategy_code_input: # If empty string or None
                    if not bot.strategy_template:
                        logger.warning(f"Bot {bot.id} has no default strategy_template and no strategy_file_content provided for new version.")
                        return Response({"detail": "Bot has no default strategy template and no strategy code was provided."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    try:
                        logger.info(f"No strategy_file_content provided for BotVersion. Using default template: {bot.strategy_template} for bot {bot.id}")
                        actual_strategy_code = services.get_strategy_template_content(bot.strategy_template)
                    except FileNotFoundError:
                        logger.error(f"Default strategy template file '{bot.strategy_template}' not found for bot {bot.id} when creating version.")
                        return Response({"detail": f"Default strategy template file '{bot.strategy_template}' not found."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    except Exception as e_get_content:
                        logger.error(f"Error getting content for default template '{bot.strategy_template}' for bot {bot.id}: {e_get_content}", exc_info=True)
                        return Response({"detail": f"Error reading default strategy template: {str(e_get_content)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                else:
                    actual_strategy_code = strategy_code_input
                
                if actual_strategy_code is None: # Should not happen if logic above is correct, but as a safeguard
                    logger.error(f"Strategy code could not be determined for BotVersion creation for bot {bot.id}.")
                    return Response({"detail": "Strategy code could not be determined."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                bot_version = services.create_bot_version(
                    bot=bot,
                    strategy_code=actual_strategy_code, 
                    params=data['params'],
                    notes=data.get('notes')
                )
                response_serializer = BotVersionSerializer(bot_version)
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            except Bot.DoesNotExist:
                return Response({"detail": "Bot not found."}, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"Error creating BotVersion: {e}", exc_info=True)
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
                bot_version = get_object_or_404(BotVersion, id=data['bot_version_id'])
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                    return Response({"detail": "You do not have permission for this bot version."},
                                    status=status.HTTP_403_FORBIDDEN)
                
                backtest_run = services.launch_backtest(
                    bot_version_id=data['bot_version_id'],
                    backtest_config_id=data['backtest_config_id'],
                    instrument_symbol=data['instrument_symbol'], 
                    data_window_start=data['data_window_start'],
                    data_window_end=data['data_window_end']
                )
                response_serializer = BacktestRunSerializer(backtest_run)
                return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)
            except (BotVersion.DoesNotExist, BacktestConfig.DoesNotExist) as e:
                 return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve:
                return Response({"detail": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error launching backtest: {e}", exc_info=True)
                return Response({"detail": "An error occurred while launching the backtest."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StartLiveRunAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = StartLiveRunSerializer(data=request.data)
        if serializer.is_valid():
            bot_version_id = serializer.validated_data['bot_version_id']
            try:
                bot_version = get_object_or_404(BotVersion, id=bot_version_id)
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                     return Response({"detail": "You do not have permission to start a live run for this bot version."},
                                    status=status.HTTP_403_FORBIDDEN)

                live_run = services.start_bot_live_run(
                    bot_version_id=bot_version_id,
                    instrument_symbol=serializer.validated_data['instrument_symbol'] 
                )
                response_serializer = LiveRunSerializer(live_run)
                return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)
            except BotVersion.DoesNotExist as e:
                 return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve: 
                return Response({"detail": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
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

        # Permission check: Ensure the user can access this backtest run's data
        user = request.user
        if not (user.is_staff or user.is_superuser or backtest_run.config.bot_version.bot.created_by == user):
            raise PermissionDenied("You do not have permission to access chart data for this backtest run.")

        try:
            # 1. Fetch OHLCV data
            ohlcv_queryset = BacktestOhlcvData.objects.filter(backtest_run=backtest_run).order_by('timestamp')
            # For ApexCharts, OHLC data is often [{ x: timestamp, y: [o, h, l, c] }]
            # We'll format this here for simplicity, though it could also be done in the serializer or frontend
            ohlcv_data_apex = [
                {"x": int(o.timestamp.timestamp() * 1000), "y": [o.open, o.high, o.low, o.close]} 
                for o in ohlcv_queryset
            ]
            # If not formatting for Apex here, use the serializer directly:
            # ohlcv_data_serialized = BacktestOhlcvDataSerializer(ohlcv_queryset, many=True).data


            # 2. Fetch Indicator data and group by indicator_name
            indicator_queryset = BacktestIndicatorData.objects.filter(backtest_run=backtest_run).order_by('indicator_name', 'timestamp')
            
            indicator_data_grouped = {}
            for record in indicator_queryset:
                # ApexCharts usually expects [{ x: timestamp, y: value }] for simple line series
                point = {"x": int(record.timestamp.timestamp() * 1000), "y": record.value}
                if record.indicator_name not in indicator_data_grouped:
                    indicator_data_grouped[record.indicator_name] = [point]
                else:
                    indicator_data_grouped[record.indicator_name].append(point)
            # If not formatting for Apex here, serialize directly and group later or pass flat list:
            # indicator_data_serialized = BacktestIndicatorDataSerializer(indicator_queryset, many=True).data


            # 3. Fetch and serialize Trade Markers from simulated_trades_log
            # The BacktestRun.simulated_trades_log is already a list of dicts.
            # We can pass it directly to the BacktestTradeMarkerSerializer if its structure matches.
            # The serializer expects fields like 'entry_timestamp', 'entry_price', etc.
            raw_trades_log = backtest_run.simulated_trades_log or []
            trade_markers_serialized = BacktestTradeMarkerSerializer(raw_trades_log, many=True).data
            
            # Prepare data for the main BacktestChartDataSerializer
            # Note: The BacktestChartDataSerializer expects specific structures.
            # We are manually constructing the dict here to match ApexCharts common formats.
            # If BacktestChartDataSerializer was designed to take querysets and do this formatting,
            # that would be an alternative.
            
            chart_data = {
                "ohlcv_data": ohlcv_data_apex, # Using pre-formatted data
                "indicator_data": indicator_data_grouped, # Using pre-formatted and grouped data
                "trade_markers": trade_markers_serialized,
                # Optional: Add metadata
                "backtest_run_id": backtest_run.id,
                "instrument_symbol": backtest_run.instrument_symbol,
                "data_window_start": backtest_run.data_window_start.isoformat(),
                "data_window_end": backtest_run.data_window_end.isoformat()
            }
            
            # We are not using BacktestChartDataSerializer directly here because we pre-formatted
            # for Apex. If we were, it would be:
            # final_serializer = BacktestChartDataSerializer(data_for_main_serializer_instance)
            # return Response(final_serializer.data, status=status.HTTP_200_OK)

            return Response(chart_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching chart data for BacktestRun {backtest_run_id}: {e}", exc_info=True)
            return Response({"error": f"Could not retrieve chart data: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
