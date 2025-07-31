from rest_framework import viewsets, permissions
from .models import Prompt, ChatSession
from .serializers import (
    PromptSerializer,
    SessionExecutionSerializer,
    ChatSessionSerializer,
    TradeJournalSerializer,
)
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework import status
from trade_journal.models import TradeJournal


class PromptViewSet(viewsets.ModelViewSet):
    queryset = Prompt.objects.all()
    serializer_class = PromptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        This view should return a list of all prompts
        for the currently authenticated user, or globally shared prompts.
        """
        user = self.request.user
        if user.is_authenticated:
            return Prompt.objects.filter(user=user) | Prompt.objects.filter(
                is_globally_shared=True
            )
        return Prompt.objects.filter(is_globally_shared=True)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StoreSessionExecutionViewset(APIView):
    serializer_class = SessionExecutionSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        session_execution = serializer.save()
        return Response(
            {
                "message": "Session execution stored successfully",
                "id": str(session_execution.id),
            },
            status=status.HTTP_201_CREATED,
        )


class ChatSessionViewset(ModelViewSet):
    serializer_class = ChatSessionSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = ChatSession.objects.all()

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(user=self.request.user)
            .order_by("-created_at")
        )


class TradeJournalViewset(ModelViewSet):
    serializer_class = TradeJournalSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    queryset = TradeJournal.objects.all()
    pagination_class = None  # Disable pagination for simplicity

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(trade__account__user=self.request.user)
            .order_by("-created_at")
        )
