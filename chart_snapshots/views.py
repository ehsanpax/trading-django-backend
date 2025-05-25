from django.db import models # Added for Q objects
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import ChartSnapshotConfig, ChartSnapshot
from .serializers import ChartSnapshotConfigSerializer, ChartSnapshotSerializer, AdhocChartSnapshotRequestSerializer
from .tasks import generate_chart_snapshot_task

class ChartSnapshotConfigViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Chart Snapshot Configurations.
    Users can create, view, update, and delete their configurations.
    They can also trigger the generation of a snapshot from a configuration.
    """
    serializer_class = ChartSnapshotConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        This view should only return configurations belonging to the currently authenticated user.
        """
        return ChartSnapshotConfig.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """
        Automatically set the user to the currently authenticated user.
        """
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'], url_path='execute')
    def execute_snapshot(self, request, pk=None):
        """
        Triggers the generation of a chart snapshot for this configuration.
        Optionally accepts a 'journal_entry_id' in the request data to link the snapshot.
        """
        config = self.get_object()
        journal_entry_id = request.data.get('journal_entry_id', None)
        
        # Basic validation for journal_entry_id if provided (e.g., is UUID) could be added here.

        task = generate_chart_snapshot_task.delay(config_id=config.id, journal_entry_id=journal_entry_id, adhoc_settings=None)
        
        return Response(
            {'status': 'Snapshot generation tasked.', 'task_id': task.id},
            status=status.HTTP_202_ACCEPTED
        )

class ChartSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing Chart Snapshots.
    Users can only view snapshots linked to their configurations or their journal entries.
    """
    serializer_class = ChartSnapshotSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        This view should return snapshots that:
        1. Belong to a config owned by the user.
        OR
        2. Are linked to a journal entry where the trade is owned by the user.
           (Assuming TradeJournal -> Trade -> User relationship exists and is relevant for permission)
        For simplicity now, filtering by config user. More complex permission can be added.
        """
        # This queryset can be complex depending on how you want to scope access.
        # Option A: Snapshots from user's configs
        # user_configs = ChartSnapshotConfig.objects.filter(user=self.request.user)
        # return ChartSnapshot.objects.filter(config__in=user_configs)
        
        # Option B: Snapshots linked to user's journal entries (more direct for journaling context)
        # This requires TradeJournal to have a user link or through Trade.
        # Assuming TradeJournal.trade.user is the path.
        # return ChartSnapshot.objects.filter(journal_entry__trade__user=self.request.user)

        # For now, let's allow viewing if the snapshot's config is user's OR journal entry's trade is user's
        # This requires careful model relationships.
        # A simpler approach for now: filter by snapshots whose config is owned by the user,
        # or whose journal entry's trade is owned by the user.
        # If a snapshot has no config, it must have a journal entry linked to the user.

        # Simplest for now: snapshots linked to user's configs.
        # Snapshots linked to journal entries where the journal's trade belongs to the user.
        # This needs to be refined based on exact ownership logic of TradeJournal.
        
        # Let's assume TradeJournal.trade.account.user is the path to the user
        qs = ChartSnapshot.objects.filter(
            models.Q(config__user=self.request.user) |
            models.Q(journal_entry__trade__account__user=self.request.user)
        ).distinct()
        # If 'trade.account' is not the correct path, this will need adjustment.
        # Fallback to simpler config-based permission if journal path is complex/unknown:
        # qs = ChartSnapshot.objects.filter(config__user=self.request.user) # Simpler alternative
        return qs.distinct() # Ensure distinct if Q objects cause duplicates


class AdhocChartSnapshotCreateView(generics.GenericAPIView):
    """
    API endpoint to create a chart snapshot with ad-hoc settings.
    """
    serializer_class = AdhocChartSnapshotRequestSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            adhoc_settings = {
                "symbol": validated_data["symbol"],
                "timeframe": validated_data["timeframe"],
                "indicator_settings": validated_data["indicator_settings"],
            }
            journal_entry_id = validated_data.get("journal_entry_id")

            task = generate_chart_snapshot_task.delay(
                config_id=None, 
                journal_entry_id=journal_entry_id, 
                adhoc_settings=adhoc_settings
            )
            return Response(
                {'status': 'Adhoc snapshot generation tasked.', 'task_id': task.id},
                status=status.HTTP_202_ACCEPTED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
