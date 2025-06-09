import os # For listing strategy templates
from pathlib import Path # For constructing path to strategy templates
from django.conf import settings # To get BASE_DIR

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
    BotVersionCreateSerializer, StartLiveRunSerializer
)
from . import services
from accounts.models import Account # For assigning account to bot

# Add logger to views
import logging
logger = logging.getLogger(__name__)
from rest_framework.exceptions import PermissionDenied


class ListStrategyTemplatesAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated] # Or AllowAny if templates are not sensitive

    def get(self, request, *args, **kwargs):
        try:
            templates_dir = Path(settings.BASE_DIR) / 'bots' / 'strategy_templates'
            if not templates_dir.is_dir():
                logger.warning(f"Strategy templates directory not found: {templates_dir}")
                return Response({"error": "Strategy templates directory not found."}, status=status.HTTP_404_NOT_FOUND)

            templates = []
            for item in os.listdir(templates_dir):
                if item.endswith(".py") and item != "__init__.py":
                    # You could also try to import and get a docstring or a specific variable
                    # for a more descriptive name, but filename is simplest for now.
                    templates.append({
                        "filename": item,
                        "display_name": item.replace(".py", "").replace("_", " ").title() # e.g., Footprint V1
                    })
            
            return Response(templates, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error listing strategy templates: {e}", exc_info=True)
            return Response({"error": "Could not list strategy templates."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BotViewSet(viewsets.ModelViewSet):
    queryset = Bot.objects.all()
    serializer_class = BotSerializer
    permission_classes = [permissions.IsAuthenticated] # Adjust as needed

    def get_queryset(self):
        # Filter bots by the current user if not staff/superuser
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return Bot.objects.all()
        return Bot.objects.filter(created_by=user)

    def perform_create(self, serializer):
        # created_by is handled in serializer's create method using self.context['request'].user
        # account_id can be passed in request data and handled by serializer
        bot_instance = serializer.save() # Get the created bot instance

        # Automatically create a default BotVersion
        if bot_instance:
            try:
                logger.info(f"Bot {bot_instance.id} created. Attempting to create default BotVersion.")
                services.create_default_bot_version(bot_instance)
            except Exception as e:
                # Log the error but don't let it fail the Bot creation response.
                # The Bot is created; the default version is a bonus.
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

    # Custom create for BotVersion as it involves code hashing from file content
    def create(self, request, *args, **kwargs):
        serializer = BotVersionCreateSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            try:
                bot = get_object_or_404(Bot, id=data['bot_id'])
                # Ensure user has permission to create version for this bot
                if not (request.user.is_staff or request.user.is_superuser or bot.created_by == request.user):
                    return Response({"detail": "You do not have permission to create a version for this bot."},
                                    status=status.HTTP_403_FORBIDDEN)

                # Assuming strategy_file_content is the actual python code string
                # In a real app, you might get this from a file upload or a specific field.
                # For now, we expect it directly in the payload.
                # The Bot model's strategy_template field should store the filename (e.g., "footprint_v1.py")
                # This filename is used by load_strategy_template service.
                # The actual code content is passed here for hashing.
                
                bot_version = services.create_bot_version(
                    bot=bot,
                    strategy_code=data['strategy_file_content'], # This is the actual code
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
        # Add permission check if needed: does user own the bot_version?
        bot_version = serializer.validated_data.get('bot_version')
        user = self.request.user
        if not (user.is_staff or user.is_superuser or bot_version.bot.created_by == user):
            raise PermissionDenied("You do not have permission for this bot version.")
        serializer.save()


class BacktestRunViewSet(viewsets.ReadOnlyModelViewSet): # Usually ReadOnly once created
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

class LiveRunViewSet(viewsets.ReadOnlyModelViewSet): # Usually ReadOnly once created/managed by actions
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
                # Permission check: Does user own the bot_version?
                bot_version = get_object_or_404(BotVersion, id=data['bot_version_id'])
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                    return Response({"detail": "You do not have permission for this bot version."},
                                    status=status.HTTP_403_FORBIDDEN)
                
                backtest_run = services.launch_backtest(
                    bot_version_id=data['bot_version_id'],
                    backtest_config_id=data['backtest_config_id'],
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
                # Permission check inside service is also good, but can be here too
                bot_version = get_object_or_404(BotVersion, id=bot_version_id)
                if not (request.user.is_staff or request.user.is_superuser or bot_version.bot.created_by == request.user):
                     return Response({"detail": "You do not have permission to start a live run for this bot version."},
                                    status=status.HTTP_403_FORBIDDEN)

                live_run = services.start_bot_live_run(bot_version_id)
                response_serializer = LiveRunSerializer(live_run)
                return Response(response_serializer.data, status=status.HTTP_202_ACCEPTED)
            except BotVersion.DoesNotExist as e:
                 return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            except DjangoValidationError as ve: # Catch validation errors from service
                return Response({"detail": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error starting live run: {e}", exc_info=True)
                return Response({"detail": "An error occurred while starting the live run."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StopLiveRunAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, live_run_id, *args, **kwargs): # live_run_id from URL
        try:
            live_run = get_object_or_404(LiveRun, id=live_run_id)
            # Permission check
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
