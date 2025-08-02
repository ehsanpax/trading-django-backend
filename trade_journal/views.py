from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import TradeJournal, TradeJournalAttachment
from .serializers import TradeJournalSerializer, TradeJournalAttachmentSerializer
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q


class TradeJournalViewSet(viewsets.ModelViewSet):
    """
    ViewSet for listing, creating, updating, and deleting Trade Journal entries.
    Only journals for trades owned by the authenticated user are returned.
    """

    queryset = TradeJournal.objects.all()
    serializer_class = TradeJournalSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        account_id = self.request.query_params.get("account_id", None)
        user = self.request.user
        # Base queryset for user's journals, ensuring through trade -> account -> user
        queryset = TradeJournal.objects.filter(trade__account__user=user)
        if account_id:
            # Filter by specific account if provided
            queryset = queryset.filter(
                Q(trade__account__id=account_id) | Q(trade__account__simple_id=True)
            )

        # Allow filtering by a specific trade_id passed as a query parameter
        trade_id = self.request.query_params.get("trade", None)
        if trade_id:
            # Ensure the trade_id is valid (e.g., UUID format) if necessary,
            # or let the DB handle potential errors if format is incorrect.
            # For simplicity, direct filter:
            queryset = queryset.filter(trade__id=trade_id)

        return queryset.order_by("-created_at")  # Optional: order by creation date


class TradeJournalAttachmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for handling attachments in a single HTTP request.
    """

    queryset = TradeJournalAttachment.objects.all()
    serializer_class = TradeJournalAttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Only attachments for journals belonging to this user
        return TradeJournalAttachment.objects.filter(
            journal__trade__account__user=self.request.user
        )

    def create(self, request, *args, **kwargs):
        """
        Handle multiple file uploads in a single request.
        Expects:
          - 'journal' in form data for the journal ID
          - multiple files in 'files' (or another field name)
        """
        journal_id = request.data.get("journal")
        if not journal_id:
            return Response(
                {"detail": "Missing 'journal' field"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate that the journal belongs to this user
        journal_instance = get_object_or_404(
            TradeJournal, id=journal_id, trade__account__user=request.user
        )

        # Retrieve the list of files from the 'files' key
        files = request.FILES.getlist("files")
        if not files:
            return Response(
                {"detail": "No files were provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        attachments = []
        for file in files:
            attach = TradeJournalAttachment(journal=journal_instance, file=file)
            attach.save()
            attachments.append(attach)

        # Serialize all newly created attachments
        serializer = self.get_serializer(attachments, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
